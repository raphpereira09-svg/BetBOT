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
        if s <= 0:
            continue
        ph, pd_, pa = ph/s, pd_/s, pa/s
        rows.append({"match_id": mid, "league": league, "teams": teams, "start_time_iso": start, "home": home_name, "away": away_name, "p_home": ph, "p_draw": pd_, "p_away": pa, "n_books": len(set(g["book"]))})
    return pd.DataFrame(rows)

def best_price(df: pd.DataFrame) -> float:
    return float(df["price"].max()) if not df.empty else float("nan")

def select_picks(df_all: pd.DataFrame, min_ev: float = 0.02, max_picks: int = 3) -> tuple[list[dict], list[dict]]:
    df_h2h = df_all[(df_all["market"]=="h2h") & (df_all["outcome"].isin(["home","draw","away"]))]
    df_tot = df_all[(df_all["market"]=="totals") & (df_all["outcome"].isin(["over","under"]))].copy()

    cons = build_consensus(df_h2h)
    picks, diags = [], []

    for _, r in cons.iterrows():
        mid = r["match_id"]
        g_h2h = df_h2h[df_h2h["match_id"]==mid]
        g_tot = df_tot[df_tot["match_id"]==mid]

        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        top_scores = ", ".join([f"{i}-{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])

        out_best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]
            price = best_price(sub)
            if not pd.isna(price) and price>1.0:
                p_model = summ[f"p_{side}"]
                ev = p_model * price - 1.0
                if ev >= min_ev:
                    out_best = max(out_best or [], [{
                        "type": "H2H","selection": side.capitalize(),"price": float(price),"prob": float(p_model),"ev": float(ev),"book": sub.sort_values("price", ascending=False)["book"].iloc[0],
                    }], key=lambda x: x[0]["ev"])

        tot25 = g_tot[g_tot["point"].round(2) == 2.50]
        tot_pick = None
        if not tot25.empty:
            p_over = summ["totals_over"].get(2.5, np.nan)
            if not np.isnan(p_over):
                over_odds = best_price(tot25[tot25["outcome"]=="over"])
                under_odds= best_price(tot25[tot25["outcome"]=="under"])
                ev_over = p_over * over_odds - 1.0 if over_odds and over_odds>1.0 else -9
                p_under = 1.0 - p_over
                ev_under = p_under * under_odds - 1.0 if under_odds and under_odds>1.0 else -9
                if max(ev_over, ev_under) >= min_ev:
                    if ev_over >= ev_under:
                        tot_pick = {"type":"Totals","selection":"Over 2.5","price":float(over_odds),"prob":float(p_over),"ev":float(ev_over),"book": tot25[tot25["outcome"]=="over"].sort_values("price",ascending=False)["book"].iloc[0]}
                    else:
                        tot_pick = {"type":"Totals","selection":"Under 2.5","price":float(under_odds),"prob":float(p_under),"ev":float(ev_under),"book": tot25[tot25["outcome"]=="under"].sort_values("price",ascending=False)["book"].iloc[0]}

        candidates = []
        if out_best: candidates += out_best
        if tot_pick: candidates.append(tot_pick)
        if candidates:
            best = max(candidates, key=lambda x: x["ev"])
            picks.append({"match_id": mid,"league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],"mean_score": mean_score, "top_scores": top_scores,"pick_type": best["type"], "selection": best["selection"],"price": best["price"], "prob": best["prob"], "ev": best["ev"], "book": best["book"]})

        diags.append({"match_id": mid, "league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],"mean_score": mean_score, "top_scores": top_scores,"p_home": float(summ["p_home"]), "p_draw": float(summ["p_draw"]), "p_away": float(summ["p_away"]), "p_over25": float(summ["totals_over"].get(2.5, np.nan)),})

    picks = sorted(picks, key=lambda x: x["ev"], reverse=True)[:max_picks]
    return picks, diags
