# cron_send.py — v4-lite sender with adaptive backoff + diagnostics
import os, pandas as pd, pytz, requests
from strategy import pick_daily_bets, fractional_kelly
from signals import build_signal_table, adjust_probabilities
from odds_providers import fetch_today_odds_http

def fmt_msg(rows):
    if not rows:
        return "<b>📣 Sélections du jour</b>\nPas de value bet aujourd'hui."
    parts = ["<b>📣 Sélections du jour</b>"]
    for r in rows:
        parts.append(
            "🏟️ <b>{league}</b>\n{teams}\n🕒 {start}\n— — — — —\n"
            "🎯 <b>{market}</b> • <b>{outcome}</b>\n"
            "💼 <b>Book</b> {book}\n"
            "🎲 <b>Cote</b> {odds:.2f}\n"
            "💸 <b>Mise conseillée</b> {stake:.2f}€\n"
            "<code>ID: {mid}</code>".format(**r)
        )
    return "\n\n".join(parts)

def fmt_diag(df_top):
    if df_top.empty: return ""
    lines = ["<b>🔎 Diagnostic (proches de la sélection)</b>"]
    for _, r in df_top.iterrows():
        bits = []
        if "n_books" in r: bits.append(f"books={int(r['n_books'])}")
        if "best_vs_median" in r and pd.notna(r["best_vs_median"]): bits.append(f"bvm={r['best_vs_median']:.3f}")
        if "edge_use" in r: bits.append(f"edge={r['edge_use']:.2%}")
        bits.append(f"ev={r['ev']:.2%}")
        lines.append(f"• <b>{r.get('league')}</b> — {r.get('teams')} → {r.get('outcome')} @ {float(r.get('book_odds',0)):.2f} ({why})")
    return "\n".join(lines)

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    min_odds = float(os.getenv("MIN_ODDS","1.30"))
    min_edge = float(os.getenv("MIN_EDGE","0.015"))
    kelly    = float(os.getenv("KELLY_FRACTION","0.20"))
    max_bets = int(os.getenv("MAX_BETS","3"))
    bankroll = float(os.getenv("BANKROLL_START","100"))

    df = fetch_today_odds_http()
    if df.empty:
        text = "<b>📣 Sélections du jour</b>\nAucun évènement renvoyé par The Odds API."
    else:
        df = df[df["book_odds"] >= min_odds].copy()
        sig = build_signal_table()
        if not sig.empty:
            df = adjust_probabilities(df, sig)
        else:
            df["adj_prob"] = df.get("model_prob", 0.5)
            df["blend_prob"] = df.get("model_prob", 0.5)
        picks = pick_daily_bets(df, min_edge=min_edge, max_bets=max_bets, use_adj=True)
        if not picks.empty:
            rows = []
            for _, r in picks.iterrows():
                prob = float(r.get("blend_prob", r.get("adj_prob", r.get("model_prob", 0.0))) or 0.0)
                stake_pct = fractional_kelly(prob, r["book_odds"], fraction=kelly)
                stake = round(bankroll * stake_pct, 2)
                start_local = pd.to_datetime(r["start_time_iso"], utc=True).tz_convert(tz).strftime("%a %d %b %Y • %H:%M")
                rows.append(dict(league=r["league"], teams=r["teams"], start=start_local, market=r["market"],
                                 outcome=r["outcome"], book=r["book"], odds=float(r["book_odds"]), stake=stake, mid=r["match_id"]))
            text = fmt_msg(rows)
        else:
            prob_col = "blend_prob" if "blend_prob" in df.columns else ("adj_prob" if "adj_prob" in df.columns else "model_prob")
            df["edge_use"] = df[prob_col].astype(float) - (1.0/df["book_odds"].astype(float))
            df["ev"] = df[prob_col].astype(float) * df["book_odds"].astype(float) - 1.0
            near = df.sort_values(["ev","edge_use","book_odds"], ascending=[False,False,False]).head(5)
            # Build diag lines
            diags = []
            for _, r in near.iterrows():
                parts = []
                if "n_books" in r: parts.append(f"books={int(r['n_books'])}")
                if "best_vs_median" in r and pd.notna(r["best_vs_median"]): parts.append(f"bvm={r['best_vs_median']:.3f}")
                if "edge_use" in r: parts.append(f"edge={r['edge_use']:.2%}")
                parts.append(f"ev={r['ev']:.2%}")
                why = ", ".join(parts)
                diags.append(f"• <b>{r.get('league')}</b> — {r.get('teams')} → {r.get('outcome')} @ {float(r.get('book_odds',0)):.2f} ({why})")
            text = "<b>📣 Sélections du jour</b>\nAucune sélection retenue, même après backoff.\n\n" + "\n".join(diags)

    token = os.environ["TELEGRAM_BOT_TOKEN"]; chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    resp.raise_for_status()

if __name__ == "__main__":
    main()
