import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import fear_and_greed
import feedparser
import numpy as np

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

@st.cache_data(ttl=1800)
def get_stock_news(ticker):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    news = []
    for entry in feed.entries[:5]:
        news.append({"title": entry.title, "link": entry.link, "published": entry.published})
    return news

@st.cache_data(ttl=3600)
def get_macro():
    macro = {}
    try:
        oil = yf.download("CL=F", period="5d", auto_adjust=True, progress=False)
        macro["Oil"] = f"${round(float(oil['Close'].squeeze().iloc[-1]), 2)}"
    except:
        macro["Oil"] = "N/A"
    try:
        gold = yf.download("GC=F", period="5d", auto_adjust=True, progress=False)
        macro["Gold"] = f"${round(float(gold['Close'].squeeze().iloc[-1]), 2)}"
    except:
        macro["Gold"] = "N/A"
    try:
        vix = yf.download("^VIX", period="5d", auto_adjust=True, progress=False)
        macro["VIX"] = f"{round(float(vix['Close'].squeeze().iloc[-1]), 2)}"
    except:
        macro["VIX"] = "N/A"
    try:
        dxy = yf.download("DX-Y.NYB", period="5d", auto_adjust=True, progress=False)
        macro["USD"] = f"{round(float(dxy['Close'].squeeze().iloc[-1]), 2)}"
    except:
        macro["USD"] = "N/A"
    return macro

@st.cache_data(ttl=3600)
def get_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        rec = stock.recommendations
        strong_buy, buy, hold, sell, strong_sell = 0, 0, 0, 0, 0
        if rec is not None and not rec.empty:
            latest = rec.iloc[-1]
            strong_buy = int(latest.get("strongBuy", 0))
            buy = int(latest.get("buy", 0))
            hold = int(latest.get("hold", 0))
            sell = int(latest.get("sell", 0))
            strong_sell = int(latest.get("strongSell", 0))
        target = info.get("targetMeanPrice", None)
        current = info.get("currentPrice", None)
        upside = round((target - current) / current * 100, 1) if target and current else None
        rev_growth = info.get("revenueGrowth", None)
        earnings_growth = info.get("earningsGrowth", None)
        pe = info.get("trailingPE", None)
        forward_pe = info.get("forwardPE", None)
        profit_margin = info.get("profitMargins", None)
        return {
            "strong_buy": strong_buy,
            "buy": buy,
            "hold": hold,
            "sell": sell,
            "strong_sell": strong_sell,
            "target": target,
            "upside": upside,
            "rev_growth": rev_growth,
            "earnings_growth": earnings_growth,
            "pe": pe,
            "forward_pe": forward_pe,
            "profit_margin": profit_margin
        }
    except:
        return {}

@st.cache_data(ttl=3600)
def get_revenue_estimates(ticker):
    try:
        stock = yf.Ticker(ticker)
        earnings = stock.earnings_dates
        financials = stock.quarterly_financials
        estimates = stock.earnings_estimate
        return estimates
    except:
        return None

def get_support_resistance(close):
    try:
        prices = close.values
        levels = []
        for i in range(2, len(prices) - 2):
            if prices[i] < prices[i-1] and prices[i] < prices[i+1] and prices[i] < prices[i-2] and prices[i] < prices[i+2]:
                levels.append(("support", round(float(prices[i]), 2)))
            if prices[i] > prices[i-1] and prices[i] > prices[i+1] and prices[i] > prices[i-2] and prices[i] > prices[i+2]:
                levels.append(("resistance", round(float(prices[i]), 2)))
        supports = sorted([l[1] for l in levels if l[0] == "support"], reverse=True)[:3]
        resistances = sorted([l[1] for l in levels if l[0] == "resistance"])[:3]
        return supports, resistances
    except:
        return [], []

fg_score, fg_label = get_fear_greed()
spy_return = get_spy_return()
macro = get_macro()

st.markdown("### 🌍 Market Overview")
cols = st.columns(7)
if fg_score:
    fg_color = "🟢" if fg_score >= 60 else "🟡" if fg_score >= 40 else "🔴"
    cols[0].metric(f"{fg_color} Fear & Greed", f"{fg_score} · {fg_label}")
cols[1].metric("📊 SPY 3M", f"{round(spy_return * 100, 1)}%")
cols[2].metric("🛢️ Oil", macro.get("Oil", "N/A"))
cols[3].metric("🥇 Gold", macro.get("Gold", "N/A"))
cols[4].metric("📉 VIX", macro.get("VIX", "N/A"))
cols[5].metric("💵 USD", macro.get("USD", "N/A"))
cols[6].metric("🕐 Updated", pd.Timestamp.now().strftime("%d %b %H:%M"))

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
        pct_from_high = round((price - high52) / high52 * 100, 1)
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
            "vs 52W High": f"{pct_from_high}%",
            "RS vs SPY": f"{rs}%",
            "Avg Vol": f"{int(avg_vol):,}",
            "_ma50_slope": ma50_slope,
            "_price_raw": price,
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

display_cols = ["Ticker","Price","Score","50MA","150MA","200MA","vs 50MA","vs 200MA","vs 52W High","RS vs SPY"]
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
c5.metric("vs 52W High", row["vs 52W High"])
c6.metric("RS vs SPY", row["RS vs SPY"])

st.markdown("#### 📊 Fundamentals")
fund = get_fundamentals(selected)
if fund:
    f1, f2, f3, f4, f5 = st.columns(5)
    f1.metric("🎯 Price Target", f"${fund['target']:.2f}" if fund.get('target') else "N/A")
    f2.metric("📈 Upside", f"{fund['upside']}%" if fund.get('upside') else "N/A")
    f3.metric("💰 Rev Growth", f"{round(fund['rev_growth']*100,1)}%" if fund.get('rev_growth') else "N/A")
    f4.metric("📉 Fwd PE", f"{round(fund['forward_pe'],1)}" if fund.get('forward_pe') else "N/A")
    f5.metric("💵 Profit Margin", f"{round(fund['profit_margin']*100,1)}%" if fund.get('profit_margin') else "N/A")

    st.markdown("#### 🏦 Analyst Ratings")
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("💚 Strong Buy", fund.get('strong_buy', 0))
    a2.metric("🟢 Buy", fund.get('buy', 0))
    a3.metric("🟡 Hold", fund.get('hold', 0))
    a4.metric("🔴 Sell", fund.get('sell', 0))
    a5.metric("❌ Strong Sell", fund.get('strong_sell', 0))

df = stock_data[selected]
close = df["Close"].squeeze()
supports, resistances = get_support_resistance(close)

fig = go.Figure()
fig.add_trace(go.Candlestick(x=df.index, open=df["Open"].squeeze(), high=df["High"].squeeze(), low=df["Low"].squeeze(), close=close, name="Price", increasing_line_color="lime", decreasing_line_color="red"))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(50).mean(), name="50MA", line=dict(color="dodgerblue", width=1.5)))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(150).mean(), name="150MA", line=dict(color="orange", width=1.5)))
fig.add_trace(go.Scatter(x=df.index, y=close.rolling(200).mean(), name="200MA", line=dict(color="red", width=1.5)))
for s in supports:
    fig.add_hline(y=s, line_dash="dash", line_color="lime", opacity=0.5, annotation_text=f"S {s}")
for r in resistances:
    fig.add_hline(y=r, line_dash="dash", line_color="tomato", opacity=0.5, annotation_text=f"R {r}")
if fund.get('target'):
    fig.add_hline(y=fund['target'], line_dash="dot", line_color="gold", opacity=0.8, annotation_text=f"🎯 Target ${fund['target']:.2f}")
fig.update_layout(template="plotly_dark", title=f"{selected}", xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(fig, use_container_width=True)

st.markdown("#### 📐 Support & Resistance")
sr1, sr2 = st.columns(2)
sr1.markdown("**🟢 Support Levels**")
for s in supports:
    sr1.markdown(f"• ${s}")
sr2.markdown("**🔴 Resistance Levels**")
for r in resistances:
    sr2.markdown(f"• ${r}")

st.markdown("### 📰 Latest News")
news = get_stock_news(selected)
if news:
    for item in news:
        st.markdown(f"• [{item['title']}]({item['link']})  \n<small>{item['published']}</small>", unsafe_allow_html=True)
else:
    st.info("No news found.")
