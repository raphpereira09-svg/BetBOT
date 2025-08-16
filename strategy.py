# strategy.py — v4-lite (adaptive backoff to always return sensible picks)
import pandas as pd
import numpy as np
import os, datetime as dt, pytz

def implied_prob_from_decimal(odds: float) -> float:
    return 1.0/odds if odds>1.0 else 1.0

def edge(p: float, odds: float) -> float:
    return float(p) - implied_prob_from_decimal(float(odds))

def fractional_kelly(model_p: float, odds: float, fraction: float = 0.20) -> float:
    b = float(odds) - 1.0
    p = float(model_p)
    if b <= 0 or p <= 0.0 or p >= 1.0:
        return 0.0
    k = ((b * p) - (1 - p)) / b
    return max(0.0, k * float(fraction))

def _now_tz():
    tz = pytz.timezone(os.getenv("TIMEZONE","Europe/Paris"))
    return dt.datetime.now(tz)

def _min_edge_required_soft(odds: float) -> float:
    o = float(odds)
    if o < 1.45: return 0.015
    if o < 1.60: return 0.015
    if o < 2.00: return 0.015
    return 0.010

def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty: return df
    now = _now_tz()
    min_start_min = int(os.getenv("MIN_START_MINUTES", 15))
    max_start_h   = int(os.getenv("MAX_START_HOURS", 72))
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(now.tzinfo)
    df = df[(df["start_dt"] >= now + pd.Timedelta(minutes=min_start_min)) &
            (df["start_dt"] <= now + pd.Timedelta(hours=max_start_h))]
    df = df[~df["outcome"].astype(str).str.lower().isin(["draw","x","nul","match nul"])]
    for c in ["blend_prob","adj_prob","consensus_prob","model_prob"]:
        if c in df.columns:
            prob_col = c; break
    else:
        prob_col = "model_prob"
    df["prob_use"] = df[prob_col].astype(float).clip(1e-6, 1-1e-6)
    df["edge_use"] = df.apply(lambda r: edge(r["prob_use"], r["book_odds"]), axis=1)
    df["ev"] = df["prob_use"] * df["book_odds"].astype(float) - 1.0
    return df

def _filter_stage(df: pd.DataFrame, min_edge: float, min_books:int, bvm: tuple[float,float], caps: tuple[float,float]) -> pd.DataFrame:
    if df.empty: return df
    df2 = df.copy()
    df2 = df2[df2["book_odds"] >= float(os.getenv("MIN_ODDS", 1.30))]
    if "n_books" in df2.columns:
        df2 = df2[df2["n_books"] >= min_books]
    if "best_vs_median" in df2.columns:
        is_tennis = df2["sport"].astype(str).str.lower().eq("tennis")
        bvm_tennis, bvm_other = bvm
        mask_tennis = is_tennis & (df2["best_vs_median"].fillna(1.0) >= bvm_tennis)
        mask_other  = (~is_tennis) & (df2["best_vs_median"].fillna(1.0) >= bvm_other)
        df2 = df2[mask_tennis | mask_other]
    max_odds, min_prob = caps
    df2 = df2[(df2["book_odds"] <= max_odds) & (df2["prob_use"] >= min_prob)]
    df2["edge_bar"] = df2["book_odds"].apply(_min_edge_required_soft)
    df2 = df2[(df2["edge_use"] >= df2["edge_bar"]) & (df2["edge_use"] >= min_edge)]
    return df2

def pick_daily_bets(df: pd.DataFrame, min_edge: float, max_bets: int = 3, use_adj: bool = True):
    df = _prepare(df)
    if df.empty: return df

    stageA = _filter_stage(df, min_edge=min_edge, min_books=int(os.getenv("MIN_BOOKS","2")),
                           bvm=(float(os.getenv("BVM_TENNIS","1.00")), float(os.getenv("BVM_OTHER","0.995"))),
                           caps=(float(os.getenv("MAX_ODDS_GLOBAL","2.60")), float(os.getenv("MIN_PROB_GLOBAL","0.50"))))
    if len(stageA) >= max_bets:
        return stageA.sort_values(["ev","edge_use","book_odds"], ascending=False).head(max_bets)

    stageB = _filter_stage(df, min_edge=max(0.012, min_edge*0.8), min_books=1,
                           bvm=(0.995, 0.990), caps=(2.80, 0.48))
    if len(stageA) + len(stageB) >= max_bets:
        out = pd.concat([stageA, stageB]).drop_duplicates().sort_values(["ev","edge_use","book_odds"], ascending=False)
        return out.head(max_bets)

    fallback = df.copy()
    fallback = fallback[(fallback["book_odds"] >= 1.30) & (fallback["book_odds"] <= 3.00)]
    if "n_books" in fallback.columns:
        fallback = fallback[fallback["n_books"] >= 1]
    if "best_vs_median" in fallback.columns:
        fallback = fallback[fallback["best_vs_median"].fillna(1.0) >= 0.99]
    fallback = fallback[fallback["ev"] >= 0.0]
    if fallback.empty:
        return stageA.sort_values(["ev","edge_use","book_odds"], ascending=False).head(max_bets)
    return fallback.sort_values(["ev","edge_use","book_odds"], ascending=False).head(max_bets)
