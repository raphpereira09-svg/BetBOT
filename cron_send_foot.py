# cron_send_foot.py — Football-only sender with score prediction + DRY_RUN + erreurs claires
import os, sys, pandas as pd, pytz, requests
from odds_providers import fetch_soccer_odds
from foot_selector import select_picks

def send_telegram(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant(s). Ajoute les secrets dans GitHub → Settings → Secrets → Actions.")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=20)
    # Affiche les erreurs Telegram de façon lisible
    if r.status_code >= 400:
        try:
            detail = r.json()
        except Exception:
            detail = {"raw": r.text}
        raise RuntimeError(f"Telegram error {r.status_code}: {detail}")
    return r

def fmt_pick(p):
    return (
        f"🏟️ <b>{p['league']}</b>\n{p['teams']}\n"
        f"🧮 Score attendu: <b>{p['mean_score']}</b>\n"
        f"📊 Top scores: {p['top_scores']}\n"
        f"— — — — —\n"
        f"✅ <b>{p['pick_type']}</b>: <b>{p['selection']}</b>\n"
        f"🎲 Cote: <b>{p['price']:.2f}</b> • P: <b>{p['prob']*100:.1f}%</b>\n"
        f"📈 EV: <b>{p['ev']*100:.2f}%</b> • Book: {p['book']}"
    )

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    min_ev = float(os.getenv("MIN_EV","0.02"))
    max_picks = int(os.getenv("MAX_PICKS","3"))
    dry = os.getenv("DRY_RUN","0") == "1"

    # 1) Récup odds
    try:
        df = fetch_soccer_odds()
    except Exception as e:
        print(f"[ERR] The Odds API: {e}", file=sys.stderr)
        sys.exit(1)

    if df.empty:
        msg = "<b>📣 Foot — Sélections</b>\nAucun match trouvé (The Odds API vide)."
        if dry:
            print(msg)
            return
        send_telegram(msg)
        return

    # 2) Sélection
    picks, diags = select_picks(df, min_ev=min_ev, max_picks=max_picks)

    # 3) Sortie
    if picks:
        parts = ["<b>📣 Foot — Sélections</b>"]
        for p in picks:
            p["start_local"] = pd.to_datetime(p["start_time_iso"], utc=True).tz_convert(tz).strftime("%a %d %b • %H:%M")
            parts.append(fmt_pick(p) + f"\n🕒 {p['start_local']}")
        text = "\n\n".join(parts)
    else:
        head = "<b>📣 Foot — Sélections</b>\nAucun pick ≥ seuil EV.\n\n<b>🔎 Diagnostics (quelques matches)</b>"
        rows = []
        for d in diags[:5]:
            pl = []
            if pd.notna(d.get("p_over25", float('nan'))):
                pl.append(f"Over2.5 {d['p_over25']*100:.1f}%")
            pl.append(f"H/D/A {d['p_home']*100:.0f}/{d['p_draw']*100:.0f}/{d['p_away']*100:.0f}%")
            rows.append(f"• <b>{d['league']}</b> — {d['teams']}\n  Score exp: {d['mean_score']} | {', '.join(pl)}\n  Top: {d['top_scores']}")
        text = head + "\n" + "\n".join(rows)

    # 4) Envoi / Dry-run
    if dry:
        print("[DRY_RUN] Message prêt mais non envoyé :\n", text)
        return

    try:
        send_telegram(text)
    except Exception as e:
        # Erreurs Telegram fréquentes : 401 (token invalide), 400 "chat not found" (chat_id faux ou /start non fait),
        # 403 "blocked by the user" (bot bloqué), etc.
        print(f"[ERR] Envoi Telegram: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
