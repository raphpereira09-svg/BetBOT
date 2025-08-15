from __future__ import annotations
import os, numpy as np, pandas as pd
from typing import Tuple

DATA_DIR = os.environ.get("DATA_DIR", "data")

def split_teams(teams: str) -> Tuple[str, str]:
    if " vs " in teams:
        h, a = teams.split(" vs ", 1)
    elif " - " in teams:
        h, a = teams.split(" - ", 1)
    else:
        parts = teams.split()
        mid = len(parts)//2
        h, a = " ".join(parts[:mid]), " ".join(parts[mid:])
    return h.strip(), a.strip()

def _read_csv_if_exists(path: str, columns: list) -> pd.DataFrame:
    if os.path.exists(path):
        try:
            df = pd.read_csv(path)
            for c in columns:
                if c not in df.columns:
                    df[c] = np.nan
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=columns)

def load_form_scores() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "form.csv")
    cols = ["sport","entity_type","entity","metric","value"]
    df = _read_csv_if_exists(path, cols)
    if not df.empty:
        df["key"] = df["sport"].str.lower().str.strip() + "|" + df["entity_type"].str.lower().str.strip() + "|" + df["entity"].astype(str).str.strip().str.lower()
        df = df.groupby(["key","metric"], as_index=False)["value"].sum()
        df = df.pivot(index="key", columns="metric", values="value").fillna(0.0).reset_index()
    return df

def load_injuries() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "injuries.csv")
    cols = ["sport","team","player","status","severity","impact","note"]
    df = _read_csv_if_exists(path, cols)
    if not df.empty:
        df["team_key"] = df["sport"].str.lower().str.strip() + "|team|" + df["team"].astype(str).str.strip().str.lower()
        df = df.groupby("team_key", as_index=False)["impact"].sum().rename(columns={"impact":"injury_impact"})
    return df

def load_news() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "news.csv")
    cols = ["sport","entity_type","entity","tag","impact","confidence","source"]
    df = _read_csv_if_exists(path, cols)
    if not df.empty:
        df["key"] = df["sport"].str.lower().str.strip() + "|" + df["entity_type"].str.lower().str.strip() + "|" + df["entity"].astype(str).str.strip().str.lower()
        df["weighted"] = df["impact"].astype(float) * df["confidence"].astype(float)
        df = df.groupby("key", as_index=False)["weighted"].sum().rename(columns={"weighted":"news_signal"})
    return df

def build_signal_table() -> pd.DataFrame:
    form = load_form_scores()
    injuries = load_injuries()
    news = load_news()
    df = pd.DataFrame({"key":[]})
    for part in [form, injuries, news]:
        if not part.empty:
            if df.empty:
                df = part
            else:
                df = pd.merge(df, part, on=part.columns[0], how="outer")
    if df.empty:
        return pd.DataFrame(columns=["key"])
    for c in df.columns:
        if c != "key":
            df[c] = df[c].fillna(0.0)
    return df

def get_team_signal(signal_table: pd.DataFrame, sport: str, team: str) -> float:
    key = sport.lower().strip() + "|team|" + team.strip().lower()
    row = signal_table[signal_table["key"] == key]
    if row.empty:
        return 0.0
    news = float(row.get("news_signal", 0.0).values[0]) if "news_signal" in row.columns else 0.0
    inj = float(row.get("injury_impact", 0.0).values[0]) if "injury_impact" in row.columns else 0.0
    form_cols = [c for c in row.columns if c not in ("key","news_signal","injury_impact")]
    form_score = float(row[form_cols].sum(axis=1).values[0]) if form_cols else 0.0
    raw = 0.6*news + 0.3*form_score + 0.1*inj
    return float(np.tanh(raw))

def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1-1e-6)
    return float(np.log(p/(1-p)))

def inv_logit(z: float) -> float:
    return float(1.0/(1.0+np.exp(-z)))

def adjust_probabilities(df: pd.DataFrame, signal_table: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["adj_prob"] = out["model_prob"].astype(float)
    for idx, r in out.iterrows():
        sport = str(r.get("sport","")).lower()
        market = str(r.get("market","")).lower()
        teams = str(r.get("teams",""))
        outcome = str(r.get("outcome",""))
        base_p = float(r.get("model_prob", 0.5))
        if not teams or not outcome:
            continue
        home, away = split_teams(teams)
        s_home = get_team_signal(signal_table, sport, home)
        s_away = get_team_signal(signal_table, sport, away)
        delta = 0.0
        if market in ("1x2","match winner","moneyline"):
            if outcome.lower() in (home.lower(), "home", "1", f"{home.lower()} win"):
                delta = (s_home - s_away) * 0.5
            elif outcome.lower() in (away.lower(), "away", "2", f"{away.lower()} win"):
                delta = (s_away - s_home) * 0.5
            elif outcome.lower() in ("draw","x","nul"):
                delta = -abs(s_home - s_away) * 0.3
        elif market in ("over/under","totals"):
            s_total = s_home + s_away
            if "under" in outcome.lower():
                delta = (-abs(s_total)) * 0.3
            elif "over" in outcome.lower():
                delta = (abs(s_total)) * 0.3
        z = logit(base_p) + delta
        out.at[idx, "adj_prob"] = inv_logit(z)
    return out
