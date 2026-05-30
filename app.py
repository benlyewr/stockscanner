import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Stock Scanner", layout="wide")
st.title("📈 SaaS Stock Scanner")

tickers = [
    "CRM", "NOW", "SNOW", "DDOG", "NET",
    "ZS", "CRWD", "MDB", "GTLB", "BILL",
    "HUBS", "TEAM", "OKTA", "ZI", "ESTC",
    "CFLT", "TTD", "APPF", "PCTY", "PAYC"
]

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    df = yf.download(ticker, period="1y", auto_adjust=True, progress=False)
    return df

results = []
stock_data = {}
progress = st.progress(0)
status = st.empty()

for i, ticker in enumerate(tickers):
    try:
        status.text(f"Loading {ticker}...")
        df = get_stock_data(ticker)
        close = df["Close"].squeeze()
        price = round(float(close.iloc[-1]), 2)
        ma50 = round(float(close.rolling(50).mean().iloc[-1]), 2)
        ma150 = round(float(close.rolling(150).mean().iloc[-1]), 2)
        ma200 = round(float(close.rolling(200).mean().iloc[-1]), 2)
        score = sum([price > ma50, price > ma150, price > ma200])
        results.append({
            "Ticker": ticker,
            "Price": price,
            "50MA": ma50,
            "150MA": ma150,
            "200MA": ma200,
            "Score": score
        })
        stock_data[ticker] = df
    except Exception as e:
        st.warning(f"Skipped {ticker}: {e}")
    progress.progress((i + 1) / len(tickers))

status.text("Done!")
df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

st.subheader("📊 Scores")
st.dataframe(df_results, use_container_width=True)

st.subheader("📈 Price Charts")
selected = st.selectbox("Select a stock to view chart", df_results["Ticker"].tolist())

if selected and selected in stock_data:
