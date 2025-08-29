# foot_selector.py — FIXED
from __future__ import annotations
import pandas as pd
import numpy as np
from foot_model import summarize_match

def implied_prob(decimal_odds: float) -> float:
    return 1.0/float(decimal_odds) if decimal_odds>1.0 else 1.0

def consensus_from_prices(prices: list[float]) -> float:
    imps = sorted([implied_prob(x) for x in prices if x and x>1.0])
    if not imps: return 0.0
    mid = len(imps)//2
    med = imps[mid] if len(imps)%2==1 else 0.5*(imps[mid-1]+imps[mid])
    return med

def build_consensus(df_h2h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mid, g in df_h2h.groupby("match_id"):
        teams = g["teams"].iloc[0]
        league = g["league"].iloc[0]
        start  = g["start_time_iso"].iloc[0]
        home_name = g["book_home"].iloc[0]; away_name = g["book_away"].iloc[0]
        home_prices = g[g["outcome"]=="home"]["price"].tolist()
        draw_prices = g[g["outcome"]=="draw"]["price"].tolist()
        away_prices = g[g["outcome"]=="away"]["price"].tolist()
        ph = consensus_from_prices(home_prices)
        pd_ = consensus_from_prices(draw_prices)
        pa = consensus_from_prices(away_prices)
        s = ph + pd_ + pa
        if s <= 0:  # pas assez de données
            continue
        ph, pd_, pa = ph/s, pd_/s, pa/s
        rows.append({
            "match_id": mid, "league": league, "teams": teams, "start_time_iso": start,
            "home": home_name, "away": away_name,
            "p_home": ph, "p_draw": pd_, "p_away": pa,
            "n_books": len(set(g["book"]))
        })
    return pd.DataFrame(rows)

def best_price_and_book(df: pd.DataFrame) -> tuple[float, str]:
    if df.empty: return float("nan"), ""
    idx = df["price"].idxmax()
    return float(df.loc[idx, "price"]), str(df.loc[idx, "book"])

def select_picks(df_all: pd.DataFrame, min_ev: float = 0.02, max_picks: int = 3) -> tuple[list[dict], list[dict]]:
    df_h2h = df_all[(df_all["market"]=="h2h") & (df_all["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df_all[(df_all["market"]=="totals") & (df_all["outcome"].isin(["over","under"]))].copy()
    # sécurise la colonne point (numérique)
    if "point" in df_tot.columns:
        df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")

    cons = build_consensus(df_h2h)
    picks, diags = [], []

    for _, r in cons.iterrows():
        mid = r["match_id"]
        g_h2h = df_h2h[df_h2h["match_id"]==mid]
        g_tot = df_tot[df_tot["match_id"]==mid]

        # Modèle de score à partir de H/D/A
        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        top_scores = ", ".join([f"{i}-{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])

        # ----- H2H : garder le meilleur côté si EV >= seuil
        out_best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]
            price, book = best_price_and_book(sub)
            if not pd.isna(price) and price>1.0:
                p_model = float(summ[f"p_{side}"])
                ev = p_model * price - 1.0
                if ev >= min_ev:
                    cand = {
                        "type": "H2H",
                        "selection": side.capitalize(),
                        "price": float(price),
                        "prob": p_model,
                        "ev": float(ev),
                        "book": book,
                    }
                    if (out_best is None) or (cand["ev"] > out_best["ev"]):
                        out_best = cand

        # ----- Totals 2.5 : over/under si EV >= seuil
        tot25 = g_tot[g_tot["point"].round(2) == 2.50]
        tot_pick = None
        if not tot25.empty:
            p_over = float(summ["totals_over"].get(2.5, np.nan))
            if not np.isnan(p_over):
                over_df = tot25[tot25["outcome"]=="over"]
                under_df= tot25[tot25["outcome"]=="under"]
                over_odds, over_book = best_price_and_book(over_df)
                under_odds, under_book= best_price_and_book(under_df)
                ev_over  = p_over * over_odds - 1.0 if over_odds and over_odds>1.0 else -9
                p_under  = 1.0 - p_over
                ev_under = p_under * under_odds - 1.0 if under_odds and under_odds>1.0 else -9
                if max(ev_over, ev_under) >= min_ev:
                    if ev_over >= ev_under:
                        tot_pick = {"type":"Totals","selection":"Over 2.5","price":float(over_odds),
                                    "prob":p_over,"ev":float(ev_over),"book":over_book}
                    else:
                        tot_pick = {"type":"Totals","selection":"Under 2.5","price":float(under_odds),
                                    "prob":p_under,"ev":float(ev_under),"book":under_book}

        # Choisir le meilleur pick pour ce match
        candidates = []
        if out_best: candidates.append(out_best)
        if tot_pick: candidates.append(tot_pick)
        if candidates:
            best = max(candidates, key=lambda x: x["ev"])
            picks.append({
                "match_id": mid,
                "league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],
                "mean_score": mean_score, "top_scores": top_scores,
                "pick_type": best["type"], "selection": best["selection"],
                "price": best["price"], "prob": best["prob"], "ev": best["ev"], "book": best["book"]
            })

        # Diagnostics
        diags.append({
            "match_id": mid, "league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],
            "mean_score": mean_score, "top_scores": top_scores,
            "p_home": float(summ["p_home"]), "p_draw": float(summ["p_draw"]), "p_away": float(summ["p_away"]),
            "p_over25": float(summ["totals_over"].get(2.5, np.nan)),
        })

    # Tri final par EV et coupe à max_picks
    picks = sorted(picks, key=lambda x: x["ev"], reverse=True)[:max_picks]
    return picks, diags
