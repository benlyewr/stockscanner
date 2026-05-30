import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import feedparser
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock Scanner V2", layout="wide")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1.1rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.7rem !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("## 📈 Stock Scanner V2")

FMP_API_KEY = st.secrets.get("FMP_API_KEY", None)

tickers = [
    "MSFT", "AAPL", "NVDA", "AVGO", "WDC",
    "GOOG", "META", "AMZN", "NOW", "GLW",
    "MCD", "QUBT", "UEC", "AGYS", "IBM",
    "UBER", "NFLX", "ORCL", "BABA", "CRWV",
    "SMTC", "DY", "IONQ", "UNH", "SMCI",
    "NBIS", "MU", "DRAM", "VST", "HWM",
    "RDDT", "TSM", "ADI", "SNDK", "STRL",
    "BA", "APLD", "MSTR", "MARA", "MELI",
    "RCL", "MRVL", "TSLA", "ARM"
]

def get_label(score):
    if score >= 85: return "🟢 Strong Candidate"
    elif score >= 70: return "🟩 Watchlist"
    elif score >= 55: return "🟨 Early Setup"
    else: return "🔴 Ignore"

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    try:
        df = yf.download(ticker, period="5y", auto_adjust=True, progress=False)
        if df.empty or len(df) < 50:
            t = yf.Ticker(ticker)
            df = t.history(period="5y")
        if df.empty or len(df) < 50:
            return None
        return df
    except:
        return None

@st.cache_data(ttl=3600)
def get_fear_greed():
    try:
        import fear_and_greed
        data = fear_and_greed.get()
        return round(data.value), data.description
    except:
        try:
            r = requests.get("https://api.alternative.me/fng/")
            data = r.json()["data"][0]
            return int(data["value"]), data["value_classification"]
        except:
            return None, None

@st.cache_data(ttl=3600)
def get_spy_return():
    spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
    close = spy["Close"].squeeze()
    return float(close.iloc[-1]) / float(close.iloc[0]) - 1

@st.cache_data(ttl=3600)
def get_macro():
    macro = {}
    symbols = {
        "Oil": "CL=F", "Gold": "GC=F", "VIX": "^VIX", "USD": "DX-Y.NYB",
        "1Y Treasury": "^IRX", "10Y Treasury": "^TNX", "20Y Treasury": "^TYX"
    }
    for name, sym in symbols.items():
        try:
            df = yf.download(sym, period="5d", auto_adjust=True, progress=False)
            close = df["Close"].squeeze()
            val = round(float(close.iloc[-1]), 2)
            prev = round(float(close.iloc[-2]), 2)
            chg = round(val - prev, 2)
            macro[name] = {"value": val, "change": chg}
        except:
            macro[name] = {"value": "N/A", "change": 0}
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
        return {
            "strong_buy": strong_buy, "buy": buy, "hold": hold,
            "sell": sell, "strong_sell": strong_sell,
            "target": target, "upside": upside,
            "rev_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "profit_margin": info.get("profitMargins"),
            "eps_forward": info.get("forwardEps"),
            "eps_trailing": info.get("trailingEps")
        }
    except:
        return {}

@st.cache_data(ttl=3600)
def get_fmp_financials(ticker):
    if not FMP_API_KEY:
        return None, None
    try:
        url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?limit=5&apikey={FMP_API_KEY}"
        r = requests.get(url)
        actuals = r.json()
        url2 = f"https://financialmodelingprep.com/api/v3/analyst-estimates/{ticker}?limit=3&apikey={FMP_API_KEY}"
        r2 = requests.get(url2)
        estimates = r2.json()
        return actuals, estimates
    except:
        return None, None

@st.cache_data(ttl=1800)
def get_stock_news(ticker):
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        feed = feedparser.parse(url)
        return [{"title": e.title, "link": e.link, "published": e.published} for e in feed.entries[:6]]
    except:
        return []

def detect_123_reversal(close):
    try:
        prices = close.values[-60:]
        lows = []
        for i in range(2, len(prices)-2):
            if prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                lows.append((i, prices[i]))
        if len(lows) >= 2:
            p1_idx, p1 = lows[-2]
            p3_idx, p3 = lows[-1]
            if p3 > p1:
                p2 = max(prices[p1_idx:p3_idx])
                current = prices[-1]
                if current > p2:
                    return True
        return False
    except:
        return False

def get_support_resistance(close):
    try:
        prices = close.values
        supports, resistances = [], []
        for i in range(2, len(prices)-2):
            if prices[i] < prices[i-1] and prices[i] < prices[i+1] and prices[i] < prices[i-2] and prices[i] < prices[i+2]:
                supports.append(round(float(prices[i]), 2))
            if prices[i] > prices[i-1] and prices[i] > prices[i+1] and prices[i] > prices[i-2] and prices[i] > prices[i+2]:
                resistances.append(round(float(prices[i]), 2))
        price_now = float(prices[-1])
        supports = sorted([s for s in supports if s < price_now], reverse=True)[:3]
        resistances = sorted([r for r in resistances if r > price_now])[:3]
        return supports, resistances
    except:
        return [], []

fg_score, fg_label = get_fear_greed()
spy_return = get_spy_return()

results = []
skipped = []
stock_data = {}

with st.spinner("Loading all stocks..."):
    progress = st.progress(0)
    for i, ticker in enumerate(tickers):
        df = get_stock_data(ticker)
        if df is None:
            skipped.append(ticker)
            progress.progress((i+1)/len(tickers))
            continue
        try:
            close = df["Close"].squeeze()
            vol = df["Volume"].squeeze()
            close_1y = close.iloc[-252:] if len(close) >= 252 else close
            price = round(float(close.iloc[-1]), 2)
            ma50 = round(float(close_1y.rolling(50).mean().iloc[-1]), 2)
            ma150 = round(float(close_1y.rolling(150).mean().iloc[-1]), 2)
            ma200 = round(float(close_1y.rolling(200).mean().iloc[-1]), 2)
            high52 = round(float(close_1y.max()), 2)
            low52 = round(float(close_1y.min()), 2)
            pct_from_50 = round((price - ma50) / ma50 * 100, 1)
            pct_from_200 = round((price - ma200) / ma200 * 100, 1)
            pct_from_high = round((price - high52) / high52 * 100, 1)
            avg_vol = round(float(vol.rolling(50).mean().iloc[-1]), 0)
            ma50_slope = float(close_1y.rolling(50).mean().iloc[-1]) - float(close_1y.rolling(50).mean().iloc[-6])
            ma200_slope = float(close_1y.rolling(200).mean().iloc[-1]) - float(close_1y.rolling(200).mean().iloc[-10])
            stock_return = float(close_1y.iloc[-1]) / float(close_1y.iloc[0]) - 1
            rs = round((stock_return - spy_return) * 100, 1)
            reversal_123 = detect_123_reversal(close_1y)
            fund = get_fundamentals(ticker)
            rev_growth = fund.get("rev_growth")
            earnings_growth = fund.get("earnings_growth")
            profit_margin = fund.get("profit_margin")
            forward_pe = fund.get("forward_pe")

            score = 0
            if reversal_123: score += 25
            if price > ma50: score += 5
            if price > ma150: score += 5
            if price > ma200: score += 5
            if ma50 > ma150 > ma200: score += 15
            if ma50_slope > 0: score += 10
            if ma200_slope > 0: score += 10
            if rs > 0: score += 10
            if rs > 10: score += 10
            if rev_growth and rev_growth > 0: score += 15
            if earnings_growth and earnings_growth > 0: score += 10
            if profit_margin and profit_margin > 0: score += 5
            if forward_pe and 0 < forward_pe < 60: score += 5
            if fg_score and fg_score >= 75: score -= 10

            results.append({
                "Ticker": ticker,
                "Price": f"${price:.2f}",
                "Score": score,
                "Label": get_label(score),
                "50MA": f"${ma50:.2f}",
                "150MA": f"${ma150:.2f}",
                "200MA": f"${ma200:.2f}",
                "52W High": f"${high52:.2f}",
                "52W Low": f"${low52:.2f}",
                "vs 50MA": f"{pct_from_50}%",
                "vs 200MA": f"{pct_from_200}%",
                "vs 52W High": f"{pct_from_high}%",
                "RS vs SPY": f"{rs}%",
                "123 Reversal": "✅" if reversal_123 else "❌",
                "Avg Vol": f"{int(avg_vol):,}",
                "_price_raw": price,
                "_ma50_slope": ma50_slope,
                "_ma200_slope": ma200_slope
            })
            stock_data[ticker] = df
        except Exception as e:
            skipped.append(ticker)
        progress.progress((i+1)/len(tickers))
    progress.empty()

df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

if skipped:
    st.warning(f"Could not load: {', '.join(skipped)}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Scanner", "📈 Chart", "💰 Revenue & EPS", "🌍 Macro", "📰 News"])

with tab1:
    def color_score(val):
        if val >= 85: return "background-color: #008000; color: white; font-weight: bold"
        elif val >= 70: return "background-color: #1a5c1a; color: white"
        elif val >= 55: return "background-color: #5c5c1a; color: white"
        else: return "background-color: #3d0000; color: white"

    display_cols = ["Ticker","Price","Score","Label","50MA","150MA","200MA","vs 50MA","vs 200MA","vs 52W High","RS vs SPY","123 Reversal"]
    styled = df_results[display_cols].style.map(color_score, subset=["Score"])
    st.dataframe(styled, use_container_width=True, height=500)

    c1, c2, c3, c4 = st.columns(4)
    strong = df_results[df_results["Score"] >= 85]
    watch = df_results[(df_results["Score"] >= 70) & (df_results["Score"] < 85)]
    early = df_results[(df_results["Score"] >= 55) & (df_results["Score"] < 70)]
    ignore = df_results[df_results["Score"] < 55]
    c1.metric("🟢 Strong Candidates", len(strong))
    c2.metric("🟩 Watchlist", len(watch))
    c3.metric("🟨 Early Setup", len(early))
    c4.metric("🔴 Ignore", len(ignore))

with tab2:
    selected = st.selectbox("Select stock", df_results["Ticker"].tolist())
    row = df_results[df_results["Ticker"] == selected].iloc[0]
    fund = get_fundamentals(selected)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Price", row["Price"])
    c2.metric("Score", f"{int(row['Score'])}/100")
    c3.metric("Label", row["Label"])
    c4.metric("52W High", row["52W High"])
    c5.metric("vs 52W High", row["vs 52W High"])
    c6.metric("RS vs SPY", row["RS vs SPY"])

    if fund:
        f1, f2, f3, f4, f5 = st.columns(5)
        f1.metric("🎯 Target", f"${fund['target']:.2f}" if fund.get('target') else "N/A")
        f2.metric("📈 Upside", f"{fund['upside']}%" if fund.get('upside') else "N/A")
        f3.metric("💰 Rev Growth", f"{round(fund['rev_growth']*100,1)}%" if fund.get('rev_growth') else "N/A")
        f4.metric("📉 Fwd PE", f"{round(fund['forward_pe'],1)}" if fund.get('forward_pe') else "N/A")
        f5.metric("💵 Margin", f"{round(fund['profit_margin']*100,1)}%" if fund.get('profit_margin') else "N/A")

        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("💚 Strong Buy", fund.get('strong_buy', 0))
        a2.metric("🟢 Buy", fund.get('buy', 0))
        a3.metric("🟡 Hold", fund.get('hold', 0))
        a4.metric("🔴 Sell", fund.get('sell', 0))
        a5.metric("❌ Strong Sell", fund.get('strong_sell', 0))

    df = stock_data[selected]
    close = df["Close"].squeeze()
    vol = df["Volume"].squeeze()
    supports, resistances = get_support_resistance(close.iloc[-252:])

    timeframe = st.radio("Timeframe", ["1M","3M","6M","YTD","1Y","5Y"], horizontal=True, index=4)
    now = pd.Timestamp.now()
    if timeframe == "1M": df_plot = df[df.index >= now - pd.DateOffset(months=1)]
    elif timeframe == "3M": df_plot = df[df.index >= now - pd.DateOffset(months=3)]
    elif timeframe == "6M": df_plot = df[df.index >= now - pd.DateOffset(months=6)]
    elif timeframe == "YTD": df_plot = df[df.index >= pd.Timestamp(now.year, 1, 1)]
    elif timeframe == "1Y": df_plot = df[df.index >= now - pd.DateOffset(years=1)]
    else: df_plot = df

    close_plot = df_plot["Close"].squeeze()
    vol_plot = df_plot["Volume"].squeeze()

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot["Open"].squeeze(), high=df_plot["High"].squeeze(), low=df_plot["Low"].squeeze(), close=close_plot, name="Price", increasing_line_color="lime", decreasing_line_color="red"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(50).mean(), name="50MA", line=dict(color="dodgerblue", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(150).mean(), name="150MA", line=dict(color="orange", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(200).mean(), name="200MA", line=dict(color="red", width=1.5)), row=1, col=1)
    colors = ["lime" if i == 0 or float(vol_plot.iloc[i]) >= float(vol_plot.iloc[i-1]) else "red" for i in range(len(vol_plot))]
    fig.add_trace(go.Bar(x=df_plot.index, y=vol_plot, name="Volume", marker_color=colors, opacity=0.5), row=2, col=1)
    for s in supports:
        fig.add_hline(y=s, line_dash="dash", line_color="lime", opacity=0.4, annotation_text=f"S ${s}", row=1, col=1)
    for r in resistances:
        fig.add_hline(y=r, line_dash="dash", line_color="tomato", opacity=0.4, annotation_text=f"R ${r}", row=1, col=1)
    if fund and fund.get('target'):
        fig.add_hline(y=fund['target'], line_dash="dot", line_color="gold", opacity=0.8, annotation_text=f"🎯 ${fund['target']:.2f}", row=1, col=1)
    fig.update_layout(
        template="plotly_dark",
        title=f"{selected} — {timeframe}",
        xaxis_rangeslider_visible=False,
        height=600,
        margin=dict(l=0, r=0, t=40, b=0),
        dragmode="drawline",
        newshape=dict(line_color="yellow"),
        modebar_add=["drawline", "drawopenpath", "drawrect", "eraseshape"]
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="#2a2a2a")
    st.plotly_chart(fig, use_container_width=True)

    sr1, sr2 = st.columns(2)
    sr1.markdown("**🟢 Support**")
    for s in supports: sr1.markdown(f"• ${s}")
    sr2.markdown("**🔴 Resistance**")
    for r in resistances: sr2.markdown(f"• ${r}")

with tab3:
    selected_rev = st.selectbox("Select stock", df_results["Ticker"].tolist(), key="rev_select")
    actuals, estimates = get_fmp_financials(selected_rev)

    if actuals and len(actuals) > 0:
        rev_data = []
        for item in reversed(actuals):
            rev_data.append({
                "Year": item.get("calendarYear", ""),
                "Revenue ($M)": round(item.get("revenue", 0)/1e6, 1),
                "EPS": round(item.get("eps", 0), 2),
                "Net Income ($M)": round(item.get("netIncome", 0)/1e6, 1),
                "Gross Profit ($M)": round(item.get("grossProfit", 0)/1e6, 1),
                "Operating Income ($M)": round(item.get("operatingIncome", 0)/1e6, 1),
            })
        df_rev = pd.DataFrame(rev_data)
        st.markdown("#### 📊 Actual Financials (Last 5 Years)")
        st.dataframe(df_rev, use_container_width=True)
        fig_rev = go.Figure()
        fig_rev.add_trace(go.Bar(x=df_rev["Year"], y=df_rev["Revenue ($M)"], name="Revenue", marker_color="dodgerblue"))
        fig_rev.add_trace(go.Scatter(x=df_rev["Year"], y=df_rev["EPS"], name="EPS", yaxis="y2", line=dict(color="gold", width=2)))
        fig_rev.update_layout(template="plotly_dark", title="Revenue & EPS",
            yaxis=dict(title="Revenue ($M)"),
            yaxis2=dict(title="EPS", overlaying="y", side="right"), height=350)
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("Add FMP_API_KEY to Streamlit secrets to unlock full Revenue & EPS data.")
        fund2 = get_fundamentals(selected_rev)
        if fund2:
            st.markdown("#### Available from yfinance:")
            col1, col2, col3 = st.columns(3)
            col1.metric("Rev Growth (YoY)", f"{round(fund2['rev_growth']*100,1)}%" if fund2.get('rev_growth') else "N/A")
            col2.metric("Trailing EPS", f"${fund2.get('eps_trailing', 'N/A')}")
            col3.metric("Forward EPS", f"${fund2.get('eps_forward', 'N/A')}")

    if estimates and len(estimates) > 0:
        est_data = []
        for item in estimates[:3]:
            est_data.append({
                "Year": item.get("date", "")[:4],
                "Est Revenue ($M)": round(item.get("estimatedRevenueAvg", 0)/1e6, 1),
                "Est EPS": round(item.get("estimatedEpsAvg", 0), 2),
            })
        df_est = pd.DataFrame(est_data)
        st.markdown("#### 🔮 Estimated Financials (Next 3 Years)")
        st.dataframe(df_est, use_container_width=True)

with tab4:
    macro = get_macro()
    st.markdown("### 🌍 Macro Dashboard")
    if fg_score:
        fg_color = "🟢" if fg_score >= 60 else "🟡" if fg_score >= 40 else "🔴"
        st.metric(f"{fg_color} Fear & Greed Index", f"{fg_score} — {fg_label}")
    st.divider()
    macro_items = list(macro.items())
    for j in range(0, len(macro_items), 4):
        cols = st.columns(4)
        for k, (name, data) in enumerate(macro_items[j:j+4]):
            val = data["value"]
            chg = data["change"]
            label = name + " (proxy)" if "Treasury" in name else name
            cols[k].metric(label, f"{val}%" if "Treasury" in name else str(val), delta=f"{chg:+.2f}")

with tab5:
    selected_news = st.selectbox("Select stock", df_results["Ticker"].tolist(), key="news_select")
    news = get_stock_news(selected_news)
    if news:
        for item in news:
            st.markdown(f"• [{item['title']}]({item['link']})  \n<small>{item['published']}</small>", unsafe_allow_html=True)
    else:
        st.info("No news found.")
    st.divider()
    st.markdown("#### 🌐 Global Macro News")
    for source, url in [("Reuters", "https://feeds.reuters.com/reuters/businessNews")]:
        try:
            feed = feedparser.parse(url)
            st.markdown(f"**{source}**")
            for entry in feed.entries[:4]:
                st.markdown(f"• [{entry.title}]({entry.link})")
        except:
            pass
