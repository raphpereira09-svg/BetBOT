# strategy.py — v3-lite (moins strict, plus de picks)
import pandas as pd
import numpy as np
import os, datetime as dt, pytz

def _norm(s: str) -> str:
    return (s or "").strip().lower()

def implied_prob_from_decimal(odds: float) -> float:
    return 1.0/odds if odds>1.0 else 1.0

def edge(p: float, odds: float) -> float:
    return float(p) - implied_prob_from_decimal(float(odds))

def fractional_kelly(model_p: float, odds: float, fraction: float = 0.25) -> float:
    b = float(odds) - 1.0
    p = float(model_p)
    if b <= 0 or p <= 0.0 or p >= 1.0:
        return 0.0
    k = ((b * p) - (1 - p)) / b
    return max(0.0, k * float(fraction))

def _now_paris():
    tz = pytz.timezone(os.getenv("TIMEZONE","Europe/Paris"))
    return dt.datetime.now(tz)

# seuils dynamiques DOUX (vs v3 strict)
def _min_edge_required(odds: float) -> float:
    o = float(odds)
    if o < 1.45: return 0.025  # 2.5% au lieu de 4%
    if o < 1.60: return 0.020
    if o < 2.00: return 0.018
    return 0.015

def pick_daily_bets(df: pd.DataFrame, min_edge: float, max_bets: int = 3, use_adj: bool = True):
    df = df.copy()
    if df.empty: return df

    # Fenêtre temps plus large
    now = _now_paris()
    min_start_min = int(os.getenv("MIN_START_MINUTES", 20))  # était 60
    max_start_h   = int(os.getenv("MAX_START_HOURS", 72))    # était 36
    df["start_dt"] = pd.to_datetime(df["start_time_iso"], utc=True).dt.tz_convert(now.tzinfo)
    df = df[(df["start_dt"] >= now + pd.Timedelta(minutes=min_start_min)) &
            (df["start_dt"] <= now + pd.Timedelta(hours=max_start_h))]

    # On évite le nul par défaut
    df = df[~df["outcome"].astype(str).str.lower().isin(["draw","x","nul","match nul"])]

    # Choix de la proba: blend > adj > consensus > model
    if "blend_prob" in df.columns:
        prob_col = "blend_prob"
    elif use_adj and "adj_prob" in df.columns:
        prob_col = "adj_prob"
    elif "consensus_prob" in df.columns:
        prob_col = "consensus_prob"
    else:
        prob_col = "model_prob"

    df["edge_adj"] = df.apply(lambda r: edge(float(r[prob_col]), float(r["book_odds"])), axis=1)

    # Filtres marché plus souples
    df = df[df["book_odds"] >= float(os.getenv("MIN_ODDS", 1.30))]
    min_books = int(os.getenv("MIN_BOOKS", 2))  # était 3
    if "n_books" in df.columns:
        df = df[df["n_books"] >= min_books]

    # Qualité de prix: ne PAS être en-dessous du marché (égalité acceptée)
    bvm_tennis = float(os.getenv("BVM_TENNIS", "1.00"))
    bvm_other  = float(os.getenv("BVM_OTHER",  "0.995"))
    if "best_vs_median" in df.columns:
        is_tennis = df["sport"].astype(str).str.lower().eq("tennis")
        mask_tennis = is_tennis & (df["best_vs_median"].fillna(1.0) >= bvm_tennis)
        mask_other  = (~is_tennis) & (df["best_vs_median"].fillna(1.0) >= bvm_other)
        df = df[mask_tennis | mask_other]

    # Caps génériques (anti long-shots), pas de blacklist élites
    max_odds_global = float(os.getenv("MAX_ODDS_GLOBAL", 2.40))
    min_prob_global = float(os.getenv("MIN_PROB_GLOBAL", 0.46))
    df = df[(df["book_odds"] <= max_odds_global) & (df[prob_col] >= min_prob_global)]

    # Seuils edge: global + dynamique (plus doux)
    df["edge_bar"] = df["book_odds"].apply(_min_edge_required)
    df = df[(df["edge_adj"] >= df["edge_bar"]) & (df["edge_adj"] >= float(min_edge))]

    # Tri final: EV puis edge puis cote
    df["ev"] = df[prob_col].astype(float) * df["book_odds"].astype(float) - 1.0
    df = df.sort_values(["ev","edge_adj","book_odds"], ascending=False)

    return df.head(max_bets)
