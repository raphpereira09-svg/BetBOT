# bot.py — Telegram polling bot (v5-foot) for manual commands
import os, time, requests, pandas as pd, pytz
from odds_providers import fetch_soccer_odds
from foot_selector import select_picks, weekend_report
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN'); API = f'https://api.telegram.org/bot{TOKEN}'
tz = pytz.timezone(os.getenv('TIMEZONE','Europe/Paris'))
MIN_EV = float(os.getenv('MIN_EV','0.02')); MAX_PICKS = int(os.getenv('MAX_PICKS','3'))
AUTHORIZED = set([s.strip() for s in os.getenv('TELEGRAM_CHAT_ID','').split(',') if s.strip()])
def send(chat_id, text): requests.post(f'{API}/sendMessage', data={'chat_id': chat_id, 'text': text, 'parse_mode':'HTML'})
def fmt_pick(p):
    return (f"🏟️ <b>{p['league']}</b>\n{p['teams']}\n🧮 {p['mean_score']}\n📊 {p['top_scores']}\n— — — — —\n"
            f"✅ <b>{p['pick_type']}</b>: <b>{p['selection']}</b>\n🎲 <b>{p['price']:.2f}</b> • P {p['prob']*100:.1f}%\n"
            f"📈 EV {p['ev']*100:.2f}% • {p['book']}")
def do_picks(chat_id):
    df = fetch_soccer_odds(); 
    if df.empty: send(chat_id, "<b>📣 Foot — Sélections</b>\nAucun match."); return
    picks, _ = select_picks(df, min_ev=MIN_EV, max_picks=MAX_PICKS)
    if not picks: send(chat_id, "<b>📣 Foot — Sélections</b>\nAucun pick ≥ seuil EV."); return
    parts = ["<b>📣 Foot — Sélections</b>"]
    for p in picks:
        p['start_local'] = pd.to_datetime(p['start_time_iso'], utc=True).tz_convert(tz).strftime('%a %d %b • %H:%M')
        parts.append(fmt_pick(p) + f"\n🕒 {p['start_local']}")
    send(chat_id, "\n\n".join(parts))
def do_weekend(chat_id):
    df = fetch_soccer_odds()
    if df.empty: send(chat_id, "<b>📣 Foot — Rapport week-end</b>\nAucun match."); return
    df['start_dt'] = pd.to_datetime(df['start_time_iso'], utc=True).dt.tz_convert(tz)
    df = df[(df['start_dt'].dt.weekday >= 4) & (df['start_dt'].dt.weekday <= 6)]
    rep = weekend_report(df, min_ev=float(os.getenv('WEEKEND_MIN_EV','0.01')))
    order = ['soccer_france_ligue_1','soccer_epl','soccer_spain_la_liga','soccer_italy_serie_a','soccer_germany_bundesliga']
    msg = "<b>📣 Foot — Rapport week-end (Top-5)</b>"
    for lg in order + [k for k in rep.keys() if k not in order]:
        lines = rep.get(lg, []); 
        if not lines: continue
        msg += "\n\n<b>"+lg+"</b>\n" + "\n".join(lines)
    # chunk
    for i in range(0, len(msg), 3500): send(chat_id, msg[i:i+3500])
def main():
    offset=None
    while True:
        r = requests.get(f'{API}/getUpdates', params={'timeout': 50, **({'offset':offset} if offset else {})})
        data = r.json()
        for upd in data.get('result', []):
            offset = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('channel_post') or {}; chat = msg.get('chat') or {}
            chat_id = chat.get('id'); text = (msg.get('text') or '').strip().lower()
            if not chat_id or not text: continue
            if AUTHORIZED and str(chat_id) not in AUTHORIZED:
                send(chat_id, '⛔️ Accès restreint. Ajoute ce chat_id dans TELEGRAM_CHAT_ID.'); continue
            if text.startswith('/picks') or text.startswith('/today'): do_picks(chat_id)
            elif text.startswith('/weekend'): do_weekend(chat_id)
            elif text.startswith('/start') or text.startswith('/help'):
                send(chat_id, "Commandes: /picks, /weekend")
            else: send(chat_id, "Commande inconnue. Utilise /picks ou /weekend")
        time.sleep(1)
if __name__ == '__main__': main()
