import os, json, asyncio, pytz, datetime as dt, pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

from strategy import fractional_kelly, pick_daily_bets
from signals import build_signal_table, adjust_probabilities
from odds_providers import fetch_today_odds_http

DATA_DIR = os.environ.get("DATA_DIR", "data")
STATE_PATH = os.environ.get("STATE_PATH", "state.json")

# ---------- State & IO ----------
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"bankroll": float(os.getenv("BANKROLL_START", 100.0)), "history": []}

def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)

def _journal_path():
    return os.path.join(DATA_DIR, "journal.csv")

def append_to_journal(rows: list[dict]):
    import pandas as _pd, os as _os
    jp = _journal_path()
    _os.makedirs(_os.path.dirname(jp), exist_ok=True)
    df = _pd.DataFrame(rows)
    if _os.path.exists(jp) and _os.path.getsize(jp) > 0:
        df_existing = _pd.read_csv(jp)
        df_all = _pd.concat([df_existing, df], ignore_index=True)
    else:
        df_all = df
    df_all.to_csv(jp, index=False)

def settle_in_journal(match_id: str, selection: str, result: str, price: float):
    """
    result in {'win','loss','push'}
    price: decimal odds used for the selection (book_odds)
    Updates the most recent unsettled row matching (match_id, outcome)
    """
    import pandas as _pd, os as _os
    jp = _journal_path()
    if not os.path.exists(jp):
        return False, "journal not found"
    df = _pd.read_csv(jp)
    mask = (df["match_id"]==match_id) & (df["outcome"]==selection) & (df["status"]=="open")
    idx = df[mask].index
    if len(idx)==0:
        return False, "no open bet for that match_id/selection"
    i = idx[-1]
    stake = float(df.at[i, "stake"] or 0.0)
    if result=="win":
        pnl = stake * (price - 1.0)
    elif result=="loss":
        pnl = -stake
    else:
        pnl = 0.0
    df.at[i, "result"] = result
    df.at[i, "pnl"] = round(pnl, 2)
    df.at[i, "status"] = "settled"
    state = load_state()
    bk_before = float(state.get("bankroll", 0.0))
    bk_after = round(bk_before + pnl, 2)
    state["bankroll"] = bk_after
    save_state(state)
    df.at[i, "bankroll_before"] = round(bk_before, 2)
    df.at[i, "bankroll_after"] = bk_after
    df.to_csv(jp, index=False)
    return True, f"Settled: {result}, pnl={pnl:.2f}, bankroll={bk_after:.2f}"

# ---------- Data loading ----------
def load_today_dataframe(tz) -> pd.DataFrame:
    """Reads CSV files in DATA_DIR.
    Required columns:
      match_id, sport, league, teams, start_time_iso, market, outcome, model_prob, book, book_odds, note
    """
    ensure_dirs()
    files = [os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.endswith(".csv") and f != "journal.csv"]
    frames = []
    for fp in files:
        try:
            df = pd.read_csv(fp)
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["match_id","sport","league","teams","start_time_iso","market","outcome","model_prob","book","book_odds","note"])
    df = pd.concat(frames, ignore_index=True)
    now = dt.datetime.now(tz)
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(tz)
    return df[df["start_dt"] > now]

def load_candidates(tz, use_provider: bool = False) -> pd.DataFrame:
    if use_provider:
        df_odds = fetch_today_odds_http()
        # If local model files exist, prefer their model_prob
        df_model = load_today_dataframe(tz)
        if not df_model.empty and "model_prob" in df_model.columns:
            key_cols = ["match_id","outcome"]
            merged = pd.merge(df_odds, df_model[key_cols+["model_prob"]], on=key_cols, how="left")
            merged["model_prob"] = merged["model_prob_y"].fillna(merged["model_prob_x"])
            keep = [c for c in df_odds.columns if c in merged.columns]
            keep = list(dict.fromkeys(keep + ["model_prob"]))
            return merged[keep]
        return df_odds
    else:
        return load_today_dataframe(tz)

# ---------- Formatting ----------
def format_alert_row(r, stake_amount: float):
    # HTML card formatting (simple & sober)
    import pandas as _pd
    try:
        kickoff = _pd.to_datetime(r["start_time_iso"], utc=True).tz_convert(os.getenv("TIMEZONE","Europe/Paris")).strftime("%a %d %b %Y • %H:%M")
    except Exception:
        kickoff = str(r.get("start_time_iso",""))
    league = r.get("league","")
    teams = r.get("teams","")
    market = r.get("market","")
    outcome = r.get("outcome","")
    book = r.get("book","")
    odds = float(r.get("book_odds", 0.0) or 0.0)

    prob = r.get("model_prob", None)
    adj = r.get("adj_prob", None)
    edge_val = r.get("edge", None)
    ev_val = r.get("ev", None)

    def pct(x):
        try:
            return f"{float(x)*100:.1f}%"
        except Exception:
            return ""

    prob_line = ""
    if prob is not None and prob == prob:
        if adj is not None and adj == adj and abs(float(adj) - float(prob)) > 1e-6:
            prob_line = f"<b>Prob.</b> {pct(prob)} → <i>{pct(adj)}</i>"
        else:
            prob_line = f"<b>Prob.</b> {pct(prob)}"

    edge_line = " • ".join(list(filter(None, [
        f"<b>Edge</b> {pct(edge_val)}" if edge_val==edge_val else "",
        f"<b>EV</b> {pct(ev_val)}" if ev_val==ev_val else ""
    ])))

    note = r.get("note","")
    note_line = f"\n<i>{note}</i>" if isinstance(note, str) and note.strip() else ""

    body = (
        f"🏟️ <b>{league}</b>\n"
        f"{teams}\n"
        f"🕒 {kickoff}\n"
        f"— — — — —\n"
        f"🎯 <b>{market}</b> • <b>{outcome}</b>\n"
        f"💼 <b>Book</b> {book}\n"
        f"🎲 <b>Cote</b> {odds:.2f}\n"
        f"{prob_line}\n"
        f"{edge_line}\n"
        f"💸 <b>Mise conseillée</b> {stake_amount:.2f}€\n"
        f"<code>ID: {r.get('match_id','')}</code>"
        f"{note_line}"
    )
    return body

# ---------- Bot Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salut ! Je t’enverrai chaque jour des value bets. Commandes: /today /bankroll /setbankroll 100 /setedge 0.03 /setkelly 0.25 /setmaxbets 3 /settle ...")

async def bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    await update.message.reply_text(f"Bankroll actuelle enregistrée: {state.get('bankroll', 0):.2f}")

async def setbankroll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0])
        state = load_state()
        state["bankroll"] = val
        save_state(state)
        await update.message.reply_text(f"OK, bankroll = {val:.2f}")
    except Exception:
        await update.message.reply_text("Usage: /setbankroll 123.45")

async def setedge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0])
        os.environ["MIN_EDGE"] = str(val)
        await update.message.reply_text(f"Seuil de value (edge) = {val:.3f}")
    except Exception:
        await update.message.reply_text("Usage: /setedge 0.03")

async def setkelly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(context.args[0])
        os.environ["KELLY_FRACTION"] = str(val)
        await update.message.reply_text(f"Kelly fractionnel = {val:.2f}")
    except Exception:
        await update.message.reply_text("Usage: /setkelly 0.25")

async def setmaxbets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(context.args[0])
        if val < 1 or val > 10:
            await update.message.reply_text("Choisis un nombre entre 1 et 10.")
            return
        os.environ["MAX_BETS"] = str(val)
        await update.message.reply_text(f"Nombre max de sélections/jour = {val}")
    except Exception:
        await update.message.reply_text("Usage: /setmaxbets 3")

async def settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /settle <match_id> <selection> <win|loss|push> [price]"""
    try:
        args = context.args
        match_id = args[0]
        selection = args[1]
        result = args[2].lower()
        price = float(args[3]) if len(args) > 3 else None
        if result not in ("win","loss","push"):
            await update.message.reply_text("Résultat invalide. Utilise win|loss|push.")
            return
        if price is None:
            import pandas as _pd
            jp = _journal_path()
            if os.path.exists(jp):
                df = _pd.read_csv(jp)
                mask = (df["match_id"]==match_id) & (df["outcome"]==selection) & (df["status"]=="open")
                if mask.any():
                    price = float(df[mask].iloc[-1]["book_odds"])
        if price is None:
            await update.message.reply_text("Impossible de déterminer la cote. Fournis-la: /settle <id> <selection> <win|loss|push> <cote>")
            return
        ok, msg = settle_in_journal(match_id, selection, result, price)
        await update.message.reply_text(msg if ok else f"Erreur: {msg}")
    except Exception as e:
        await update.message.reply_text(f"Usage: /settle <match_id> <selection> <win|loss|push> [cote]  ({e})")

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_daily_alert(context)

# ---------- Core Alert ----------
async def send_daily_alert(context: ContextTypes.DEFAULT_TYPE):
    tzname = os.getenv("TIMEZONE","Europe/Paris")
    tz = pytz.timezone(tzname)
    chat_id = int(os.environ["TELEGRAM_CHAT_ID"])
    min_edge = float(os.getenv("MIN_EDGE", 0.025))
    kelly_fraction = float(os.getenv("KELLY_FRACTION", 0.25))
    max_bets = int(os.getenv("MAX_BETS", 3))

    use_provider = os.getenv("ENABLE_ODDS_API","1") == "1"
    df_all = load_candidates(tz, use_provider=use_provider)
    if df_all.empty:
        await context.bot.send_message(chat_id, "Aucune rencontre éligible (pas de données/odds ou matchs déjà commencés).")
        return

    min_odds = float(os.getenv("MIN_ODDS", 1.30))
    df_all = df_all[df_all["book_odds"] >= min_odds]

    signals = build_signal_table()
    if not signals.empty:
        df_all = adjust_probabilities(df_all, signals)

    picks = pick_daily_bets(df_all, min_edge=min_edge, max_bets=max_bets, use_adj=True)
    if picks.empty:
        await context.bot.send_message(chat_id, f"Pas de value bet ≥ {min_edge:.1%} aujourd'hui.")
        return

    state = load_state()
    bankroll = float(state.get("bankroll", 100.0))

    msgs = ["<b>📣 Sélections du jour</b>"]
    journal_rows = []
    for _, r in picks.iterrows():
        stake_pct = fractional_kelly(r.get("adj_prob", r["model_prob"]), r["book_odds"], fraction=kelly_fraction)
        stake_amount = round(bankroll * stake_pct, 2)
        msgs.append(format_alert_row(r, stake_amount))
        journal_rows.append({
            "timestamp_iso": dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat(),
            "match_id": r["match_id"],
            "sport": r["sport"],
            "league": r["league"],
            "teams": r["teams"],
            "start_time_iso": r["start_time_iso"],
            "market": r["market"],
            "outcome": r["outcome"],
            "book": r["book"],
            "book_odds": float(r["book_odds"]),
            "model_prob": float(r.get("model_prob", float("nan"))),
            "adj_prob": float(r.get("adj_prob", float("nan"))),
            "edge": float(r.get("edge", float("nan"))),
            "ev": float(r.get("ev", float("nan"))),
            "stake": float(stake_amount),
            "status": "open",
            "result": "",
            "pnl": "",
            "bankroll_before": float(bankroll),
            "bankroll_after": "",
            "note": str(r.get("note",""))
        })

    await context.bot.send_message(chat_id, "\n\n".join(msgs), parse_mode=ParseMode.HTML)
    if journal_rows:
        append_to_journal(journal_rows)

# ---------- Build & Run ----------
def build_application():
    if os.environ.get("LOAD_DOTENV","1") == "1":
        load_dotenv()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).parse_mode(ParseMode.HTML).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("bankroll", bankroll))
    app.add_handler(CommandHandler("setbankroll", setbankroll))
    app.add_handler(CommandHandler("setedge", setedge))
    app.add_handler(CommandHandler("setkelly", setkelly))
    app.add_handler(CommandHandler("setmaxbets", setmaxbets))
    app.add_handler(CommandHandler("settle", settle))

    tzname = os.getenv("TIMEZONE","Europe/Paris")
    tz = pytz.timezone(tzname)
    hour = int(os.getenv("ALERT_HOUR", 10))
    app.job_queue.run_daily(send_daily_alert, time=dt.time(hour=hour, minute=0, tzinfo=tz))
    return app

def main():
    app = build_application()
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
