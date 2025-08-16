# strategy.py — v3 with blending, drift filter, sport-aware
import pandas as pd
import numpy as np
import os, datetime as dt, pytz
from history import load_recent_medians

TOP_TENNIS = {"novak djokovic","jannik sinner","carlos alcaraz","daniil medvedev","alexander zverev"}
TOP_FOOT = {"manchester city","liverpool","arsenal","real madrid","barcelona","fc barcelona","bayern munich","psg","paris saint-germain"}

def _norm(s: str) -> str:
    return (s or "").strip().lower()

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
    if o < 1.45: return 0.040
    if o < 1.60: return 0.030
    if o < 2.00: return 0.025
    return 0.020

def _now_paris():
    tz = pytz.timezone(os.getenv("TIMEZONE","Europe/Paris"))
    return dt.datetime.now(tz)

def _split_teams(teams: str):
    if " vs " in teams: a, b = teams.split(" vs ", 1)
    elif " - " in teams: a, b = teams.split(" - ", 1)
    else:
        parts = teams.split(); mid = len(parts)//2; a, b = " ".join(parts[:mid]), " ".join(parts[mid:])
    return a.strip(), b.strip()

def _opponent_name(row, selected_outcome):
    a, b = _split_teams(str(row["teams"]))
    out = _norm(selected_outcome)
    if out in (_norm(a), "home", "1", f"{_norm(a)} win"): return b
    if out in (_norm(b), "away", "2", f"{_norm(b)} win"): return a
    if _norm(a) in out and _norm(b) not in out: return b
    if _norm(b) in out and _norm(a) not in out: return a
    return b

def pick_daily_bets(df: pd.DataFrame, min_edge: float, max_bets: int = 3, use_adj: bool = True):
    df = df.copy()
    if df.empty: return df

    now = _now_paris()
    min_start_min = int(os.getenv("MIN_START_MINUTES", 60))
    max_start_h   = int(os.getenv("MAX_START_HOURS", 36))
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(now.tzinfo)
    df = df[(df["start_dt"] >= now + pd.Timedelta(minutes=min_start_min)) & (df["start_dt"] <= now + pd.Timedelta(hours=max_start_h))]

    # drop draws
    df = df[~df["outcome"].astype(str).str.lower().isin(["draw","x","nul","match nul"])]

    # choose probability column (blended preferred)
    prob_col = "blend_prob" if "blend_prob" in df.columns else ("adj_prob" if (use_adj and "adj_prob" in df.columns) else "model_prob")
    df["edge_adj"] = df.apply(lambda r: edge(float(r[prob_col]), float(r["book_odds"])), axis=1)
    df["edge_consensus"] = df.apply(lambda r: edge(float(r.get("consensus_prob", r.get("model_prob", r[prob_col]))), float(r["book_odds"])), axis=1)

    # market guardrails
    min_books = int(os.getenv("MIN_BOOKS", 3))
    df = df[df["book_odds"] >= float(os.getenv("MIN_ODDS", 1.30))]
    if "n_books" in df.columns:
        df = df[df["n_books"] >= min_books]
    if "best_vs_median" in df.columns:
        is_tennis = df["sport"].astype(str).str.lower().eq("tennis")
        mask_tennis = is_tennis & (df["best_vs_median"].fillna(1.0) >= 1.02)
        mask_other  = (~is_tennis) & (df["best_vs_median"].fillna(1.0) >= 1.01)
        df = df[mask_tennis | mask_other]

    # drift vs 24h median (optional if history available)
    try:
        eps_24h = float(os.getenv("EPS_24H", 0.01))
        hist = load_recent_medians(hours=36)
        if not hist.empty:
            df = df.merge(hist, on=["match_id","outcome"], how="left")
            df = df[(df["median24"].isna()) | (df["book_odds"] >= (df["median24"] * (1.0 + eps_24h)))]
    except Exception:
        pass

    # edge thresholds
    df["edge_bar"] = df["book_odds"].apply(_min_edge_required)
    df = df[(df["edge_adj"] >= df["edge_bar"]) & (df["edge_adj"] >= float(min_edge))]

    # require adjustment adds value
    min_delta = float(os.getenv("MIN_DELTA_EDGE", 0.005))
    df = df[(df["edge_adj"] - df["edge_consensus"]) >= min_delta]

    # sport-aware caps
    TENNIS_MAX_ODDS = float(os.getenv("TENNIS_MAX_ODDS", 2.20))
    TENNIS_MIN_PROB = float(os.getenv("TENNIS_MIN_PROB", 0.50))
    FOOT_MAX_ODDS   = float(os.getenv("FOOT_MAX_ODDS", 2.40))
    FOOT_MIN_PROB   = float(os.getenv("FOOT_MIN_PROB", 0.45))
    BASKET_MAX_ODDS = float(os.getenv("BASKET_MAX_ODDS", 2.20))
    BASKET_MIN_PROB = float(os.getenv("BASKET_MIN_PROB", 0.52))

    def ok_row(r):
        sport = _norm(r.get("sport",""))
        odds  = float(r["book_odds"])
        p     = float(r[prob_col])
        cons  = float(r.get("consensus_prob", p))
        is_underdog = cons <= 0.40
        if sport == "tennis":
            if odds > TENNIS_MAX_ODDS or p < TENNIS_MIN_PROB: return False
            opp = _norm(_opponent_name(r, r["outcome"]))
            if is_underdog and opp in TOP_TENNIS: return False
        elif sport == "football":
            if odds > FOOT_MAX_ODDS or p < FOOT_MIN_PROB: return False
            opp = _norm(_opponent_name(r, r["outcome"]))
            if is_underdog and opp in TOP_FOOT: return False
        elif sport == "basketball":
            if odds > BASKET_MAX_ODDS or p < BASKET_MIN_PROB: return False
        return True

    df = df[df.apply(ok_row, axis=1)]

    # final ranking
    df["ev"] = df[prob_col] * df["book_odds"] - 1.0
    df = df.sort_values(["ev","edge_adj","book_odds"], ascending=False)
    return df.head(max_bets)
