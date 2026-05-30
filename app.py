import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import fear_and_greed

st.set_page_config(page_title="Stock Scanner", layout="wide")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.2rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
div[data-testid="stDataFrame"] { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

st.markdown("## 📈 Stock Scanner")

tickers = [
    "MSFT", "AAPL", "NVDA", "AVGO", "WDC",
    "GOOG", "META", "AMZN", "NOW", "GLW",
    "MCD", "QUBT", "UEC", "AGYS", "IBM",
    "UBER", "NFLX", "ORCL", "BABA", "CRWV"
]

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    df = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
    return df

@st.cache_data(ttl=3600)
def get_fear_greed():
    try:
        data = fear_and_greed.get()
        return round(data.value), data.description
    except:
        return None, None

@st.cache_data(ttl=3600)
def get_spy_return():
    spy = yf.download("SPY", period="3mo", auto_adjust=True, progress=False)
    close = spy["Close"].squeeze()
    return float(close.iloc[-1]) / float(close.iloc[0]) - 1

fg_score, fg_label = get_fear_greed()
spy_return = get_spy_return()

c1, c2, c3 = st.columns(3)
if fg_score:
    fg_color = "🟢" if fg_score >= 60 else "🟡" if fg_score >= 40 else "🔴"
    c1.metric(f"{fg_color} Fear & Greed", f"{fg_score} · {fg_label}")
c2.metric("📊 SPY 3M", f"{round(spy_return * 100, 1)}%")
c3.metric("🕐 Last Updated", pd.Timestamp.now().strftime("%d %b %H:%M"))

st.divider()

results = []
stock_data = {}
progress = st.progress(0)
status = st.empty()

for i, ticker in enumerate(tickers):
    try:
        status.text(f"Loading {ticker}...")
        df = get_stock_data(ticker)
        close = df["Close"].squeeze()
        vol = df["Volume"].squeeze()
        price = round(float(close.iloc[-1]), 2)
        ma50 = round(float(close.rolling(50).mean().iloc[-1]), 2)
        ma150 = round(float(close.rolling(150).mean().iloc[-1]), 2)
        ma200 = round(float(close.rolling(200).mean().iloc[-1]), 2)
        high52 = round(float(close.max()), 2)
        low52 = round(float(close.min()), 2)
        pct_from_50 = round((price - ma50) / ma50 * 100, 1)
        pct_from_200 = round((price - ma200) / ma200 * 100, 1)
        avg_vol = round(float(vol.rolling(50).mean().iloc[-1]), 0)
        ma50_slope = round(float(close.rolling(50).mean().iloc[-1]) - float(close.rolling(50).mean().iloc[-6]), 2)
        stock_return = float(close.iloc[-1]) / float(close.iloc[0]) - 1
        rs = round((stock_return - spy_return) * 100, 1)
        score = sum([price > ma50, price > ma150, price > ma200, ma50_slope > 0])
        results.append({
            "Ticker": ticker,
            "Price": f"${price:.2f}",
            "Score": score,
            "50MA": f"${ma50:.2f}",
            "150MA": f"${ma150:.2f}",
            "200MA": f"${ma200:.2f}",
            "52W High": f"${high52:.2f}",
            "52W Low": f"${low52:.2f}",
            "vs 50MA": f"{pct_from_50}%",
            "vs 200MA": f"{pct_from_200}%",
            "RS vs SPY": f"{rs}%",
            "Avg Vol": f"{int(avg_vol):,}",
            "_ma50_slope": ma50_slope,
            "_price_raw": price,
            "_ma50_raw": ma50,
            "_ma150_raw": ma150,
            "_ma200_raw": ma200,
            "_high52": high52,
            "_low52": low52
        })
        stock_data[ticker] = df
    except Exception as e:
        st.warning(f"Skipped {ticker}: {e}")
    progress.progress((i + 1) / len(tickers))

status.empty()
progress.empty()

df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

def color_score(val):
    if val == 4:
        return "background-color: #008000; color: white; font-weight: bold"
    elif val == 3:
        return "background-color: #1a5c1a; color: white"
    elif val == 2:
        return "background-color: #5c5c1a; color: white"
    elif val == 1:
        return "background-color: #5c2a1a; color: white"
    else:
        return "background-color: #3d0000; color: white"

display_cols = ["Ticker","Price","Score","50MA","150MA","200MA","vs 50MA","vs 200MA","RS vs SPY"]
st.markdown("### 📊 Scores")
styled = df_results[display_cols].style.map(color_score, subset=["Score"])
st.dataframe(styled, use_container_width=True, height=400)

st.markdown("### 🔍 Stock Detail")
selected = st.selectbox("", [r["Ticker"] for r in results])
row = df_results[df_results["Ticker"] == selected].iloc[0]

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Price", row["Price"])
c2.metric("Score", f"{int(row['Score'])}/4")
c3.metric("52W High", row["52W High"])
c4.metric("52W Low", row["52W Low"])
c5.metric("vs 50MA", row["vs 50MA"])
c6.metric("RS vs SPY", row["RS vs SPY"])

df = stock_data[selected]
close = df["Close"].squeeze()
fig = go.Figure()
fig.add_trace(go.Candlestick(x=df.index, open=df["Open"].squeeze(), high=df["High"].squeeze(), low=df["Low"].squeeze(), close=close, name="Price", increasing_line_color="lime", decreasing_line_color="red"))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(50).mean(), name="50MA", line=dict(color="dodgerblue", width=1.5)))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(150).mean(), name="150MA", line=dict(color="orange", width=1.5)))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(200).mean(), name="200MA", line=dict(color="red", width=1.5)))
fig.update_layout(template="plotly_dark", title=f"{selected}", xaxis_rangeslider_visible=False, height=450, margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(fig, use_container_width=True)
