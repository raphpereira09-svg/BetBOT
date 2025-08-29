from __future__ import annotations
import math, numpy as np, pandas as pd
def dixon_coles_matrix(lmb_home: float, lmb_away: float, rho: float = 0.12, max_goals: int = 8):
    i = np.arange(0, max_goals+1); j = np.arange(0, max_goals+1)
    px = np.exp(-lmb_home) * np.power(lmb_home, i) / np.vectorize(math.factorial)(i)
    py = np.exp(-lmb_away) * np.power(lmb_away, j) / np.vectorize(math.factorial)(j)
    M = np.outer(px, py)
    M[0,0] *= (1 - lmb_home*rho - lmb_away*rho + rho)
    M[0,1] *= (1 + lmb_home*rho); M[1,0] *= (1 + lmb_away*rho); M[1,1] *= (1 - rho)
    M = M / M.sum(); return M
def hda_from_matrix(M): 
    i_idx, j_idx = np.indices(M.shape)
    return float(M[i_idx>j_idx].sum()), float(M[i_idx==j_idx].sum()), float(M[i_idx<j_idx].sum())
def over_prob(M, line: float):
    i_idx, j_idx = np.indices(M.shape); totals = i_idx + j_idx; return float(M[totals > line].sum())
def top_scores(M, k: int = 3):
    flat = [ (i,j,float(M[i,j])) for i in range(M.shape[0]) for j in range(M.shape[1]) ]
    flat.sort(key=lambda x: x[2], reverse=True); return flat[:k]
def calibrate_lambdas(p_home: float, p_draw: float, p_away: float, rho: float = 0.12):
    best = (1.4, 1.1, 1e9)
    for lh in np.linspace(0.4, 2.8, 25):
        for la in np.linspace(0.3, 2.4, 22):
            M = dixon_coles_matrix(lh, la, rho=rho, max_goals=8)
            H, D, A = hda_from_matrix(M)
            loss = (H - p_home)**2 + (D - p_draw)**2 + (A - p_away)**2
            if loss < best[2]: best = (lh, la, loss)
    return best
def summarize_match(home, away, p_home, p_draw, p_away, rho: float=0.12, totals_lines=None):
    lh, la, loss = calibrate_lambdas(p_home, p_draw, p_away, rho=rho)
    M = dixon_coles_matrix(lh, la, rho=rho, max_goals=8); H,D,A = hda_from_matrix(M)
    lines = totals_lines or [2.5]; totals = {float(L): over_prob(M, L) for L in lines}
    mean_home = sum(i * M[i,:].sum() for i in range(M.shape[0]))
    mean_away = sum(j * M[:,j].sum() for j in range(M.shape[1]))
    return {"home": home,"away": away,"lambda_home": lh,"lambda_away": la,"loss": loss,"p_home": H,"p_draw": D,"p_away": A,"mean_home": float(mean_home),"mean_away": float(mean_away),"top_scores": top_scores(M, 3),"totals_over": totals}
