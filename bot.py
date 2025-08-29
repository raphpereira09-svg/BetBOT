
# bot.py — Telegram polling bot (v5-foot) using Poisson/Dixon–Coles model for football
# Commands:
#   /start, /help, /picks, /today, /set_ev <val>, /set_max <n>, /status
# Optional daily push via RUN_DAILY_HHMM (e.g., 10:00) + TELEGRAM_CHAT_ID
import os, time, requests, pandas as pd, pytz
from odds_providers import fetch_soccer_odds
from foot_selector import select_picks

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN manquant.')
API = f'https://api.telegram.org/bot{TOKEN}'

TIMEZONE = os.getenv('TIMEZONE', 'Europe/Paris')
tz = pytz.timezone(TIMEZONE)

MIN_EV = float(os.getenv('MIN_EV', '0.02'))
MAX_PICKS = int(os.getenv('MAX_PICKS', '3'))
RUN_DAILY_HHMM = os.getenv('RUN_DAILY_HHMM', '').strip()
AUTHORIZED = set([s.strip() for s in os.getenv('TELEGRAM_CHAT_ID','').split(',') if s.strip()])

_last_daily_date = None

def fmt_pick(p):
    return (
        f'🏟️ <b>{p[' + '"league"' + ']}</b>\n{p[' + '"teams"' + ']}\n'
        f'🧮 Score attendu: <b>{p[' + '"mean_score"' + ']}</b>\n'
        f'📊 Top scores: {p[' + '"top_scores"' + ']}\n'
        f'— — — — —\n'
        f'✅ <b>{p[' + '"pick_type"' + ']}</b>: <b>{p[' + '"selection"' + ']}</b>\n'
        f'🎲 Cote: <b>{p[' + '"price"' + ']:.2f}</b> • P: <b>{p[' + '"prob"' + ']*100:.1f}%</b>\n'
        f'📈 EV: <b>{p[' + '"ev"' + ']*100:.2f}%</b> • Book: {p[' + '"book"' + ']}'
    )

def send_message(chat_id, text):
    try:
        r = requests.post(f'{API}/sendMessage', data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}, timeout=25)
        if r.status_code >= 400:
            try: detail = r.json()
            except Exception: detail = {'raw': r.text}
            raise RuntimeError(f'Telegram error {r.status_code}: {detail}')
    except Exception as e:
        print(f'[ERR] send_message: {e}')

def can_use(chat_id: int) -> bool:
    if not AUTHORIZED: return True
    return str(chat_id) in AUTHORIZED

def help_text():
    return ('<b>🤖 Bot Foot v5 — commandes</b>\n'
            '/picks — calculer les sélections du jour\n'
            '/today — alias de /picks\n'
            '/set_ev &lt;valeur&gt; — ex: /set_ev 0.03\n'
            '/set_max &lt;n&gt; — ex: /set_max 3\n'
            '/status — afficher paramètres\n'
            '/help — aide\n\n'
            'Astuce: RUN_DAILY_HHMM (ex: 10:00) + TELEGRAM_CHAT_ID pour push auto.')

def do_picks(chat_id):
    try:
        df = fetch_soccer_odds()
    except Exception as e:
        send_message(chat_id, f'⚠️ The Odds API error: <code>{e}</code>')
        return
    if df.empty:
        send_message(chat_id, '<b>📣 Foot — Sélections</b>\nAucun match trouvé (The Odds API vide).')
        return
    picks, diags = select_picks(df, min_ev=MIN_EV, max_picks=MAX_PICKS)
    if picks:
        parts = ['<b>📣 Foot — Sélections</b>']
        for p in picks:
            p['start_local'] = pd.to_datetime(p['start_time_iso'], utc=True).tz_convert(tz).strftime('%a %d %b • %H:%M')
            parts.append(fmt_pick(p) + f'\n🕒 {p[' + '"start_local"' + ']}')
        send_message(chat_id, '\n\n'.join(parts))
    else:
        head = '<b>📣 Foot — Sélections</b>\nAucun pick ≥ seuil EV.\n\n<b>🔎 Diagnostics (quelques matches)</b>'
        rows = []
        for d in diags[:5]:
            pl = []
            if pd.notna(d.get('p_over25', float('nan'))): pl.append(f"Over2.5 {d['p_over25']*100:.1f}%")
            pl.append(f"H/D/A {d['p_home']*100:.0f}/{d['p_draw']*100:.0f}/{d['p_away']*100:.0f}%")
            rows.append(f"• <b>{d['league']}</b> — {d['teams']}\n  Score exp: {d['mean_score']} | {', '.join(pl)}\n  Top: {d['top_scores']}")
        send_message(chat_id, head + '\n' + '\n'.join(rows))

def handle_command(chat_id, text):
    global MIN_EV, MAX_PICKS
    t = (text or '').strip()
    low = t.lower()
    if low.startswith('/start'):
        send_message(chat_id, '👋 Bienvenue !\n' + help_text())
    elif low.startswith('/help'):
        send_message(chat_id, help_text())
    elif low.startswith('/status'):
        send_message(chat_id, f'⚙️ Params — MIN_EV={MIN_EV:.3f}, MAX_PICKS={MAX_PICKS}, TZ={TIMEZONE}, RUN_DAILY_HHMM=\'{RUN_DAILY_HHMM}\'')
    elif low.startswith('/picks') or low.startswith('/today'):
        do_picks(chat_id)
    elif low.startswith('/set_ev'):
        parts = t.split()
        if len(parts)>=2:
            try:
                MIN_EV = float(parts[1])
                send_message(chat_id, f'✅ MIN_EV réglé à {MIN_EV:.3f}')
            except Exception:
                send_message(chat_id, '⚠️ Usage: /set_ev 0.02')
        else:
            send_message(chat_id, '⚠️ Usage: /set_ev 0.02')
    elif low.startswith('/set_max'):
        parts = t.split()
        if len(parts)>=2 and parts[1].isdigit():
            MAX_PICKS = int(parts[1])
            send_message(chat_id, f'✅ MAX_PICKS réglé à {MAX_PICKS}')
        else:
            send_message(chat_id, '⚠️ Usage: /set_max 3')
    else:
        send_message(chat_id, 'Commande inconnue.\n' + help_text())

def scheduled_push_if_due():
    global _last_daily_date
    if not RUN_DAILY_HHMM: return
    target_chat = os.getenv('TELEGRAM_CHAT_ID')
    if not target_chat: return
    now = pd.Timestamp.now(tz)
    try:
        hh, mm = [int(x) for x in RUN_DAILY_HHMM.split(':')]
    except Exception:
        return
    if now.hour==hh and now.minute==mm:
        if _last_daily_date == now.date(): return
        _last_daily_date = now.date()
        try:
            do_picks(target_chat)
        except Exception as e:
            send_message(target_chat, f'⚠️ Scheduled run error: <code>{e}</code>')

def main():
    print('Bot Foot v5 démarré. Polling Telegram...')
    offset = None
    while True:
        try: scheduled_push_if_due()
        except Exception as e: print('[WARN] scheduled_push_if_due:', e)
        params = {'timeout': 50}
        if offset is not None: params['offset'] = offset
        try:
            r = requests.get(f'{API}/getUpdates', params=params, timeout=60)
            data = r.json()
        except Exception as e:
            print('[WARN] getUpdates error:', e); time.sleep(2); continue
        for upd in data.get('result', []):
            offset = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('channel_post') or {}
            chat = msg.get('chat') or {}
            chat_id = chat.get('id'); text = msg.get('text','')
            if not chat_id or not text: continue
            if not can_use(chat_id):
                send_message(chat_id, '⛔️ Accès restreint. Ajoute ton chat_id dans TELEGRAM_CHAT_ID.'); continue
            handle_command(chat_id, text)
        time.sleep(1)

if __name__ == '__main__':
    main()
