from __future__ import annotations
import os, numpy as np, pandas as pd

def build_signal_table() -> pd.DataFrame:
    return pd.DataFrame(columns=["key"])

def adjust_probabilities(df: pd.DataFrame, signal_table: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["adj_prob"] = out["model_prob"].astype(float)
    out["blend_prob"] = out["model_prob"].astype(float)
    return out
