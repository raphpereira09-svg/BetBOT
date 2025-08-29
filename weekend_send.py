import os, pandas as pd, pytz, requests
from odds_providers import fetch_soccer_odds
from foot_selector import weekend_report
def send_long_message(chat_id: str, text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]; url = f"https://api.telegram.org/bot{token}/sendMessage"
    CHUNK = 3500
    for i in range(0, len(text), CHUNK):
        part = text[i:i+CHUNK]
        r = requests.post(url, data={"chat_id": chat_id, "text": part, "parse_mode":"HTML"}, timeout=30)
        r.raise_for_status()
def main():
    tzname = os.getenv("TIMEZONE","Europe/Paris"); tz = pytz.timezone(tzname)
    min_ev = float(os.getenv("WEEKEND_MIN_EV","0.01")); chat_id = os.environ["TELEGRAM_CHAT_ID"]
    df = fetch_soccer_odds()
    if df.empty: send_long_message(chat_id, "<b>📣 Foot — Rapport week-end</b>\nAucune rencontre disponible."); return
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(tz)
    df = df[(df["start_dt"].dt.weekday >= 4) & (df["start_dt"].dt.weekday <= 6)]
    if df.empty: send_long_message(chat_id, "<b>📣 Foot — Rapport week-end</b>\nAucun match entre vendredi et dimanche."); return
    header = f"<b>📣 Foot — Rapport week-end (Top-5)</b>\nSeuil value: EV ≥ {min_ev:.0%}."
    rep = weekend_report(df, min_ev=min_ev)
    bodies = []; order = ["soccer_france_ligue_1","soccer_epl","soccer_spain_la_liga","soccer_italy_serie_a","soccer_germany_bundesliga"]
    for lg in order + [k for k in rep.keys() if k not in order]:
        lines = rep.get(lg, []); 
        if not lines: continue
        bodies.append("\n\n<b>"+lg+"</b>\n" + "\n".join(lines))
    send_long_message(chat_id, header + "".join(bodies))
if __name__ == "__main__": main()
