import pandas as pd
import numpy as np
import os, datetime as dt, pytz

def implied_prob_from_decimal(odds: float) -> float:
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds

def edge(p: float, odds: float) -> float:
    return float(p) - implied_prob_from_decimal(float(odds))

def fractional_kelly(model_p: float, odds: float, fraction: float = 0.25) -> float:
    b = float(odds) - 1.0
    p = float(model_p)
    if b <= 0 or p <= 0.0 or p >= 1.0:
        return 0.0
    k = ((b * p) - (1 - p)) / b
    return max(0.0, k * float(fraction))

def _min_edge_required(odds: float) -> float:
    o = float(odds)
    if o < 1.45: return 0.040  # 4.0%
    if o < 1.60: return 0.030
    if o < 2.00: return 0.025
    return 0.020

def _now_paris():
    tz = pytz.timezone(os.getenv("TIMEZONE","Europe/Paris"))
    return dt.datetime.now(tz)

def pick_daily_bets(df: pd.DataFrame, min_edge: float, max_bets: int = 3, use_adj: bool = True):
    df = df.copy()
    if df.empty:
        return df

    # Fenêtre temporelle (par défaut: entre +60 min et +36 h)
    now = _now_paris()
    min_start_min = int(os.getenv("MIN_START_MINUTES", 60))
    max_start_h   = int(os.getenv("MAX_START_HOURS", 36))
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(now.tzinfo)
    df = df[(df["start_dt"] >= now + pd.Timedelta(minutes=min_start_min)) &
            (df["start_dt"] <= now + pd.Timedelta(hours=max_start_h))]

    # Pas de match nul (1X2) par défaut
    df = df[~df["outcome"].astype(str).str.lower().isin(["draw","x","nul","match nul"])]

    prob_col = "adj_prob" if (use_adj and "adj_prob" in df.columns) else "model_prob"
    df["edge_adj"] = df.apply(lambda r: edge(r[prob_col], r["book_odds"]), axis=1)
    df["edge_consensus"] = df.apply(lambda r: edge(r.get("consensus_prob", r["model_prob"]), r["book_odds"]), axis=1)

    # Garde-fous marché
    min_books = int(os.getenv("MIN_BOOKS", 3))
    df = df[(df["book_odds"] >= float(os.getenv("MIN_ODDS", 1.30)))]
    if "n_books" in df.columns:
        df = df[df["n_books"] >= min_books]
    if "best_vs_median" in df.columns:
        df = df[df["best_vs_median"].fillna(1.0) >= 1.01]

    # Seuils d'edge (global + dynamique)
    df["edge_bar"] = df["book_odds"].apply(_min_edge_required)
    df = df[(df["edge_adj"] >= df["edge_bar"]) & (df["edge_adj"] >= float(min_edge))]

    # On retient seulement si l'ajustement (news/blessures/forme) ne dégrade pas la value
    df = df[df["edge_adj"] >= df["edge_consensus"]]

    # Tri final
    df["ev"] = df[prob_col] * df["book_odds"] - 1.0
    df = df.sort_values(["ev","edge_adj","book_odds"], ascending=False)
    return df.head(max_bets)
