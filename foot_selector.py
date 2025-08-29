from __future__ import annotations
import pandas as pd, numpy as np
from foot_model import summarize_match
def implied_prob(odds: float): return 1.0/float(odds) if odds>1.0 else 1.0
def consensus_from_prices(prices):
    imps = sorted([implied_prob(x) for x in prices if x and x>1.0])
    if not imps: return 0.0
    mid = len(imps)//2; return imps[mid] if len(imps)%2==1 else 0.5*(imps[mid-1]+imps[mid])
def build_consensus(df_h2h: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mid, g in df_h2h.groupby("match_id"):
        teams = g["teams"].iloc[0]; league = g["league"].iloc[0]; start  = g["start_time_iso"].iloc[0]
        home_name = g["book_home"].iloc[0]; away_name = g["book_away"].iloc[0]
        ph = consensus_from_prices(g[g["outcome"]=="home"]["price"].tolist())
        pd_ = consensus_from_prices(g[g["outcome"]=="draw"]["price"].tolist())
        pa = consensus_from_prices(g[g["outcome"]=="away"]["price"].tolist())
        s = ph + pd_ + pa
        if s <= 0: continue
        ph, pd_, pa = ph/s, pd_/s, pa/s
        rows.append({"match_id": mid,"league": league,"teams": teams,"start_time_iso": start,"home": home_name,"away": away_name,"p_home": ph,"p_draw": pd_,"p_away": pa,"n_books": len(set(g["book"]))})
    return pd.DataFrame(rows)
def best_price_and_book(df: pd.DataFrame):
    if df.empty: return float("nan"), ""
    idx = df["price"].idxmax(); return float(df.loc[idx,"price"]), str(df.loc[idx,"book"])
def select_picks(df_all: pd.DataFrame, min_ev: float = 0.02, max_picks: int = 3):
    df_h2h = df_all[(df_all["market"]=="h2h") & (df_all["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df_all[(df_all["market"]=="totals") & (df_all["outcome"].isin(["over","under"]))].copy()
    if "point" in df_tot.columns: df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")
    cons = build_consensus(df_h2h); picks, diags = [], []
    for _, r in cons.iterrows():
        mid = r["match_id"]; g_h2h = df_h2h[df_h2h["match_id"]==mid]; g_tot = df_tot[df_tot["match_id"]==mid]
        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        top_scores = ", ".join([f"{i}-{j} {p*100:.1f}%" for i,j,p in summ["top_scores"]])
        out_best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]; price, book = best_price_and_book(sub)
            if not pd.isna(price) and price>1.0:
                p_model = float(summ[f"p_{side}"]); ev = p_model * price - 1.0
                if ev >= min_ev:
                    cand = {"type":"H2H","selection":side.capitalize(),"price":float(price),"prob":p_model,"ev":float(ev),"book":book}
                    if (out_best is None) or (cand["ev"] > out_best["ev"]): out_best = cand
        tot25 = g_tot[g_tot["point"].round(2) == 2.50]; tot_pick = None
        if not tot25.empty:
            p_over = float(summ["totals_over"].get(2.5, np.nan))
            if not np.isnan(p_over):
                over_df = tot25[tot25["outcome"]=="over"]; under_df= tot25[tot25["outcome"]=="under"]
                over_odds, over_book = best_price_and_book(over_df); under_odds, under_book= best_price_and_book(under_df)
                ev_over  = p_over * over_odds - 1.0 if over_odds and over_odds>1.0 else -9
                p_under  = 1.0 - p_over; ev_under = p_under * under_odds - 1.0 if under_odds and under_odds>1.0 else -9
                if max(ev_over, ev_under) >= min_ev:
                    tot_pick = ({"type":"Totals","selection":"Over 2.5","price":float(over_odds),"prob":p_over,"ev":float(ev_over),"book":over_book}
                                if ev_over>=ev_under else
                                {"type":"Totals","selection":"Under 2.5","price":float(under_odds),"prob":p_under,"ev":float(ev_under),"book":under_book})
        candidates = []; 
        if out_best: candidates.append(out_best)
        if tot_pick: candidates.append(tot_pick)
        if candidates:
            best = max(candidates, key=lambda x: x["ev"])
            picks.append({"match_id": mid,"league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],
                          "mean_score": mean_score, "top_scores": top_scores,
                          "pick_type": best["type"], "selection": best["selection"],
                          "price": best["price"], "prob": best["prob"], "ev": best["ev"], "book": best["book"]})
        diags.append({"match_id": mid,"league": r["league"], "teams": r["teams"], "start_time_iso": r["start_time_iso"],
                      "mean_score": mean_score, "top_scores": top_scores,
                      "p_home": float(summ["p_home"]), "p_draw": float(summ["p_draw"]), "p_away": float(summ["p_away"]),
                      "p_over25": float(summ["totals_over"].get(2.5, np.nan)),})
    picks = sorted(picks, key=lambda x: x["ev"], reverse=True)[:max_picks]
    return picks, diags
def weekend_report(df_all: pd.DataFrame, min_ev: float = 0.01):
    df_h2h = df_all[(df_all["market"]=="h2h") & (df_all["outcome"].isin(["home","draw","away"]))].copy()
    df_tot = df_all[(df_all["market"]=="totals") & (df_all["outcome"].isin(["over","under"]))].copy()
    if "point" in df_tot.columns: df_tot["point"] = pd.to_numeric(df_tot["point"], errors="coerce")
    cons = build_consensus(df_h2h); lines_by_league = {}
    for _, r in cons.iterrows():
        mid = r["match_id"]; g_h2h = df_h2h[df_h2h["match_id"]==mid]; g_tot = df_tot[df_tot["match_id"]==mid]
        summ = summarize_match(r["home"], r["away"], r["p_home"], r["p_draw"], r["p_away"], rho=0.12, totals_lines=[2.5])
        mean_score = f"{summ['mean_home']:.2f}-{summ['mean_away']:.2f}"
        hda = f"H/D/A {summ['p_home']*100:.0f}/{summ['p_draw']*100:.0f}/{summ['p_away']*100:.0f}%"
        over25 = summ['totals_over'].get(2.5, np.nan); over_s = f"Over2.5 {over25*100:.0f}%" if not pd.isna(over25) else ""
        best = None
        for side in ["home","draw","away"]:
            sub = g_h2h[g_h2h["outcome"]==side]; price, book = best_price_and_book(sub)
            if price and price>1.0:
                p = float(summ[f"p_{side}"]); ev = p*price - 1.0
                cand = {"type":"H2H","sel":side.capitalize(),"odds":price,"p":p,"ev":ev,"book":book}
                if (best is None) or (cand["ev"] > best["ev"]): best = cand
        tot25 = g_tot[g_tot["point"].round(2)==2.50]
        if not tot25.empty and not pd.isna(over25):
            over_odds, over_book = best_price_and_book(tot25[tot25["outcome"]=="over"])
            under_odds, under_book= best_price_and_book(tot25[tot25["outcome"]=="under"])
            ev_over = over25*over_odds - 1.0 if over_odds and over_odds>1.0 else -9
            p_under = 1.0 - over25; ev_under= p_under*under_odds - 1.0 if under_odds and under_odds>1.0 else -9
            if ev_over >= ev_under and ev_over > (best["ev"] if best else -9):
                best = {"type":"Totals","sel":"Over 2.5","odds":over_odds,"p":over25,"ev":ev_over,"book":over_book}
            elif ev_under > (best["ev"] if best else -9):
                best = {"type":"Totals","sel":"Under 2.5","odds":under_odds,"p":p_under,"ev":ev_under,"book":under_book}
        league = r["league"]; teams = r["teams"]
        if best and best["ev"] >= min_ev:
            line = f"• {teams} — {mean_score} | {hda} | {over_s} → ✅ {best['type']} {best['sel']} @ {best['odds']:.2f} (EV {best['ev']*100:.1f}%)"
        else:
            lean = "Lean: " + ("Home" if summ['p_home']>max(summ['p_draw'], summ['p_away']) else ("Away" if summ['p_away']>max(summ['p_home'], summ['p_draw']) else "Draw"))
            line = f"• {teams} — {mean_score} | {hda} | {over_s} → ⚪️ {lean} (pas de value)"
        lines_by_league.setdefault(league, []).append(line)
    for lg in list(lines_by_league): lines_by_league[lg] = sorted(lines_by_league[lg])
    return lines_by_league
