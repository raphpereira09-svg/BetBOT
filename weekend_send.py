# weekend_send.py — Analyse complète des matchs du week‑end (Top‑5) avec affichage chronologique
# - Filtre UNIQUEMENT le prochain/présent week‑end (ven 00:00 → dim 23:59:59, Europe/Paris)
# - Couvre tous les matchs des 5 grands championnats (ou ODDS_SPORTS personnalisé)
# - Pour chaque match : heure locale, score attendu, top 3 scores exacts, H/D/A, Over2.5, meilleur bet (H2H ou O/U 2.5)
# - Message Telegram découpé automatiquement si trop long
import os, math, pandas as pd, pytz, requests
from datetime import timedelta
from odds_providers import fetch_soccer_odds
from foot_model import summarize_match
from foot_selector import build_consensus, best_price_and_book

WEEKDAY_FR = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]
MONTH_FR   = ["janv.","févr.","mars","avr.","mai","juin","juil.","août","sept.","oct.","nov.","déc."]

def send_long_message(chat_id: str, text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]; url = f"https://api.telegram.org/bot{token}/sendMessage"
    CHUNK = 3500
    for i in range(0, len(text), CHUNK):
        part = text[i:i+CHUNK]
        r = requests.post(url, data={"chat_id": chat_id, "text": part, "parse_mode":"HTML"}, timeout=30)
        if r.status_code >= 400:
            try: detail = r.json()
            except Exception: detail = {"raw": r.text}
            raise RuntimeError(f"Telegram error {r.status_code}: {detail}")

def fmt_day_header(dt):
    return f"<b>{WEEKDAY_FR[dt.weekday()]} {dt.day} {MONTH_FR[dt.month-1]}</b>"

def weekend_window(now_paris):
    """Retourne (début_local, fin_local) pour le week‑end courant/prochain (ven..dim).
       Lundi‑Jeudi -> prochain ven..dim ; Vendredi‑Dimanche -> ce ven..dim.
    """
    wd = now_paris.weekday()  # Lun=0..Dim=6
    if wd <= 3:  # Lun..Jeu -> prochain vendredi
        days_to_fri = 4 - wd
        fri = (now_paris + timedelta(days=days_to_fri)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:        # Ven..Dim -> vendredi courant
        fri = (now_paris - timedelta(days=wd - 4)).replace(hour=0, minute=0, second=0, microsecond=0)
    sun = (fri + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)
    return fri, sun

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    now_paris = pd.Timestamp.now(tz)
    win_start, win_end = weekend_window(now_paris)

    min_ev = float(os.getenv("WEEKEND_MIN_EV","0.01"))
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # 1) Récup cotes
    df = fetch_soccer_odds()
    if df.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nAucune rencontre disponible.")
        return

    # 2) Heures locales + filtre sur ce/prochain week‑end UNIQUEMENT
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(tz)
    df = df[(df["start_dt"] >= win_start) & (df["start_dt"] <= win_end)].copy()
    if df.empty:
        send_long_message(chat_id, f"<b>📣 Foot — Rapport week‑end</b>\nAucun match entre {win_start.strftime('%a %d %b')} et {win_end.strftime('%a %d %b')}.")
        return

    # 3) Séparation marchés + consensus
    df_h2h = df[(df["market"]=="h2h") & (df["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df[(df["market"]=="totals") & (df["outcome"].isin(["over","under"]))].copy()
    if "point" in df_tot.columns: df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")

    cons = build_consensus(df_h2h)
    if cons.empty:
        send_long_message(chat_id, "<b>📣 Foot — Rapport week‑end</b>\nImpossible de calculer le consensus marché (données insuffisantes).")
        return

    cons = cons.merge(df[["match_id","start_dt"]].drop_duplicates("match_id"), on="match_id", how="left")
    cons = cons.sort_values(["start_dt","league","teams"]).reset_index(drop=True)

    # 4) Construction du message (chrono) avec top scores exacts
    title = (f"<b>📣 Foot — Week‑end</b> "
             f"({WEEKDAY_FR[win_start.weekday()]} {win_start.day} {MONTH_FR[win_start.month-1]}"
             f" → {WEEKDAY_FR[win_end.weekday()]} {win_end.day} {MONTH_FR[win_end.month-1]})\n"
             f"Affichage par <b>date/heure</b> • Seuil value: EV ≥ {min_ev:.0%}.\n— — —")
    parts = [title]
    current_day = None
    n_value = 0; n_total = 0

    for _, r in cons.iterrows():
        n_total += 1
        mid = r["match_id"]; start = r["start_dt"]

        # En‑tête de jour
        if (current_day is None) or (start.date() != current_day.date()):
            current_day = start
            parts.append("\n" + fmt_day_header(start))

        # Tranches de marché
        g_h2h = df_h2h[df_h2h["match_id"]==mid]
        g_tot = df_tot[df_tot["match_id"]==mid]

        # Modèle de score (Dixon‑Coles calé sur H/D/A marché)
        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        hda = f"{summ['p_home']*100:.0f}/{summ['p_draw']*100:.0f}/{summ['p_away']*100:.0f}%"
        p_over = summ['totals_over'].get(2.5, float('nan'))
        over_s = (f"{p_over*100:.0f}%" if not math.isnan(p_over) else "—")
        top3 = ", ".join([f"{i}–{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])

        # Meilleur bet (H2H ou O/U 2.5)
        best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]
            price, book = best_price_and_book(sub)
            if price and price>1.0:
                p = float(summ[f"p_{side}"]); ev = p*price - 1.0
                cand = {"type":"H2H","sel":side.capitalize(),"odds":price,"p":p,"ev":ev,"book":book}
                if (best is None) or (cand["ev"]>best["ev"]): best = cand
        tot25 = g_tot[g_tot["point"].round(2)==2.50]
        if not tot25.empty and not math.isnan(p_over):
            over_odds, over_book = best_price_and_book(tot25[tot25["outcome"]=="over"])
            under_odds, under_book= best_price_and_book(tot25[tot25["outcome"]=="under"])
            ev_over = p_over*over_odds - 1.0 if over_odds and over_odds>1.0 else -9
            p_under = 1.0 - p_over; ev_under = p_under*under_odds - 1.0 if under_odds and under_odds>1.0 else -9
            if ev_over >= ev_under and (best is None or ev_over > best["ev"]):
                best = {"type":"Totals","sel":"Over 2.5","odds":over_odds,"p":p_over,"ev":ev_over,"book":over_book}
            elif ev_under > (best["ev"] if best else -9):
                best = {"type":"Totals","sel":"Under 2.5","odds":under_odds,"p":p_under,"ev":ev_under,"book":under_book}

        # Mise en forme
        time_s = start.strftime("%H:%M")
        head = f"🕒 <b>{time_s}</b> — {r['teams']}"
        info = f"🧮 {mean_score}   •   H/D/A {hda}   •   Over2.5 {over_s}"
        scores = f"🔢 Scores probables: {top3}"

        if best and best["ev"] >= min_ev:
            n_value += 1
            pick = f"✅ <b>{best['type']}</b> {best['sel']} @ <b>{best['odds']:.2f}</b>  •  P {best['p']*100:.1f}%  •  EV <b>{best['ev']*100:.1f}%</b>  •  {best['book']}"
        else:
            lean = ("Home" if summ['p_home']>max(summ['p_draw'], summ['p_away'])
                    else ("Away" if summ['p_away']>max(summ['p_home'], summ['p_draw']) else "Draw"))
            pick = f"⚪️ Lean {lean} (pas de value)"

        parts.append(f"{head}\n{info}\n{scores}\n{pick}")

    header = parts[0] + f"\n<b>{n_value}</b> value bets détectés sur <b>{n_total}</b> matchs analysés."
    message = header + "\n" + "\n".join(parts[1:])
    send_long_message(chat_id, message)

if __name__ == '__main__':
    main()
