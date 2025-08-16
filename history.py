import os, pandas as pd
DATA_DIR = os.environ.get("DATA_DIR","data")
HIST = os.path.join(DATA_DIR, "odds_history.csv")
def save_odds_snapshot(df: pd.DataFrame):
    if df.empty or not set(["match_id","outcome","median_odds","n_books"]).issubset(df.columns): return
    snap = df[["match_id","outcome","median_odds","n_books"]].dropna().copy()
    if snap.empty: return
    snap["ts_utc"] = pd.Timestamp.utcnow().isoformat()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(HIST) and os.path.getsize(HIST)>0:
        old = pd.read_csv(HIST); allx = pd.concat([old, snap], ignore_index=True)
    else:
        allx = snap
    allx.to_csv(HIST, index=False)
