# cron_send_foot.py — Football-only sender with score prediction
import os, pandas as pd, pytz, requests
from odds_providers import fetch_soccer_odds
from foot_selector import select_picks

def send_telegram(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    resp.raise_for_status()

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

    df = fetch_soccer_odds()
    if df.empty:
        send_telegram("<b>📣 Foot — Sélections</b>\nAucun match trouvé (The Odds API vide).")
        return

    picks, diags = select_picks(df, min_ev=min_ev, max_picks=max_picks)

    if picks:
        parts = ["<b>📣 Foot — Sélections</b>"]
        for p in picks:
            p["start_local"] = pd.to_datetime(p["start_time_iso"], utc=True).tz_convert(tz).strftime("%a %d %b • %H:%M")
            parts.append(fmt_pick(p) + f"\n🕒 {p['start_local']}")
        send_telegram("\n\n".join(parts))
    else:
        head = "<b>📣 Foot — Sélections</b>\nAucun pick ≥ seuil EV.\n\n<b>🔎 Diagnostics (quelques matches)</b>"
        rows = []
        for d in diags[:5]:
            pl = []
            if pd.notna(d.get("p_over25", float('nan'))):
                pl.append(f"Over2.5 {d['p_over25']*100:.1f}%")
            pl.append(f"H/D/A {d['p_home']*100:.0f}/{d['p_draw']*100:.0f}/{d['p_away']*100:.0f}%")
            rows.append(f"• <b>{d['league']}</b> — {d['teams']}\n  Score exp: {d['mean_score']} | {', '.join(pl)}\n  Top: {d['top_scores']}")
        send_telegram(head + "\n" + "\n".join(rows))

if __name__ == "__main__":
    main()
