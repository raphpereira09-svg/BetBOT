import os, pandas as pd

DATA_DIR = os.environ.get("DATA_DIR","data")
HIST = os.path.join(DATA_DIR, "odds_history.csv")

def save_odds_snapshot(df: pd.DataFrame):
    if df.empty: return
    cols = ["match_id","outcome","median_odds","n_books"]
    if not set(cols).issubset(df.columns): return
    snap = df[cols].dropna().copy()
    if snap.empty: return
    snap["ts_utc"] = pd.Timestamp.utcnow().isoformat()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(HIST) and os.path.getsize(HIST)>0:
        old = pd.read_csv(HIST)
        allx = pd.concat([old, snap], ignore_index=True)
    else:
        allx = snap
    allx.to_csv(HIST, index=False)

def load_recent_medians(hours: int = 36) -> pd.DataFrame:
    if not os.path.exists(HIST) or os.path.getsize(HIST)==0:
        return pd.DataFrame(columns=["match_id","outcome","median24"])
    df = pd.read_csv(HIST)
    if df.empty or "ts_utc" not in df.columns:
        return pd.DataFrame(columns=["match_id","outcome","median24"])
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
    cutoff = pd.Timestamp.utcnow().tz_localize("UTC") - pd.Timedelta(hours=hours)
    df = df[df["ts_utc"] >= cutoff]
    if df.empty: 
        return pd.DataFrame(columns=["match_id","outcome","median24"])
    g = df.groupby(["match_id","outcome"])["median_odds"].median().reset_index().rename(columns={"median_odds":"median24"})
    return g
