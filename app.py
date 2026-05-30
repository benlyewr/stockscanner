import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests

st.set_page_config(page_title="Stock Scanner", layout="wide")
st.title("📈 Stock Scanner")

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
        r = requests.get("https://api.alternative.me/fng/")
        data = r.json()["data"][0]
        return int(data["value"]), data["value_classification"]
    except:
        return None, None

@st.cache_data(ttl=3600)
def get_politician_trades():
    try:
        r = requests.get("https://www.quiverquant.com/sources/congresstrading")
        return pd.DataFrame(r.json()).head(20)
    except:
        return None

@st.cache_data(ttl=3600)
def get_spy_return():
    spy = yf.download("SPY", period="3mo", auto_adjust=True, progress=False)
    close = spy["Close"].squeeze()
    return float(close.iloc[-1]) / float(close.iloc[0]) - 1

fg_score, fg_label = get_fear_greed()
spy_return = get_spy_return()

col_a, col_b = st.columns(2)
if fg_score:
    color = "🟢" if fg_score > 50 else "🔴"
    col_a.metric(f"{color} Fear & Greed Index", f"{fg_score} — {fg_label}")
col_b.metric("📊 SPY 3M Return", f"{round(spy_return * 100, 1)}%")

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
            "% vs 50MA": f"{pct_from_50}%",
            "% vs 200MA": f"{pct_from_200}%",
            "RS vs SPY": f"{rs}%",
            "Avg Vol": f"{int(avg_vol):,}",
            "MA Slope": ma50_slope
        })
        stock_data[ticker] = df
    except Exception as e:
        st.warning(f"Skipped {ticker}: {e}")
    progress.progress((i + 1) / len(tickers))

status.text("Done!")
df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

def color_score(val):
    if val == 4:
        return "background-color: #008000; color: white"
    elif val == 3:
        return "background-color: #1a5c1a; color: white"
    elif val == 2:
        return "background-color: #5c5c1a; color: white"
    elif val == 1:
        return "background-color: #5c2a1a; color: white"
    else:
        return "background-color: #3d0000; color: white"

st.subheader("📊 Scores")
styled = df_results[["Ticker","Price","Score","50MA","150MA","200MA","% vs 50MA","% vs 200MA","RS vs SPY"]].style.map(color_score, subset=["Score"])
st.dataframe(styled, use_container_width=True)

st.subheader("🔍 Stock Detail")
selected = st.selectbox("Select a stock", [r["Ticker"] for r in results])
row = df_results[df_results["Ticker"] == selected].iloc[0]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Price", row["Price"])
col2.metric("Score", f"{int(row['Score'])}/4")
col3.metric("52W High", row["52W High"])
col4.metric("52W Low", row["52W Low"])

col5, col6, col7, col8 = st.columns(4)
col5.metric("50MA", row["50MA"])
col6.metric("% vs 50MA", row["% vs 50MA"])
col7.metric("200MA", row["200MA"])
col8.metric("RS vs SPY", row["RS vs SPY"])

st.caption(f"Avg Volume: {row['Avg Vol']} | MA Slope: {row['MA Slope']}")

df = stock_data[selected]
close = df["Close"].squeeze()
fig = go.Figure()
fig.add_trace(go.Candlestick(x=df.index, open=df["Open"].squeeze(), high=df["High"].squeeze(), low=df["Low"].squeeze(), close=close, name="Price"))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(50).mean(), name="50MA", line=dict(color="blue")))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(150).mean(), name="150MA", line=dict(color="orange")))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(200).mean(), name="200MA", line=dict(color="red")))
fig.update_layout(template="plotly_dark", title=f"{selected} - 1 Year Chart", xaxis_rangeslider_visible=False, height=500)
st.plotly_chart(fig, use_container_width=True)

st.subheader("🏛️ Politician Trades")
pol_data = get_politician_trades()
if pol_data is not None:
    st.dataframe(pol_data, use_container_width=True)
else:
    st.info("Politician trade data unavailable — requires Quiver Quant API key.")
