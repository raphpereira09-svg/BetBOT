# cron_send.py — one-shot sender for GitHub Actions (no polling)
import os
import pandas as pd
import pytz
import datetime as dt
import requests

from strategy import pick_daily_bets, fractional_kelly
from signals import build_signal_table, adjust_probabilities
from odds_providers import fetch_today_odds_http

def fmt_msg(rows):
    if not rows:
        return "<b>📣 Sélections du jour</b>\nPas de value bet aujourd'hui."
    parts = ["<b>📣 Sélections du jour</b>"]
    for r in rows:
        parts.append(
            "🏟️ <b>{league}</b>\n"
            "{teams}\n"
            "🕒 {start}\n"
            "— — — — —\n"
            "🎯 <b>{market}</b> • <b>{outcome}</b>\n"
            "💼 <b>Book</b> {book}\n"
            "🎲 <b>Cote</b> {odds:.2f}\n"
            "💸 <b>Mise conseillée</b> {stake:.2f}€\n"
            "<code>ID: {mid}</code>".format(**r)
        )
    return "\n\n".join(parts)

def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris")
    min_odds = float(os.getenv("MIN_ODDS","1.30"))
    min_edge = float(os.getenv("MIN_EDGE","0.025"))
    kelly = float(os.getenv("KELLY_FRACTION","0.25"))
    max_bets = int(os.getenv("MAX_BETS","3"))
    bankroll = float(os.getenv("BANKROLL_START","100"))

    tz = pytz.timezone(tzname)

    # 1) Pull odds from The Odds API
    df = fetch_today_odds_http()
    if df.empty:
        text = "<b>📣 Sélections du jour</b>\nAucune rencontre éligible aujourd'hui."
    else:
        df = df[df["book_odds"] >= min_odds].copy()
        sig = build_signal_table()
        if not sig.empty:
            df = adjust_probabilities(df, sig)
        picks = pick_daily_bets(df, min_edge=min_edge, max_bets=max_bets, use_adj=True)
        rows = []
        for _, r in picks.iterrows():
            prob = float(r.get("adj_prob", r.get("model_prob", 0.0)) or 0.0)
            stake_pct = fractional_kelly(prob, r["book_odds"], fraction=kelly)
            stake_amount = round(bankroll * stake_pct, 2)
            start_local = pd.to_datetime(r["start_time_iso"], utc=True).tz_convert(tz).strftime("%a %d %b %Y • %H:%M")
            rows.append(dict(
                league=r["league"], teams=r["teams"], start=start_local, market=r["market"],
                outcome=r["outcome"], book=r["book"], odds=float(r["book_odds"]),
                stake=stake_amount, mid=r["match_id"]
            ))
        text = fmt_msg(rows)

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    try:
        resp.raise_for_status()
    except Exception as e:
        print("Telegram API error:", resp.status_code, resp.text)
        raise

if __name__ == "__main__":
    main()
