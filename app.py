import streamlit as st
import yfinance as yf
import pandas as pd

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
    df = yf.download(ticker, period="1y", auto_adjust=True)
    return df

results = []
progress = st.progress(0)

for i, ticker in enumerate(tickers):
    try:
        df = get_stock_data(ticker)
        close = df["Close"]
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
    except:
        pass
    progress.progress((i + 1) / len(tickers))

df_results = pd.DataFrame(results).sort_values("Score", ascending=False)
st.dataframe(df_results, use_container_width=True)
