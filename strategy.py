import pandas as pd

def implied_prob_from_decimal(odds: float) -> float:
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds

def edge(model_p: float, odds: float) -> float:
    return float(model_p) - implied_prob_from_decimal(float(odds))

def fractional_kelly(model_p: float, odds: float, fraction: float = 0.25) -> float:
    b = float(odds) - 1.0
    p = float(model_p)
    if b <= 0 or p <= 0.0 or p >= 1.0:
        return 0.0
    k = ((b * p) - (1 - p)) / b
    return max(0.0, k * float(fraction))

def pick_daily_bets(df: pd.DataFrame, min_edge: float, max_bets: int = 3, use_adj: bool = True):
    df = df.copy()
    prob_col = "adj_prob" if (use_adj and "adj_prob" in df.columns) else "model_prob"
    df["edge"] = df.apply(lambda r: edge(r[prob_col], r["book_odds"]), axis=1)
    df["ev"] = df[prob_col] * df["book_odds"] - 1.0
    df = df[(df["book_odds"]>=1.30) & (df[prob_col].between(0.02, 0.98))]
    df = df.sort_values(["ev","edge",prob_col], ascending=False)
    return df.head(max_bets)
