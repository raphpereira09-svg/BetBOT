import os, pandas as pd, numpy as np, datetime as dt, pytz, matplotlib.pyplot as plt
import streamlit as st

DATA_DIR = os.environ.get("DATA_DIR","data")
JOURNAL = os.path.join(DATA_DIR, "journal.csv")

st.set_page_config(page_title="Value Bets Dashboard", layout="wide")
st.title("📈 Value Bets — Journal & Dashboard")

if not os.path.exists(JOURNAL) or os.path.getsize(JOURNAL)==0:
    st.info("Le journal est vide. Envoie d'abord des sélections via le bot.")
    st.stop()

df = pd.read_csv(JOURNAL)
if df.empty:
    st.info("Journal vide.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
sports = sorted([s for s in df["sport"].dropna().unique()])
leagues = sorted([s for s in df["league"].dropna().unique()])
with col1:
    f_sport = st.multiselect("Sport", sports, default=sports)
with col2:
    f_league = st.multiselect("Ligue", leagues, default=leagues[:10] if len(leagues)>10 else leagues)
with col3:
    f_status = st.selectbox("Statut", ["any","open","settled"], index=0)
with col4:
    min_date = st.date_input("Depuis", value=dt.date.today() - dt.timedelta(days=30))

mask = df["sport"].isin(f_sport) & df["league"].isin(f_league)
if f_status != "any":
    mask &= (df["status"]==f_status)
mask &= pd.to_datetime(df["timestamp_iso"]).dt.date >= pd.to_datetime(min_date).date()
view = df[mask].copy()

st.subheader("🧾 Sélections")
st.dataframe(view)

st.subheader("💰 Courbe de bankroll")
settled = df[df["status"]=="settled"].sort_values("timestamp_iso").copy()
if not settled.empty:
    if settled["bankroll_before"].notna().any():
        bk0 = float(settled["bankroll_before"].dropna().iloc[0])
    else:
        bk0 = 100.0
    equity = [bk0]
    times = [pd.to_datetime(settled.iloc[0]["timestamp_iso"])]
    b = bk0
    for _, r in settled.iterrows():
        pnl = float(r.get("pnl", 0.0) or 0.0)
        b += pnl
        equity.append(b)
        times.append(pd.to_datetime(r["timestamp_iso"]))
    fig, ax = plt.subplots()
    ax.plot(times, equity)  # no style/colors specified per policy
    ax.set_xlabel("Temps")
    ax.set_ylabel("Bankroll")
    st.pyplot(fig)
else:
    st.info("Aucune ligne soldée pour tracer la courbe. Utilisez la commande /settle sur Telegram.")

st.subheader("📊 KPIs")
if not settled.empty:
    n = len(settled)
    wins = (settled["result"]=="win").sum()
    losses = (settled["result"]=="loss").sum()
    pushes = (settled["result"]=="push").sum()
    total_pnl = float(settled["pnl"].fillna(0).sum())
    roi = total_pnl / max(1e-9, settled["stake"].sum())
    avg_edge = float(settled["edge"].astype(float).fillna(0).mean())
    colA, colB, colC, colD, colE = st.columns(5)
    colA.metric("Paris soldés", n)
    colB.metric("Taux de victoire", f"{(wins/max(1,n))*100:.1f}%")
    colC.metric("ROI", f"{roi*100:.1f}%")
    colD.metric("PNL total", f"{total_pnl:.2f}")
    colE.metric("Edge moyen", f"{avg_edge*100:.2f}%")
else:
    st.info("Aucune ligne soldée.")
