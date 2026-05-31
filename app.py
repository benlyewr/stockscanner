import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import feedparser
import numpy as np
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock Scanner V2", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1rem !important; color: white !important; }
[data-testid="stMetricLabel"] { font-size: 0.65rem !important; color: #cccccc !important; }
[data-testid="stMetric"] { background: #1a1a2e; border-radius: 8px; padding: 8px 12px; border: 1px solid #2a2a3e; }
.stTabs [data-baseweb="tab"] p {
    color: black !important;
    font-size: 0.85rem;
    font-weight: 600;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] p {
    color: #2563eb !important;
    font-weight: 700;
}
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
@media (max-width: 768px) {
    [data-testid="stMetricValue"] { font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.6rem !important; }
    .stTabs [data-baseweb="tab"] p { font-size: 0.75rem; }
}
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
    "RCL", "MRVL", "TSLA", "ARM", "ADBE"
]

def get_label(score):
    if score >= 90: return "🟢 Elite"
    elif score >= 80: return "🟩 Strong"
    elif score >= 65: return "🟨 Watchlist"
    elif score >= 50: return "🟧 Early"
    else: return "🔴 Ignore"

def fmt_cap(val):
    if not val: return "N/A"
    if val >= 1e12: return f"${val/1e12:.2f}T"
    if val >= 1e9: return f"${val/1e9:.1f}B"
    if val >= 1e6: return f"${val/1e6:.1f}M"
    return f"${val:,.0f}"

def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

@st.cache_data(ttl=3600)
def get_stock_data(ticker):
    try:
        df = yf.download(ticker, period="5y", auto_adjust=True, progress=False, threads=False)
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
    spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False, threads=False)
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
            df = yf.download(sym, period="5d", auto_adjust=True, progress=False, threads=False)
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
            "eps_trailing": info.get("trailingEps"),
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "held_percent_institutions": info.get("heldPercentInstitutions"),
            "held_percent_insiders": info.get("heldPercentInsiders"),
            "float_shares": info.get("floatShares"),
        }
    except:
        return {}

@st.cache_data(ttl=3600)
def get_institutional_holders(ticker):
    try:
        stock = yf.Ticker(ticker)
        holders_list = []

        try:
            inst = stock.institutional_holders
            if inst is not None and not inst.empty:
                inst = inst.head(10).copy()
                cols_to_keep = []
                for col in inst.columns:
                    col_lower = str(col).lower()
                    if any(k in col_lower for k in ["holder", "shares", "pct", "%", "value", "date"]):
                        cols_to_keep.append(col)
                if cols_to_keep:
                    inst = inst[cols_to_keep]
                inst["Type"] = "Institution"
                holders_list.append(inst)
        except:
            pass

        try:
            mutual = stock.mutualfund_holders
            if mutual is not None and not mutual.empty:
                mutual = mutual.head(5).copy()
                cols_to_keep = []
                for col in mutual.columns:
                    col_lower = str(col).lower()
                    if any(k in col_lower for k in ["holder", "shares", "pct", "%", "value", "date"]):
                        cols_to_keep.append(col)
                if cols_to_keep:
                    mutual = mutual[cols_to_keep]
                mutual["Type"] = "Mutual Fund"
                holders_list.append(mutual)
        except:
            pass

        if holders_list:
            combined = pd.concat(holders_list, ignore_index=True)
            return combined
        return None
    except:
        return None

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
                if prices[-1] > p2:
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
            ma50_slope = float(close_1y.rolling(50).mean().iloc[-1]) - float(close_1y.rolling(50).mean().iloc[-6])
            ma200_slope = float(close_1y.rolling(200).mean().iloc[-1]) - float(close_1y.rolling(200).mean().iloc[-10])
            stock_return = float(close_1y.iloc[-1]) / float(close_1y.iloc[0]) - 1
            rs = round((stock_return - spy_return) * 100, 1)
            reversal_123 = detect_123_reversal(close_1y)
            rsi_series = calculate_rsi(close_1y).dropna()
            current_rsi = round(float(rsi_series.iloc[-1]), 1) if not rsi_series.empty else 50
            avg_vol_50 = float(vol.rolling(50).mean().iloc[-1])
            volume_ratio = round(float(vol.iloc[-1]) / avg_vol_50, 2) if avg_vol_50 and avg_vol_50 > 0 else 0

            if current_rsi >= 80: rsi_status = "‼️ Extremely Overbought"
            elif current_rsi >= 70: rsi_status = "⚠️ Overbought"
            elif current_rsi <= 20: rsi_status = "‼️ Extremely Oversold"
            elif current_rsi <= 30: rsi_status = "⚠️ Oversold"
            else: rsi_status = "✅ Neutral"

            if volume_ratio >= 5: volume_status = "‼️ Climax Volume"
            elif volume_ratio >= 3: volume_status = "⚠️ Very High Volume"
            elif volume_ratio >= 1.5: volume_status = "✅ Above Average"
            else: volume_status = "Normal"

            if pct_from_200 >= 50: extension_status = "‼️ Very Extended vs 200MA"
            elif pct_from_200 >= 30: extension_status = "⚠️ Extended vs 200MA"
            elif pct_from_200 <= -30: extension_status = "⚠️ Washed Out vs 200MA"
            else: extension_status = "✅ Normal vs 200MA"

            if pct_from_high >= -5: high_status = "Near 52W High"
            elif pct_from_high <= -40: high_status = "⚠️ Deeply Below 52W High"
            else: high_status = "Normal"

            fund = get_fundamentals(ticker)
            rev_growth = fund.get("rev_growth")
            earnings_growth = fund.get("earnings_growth")
            profit_margin = fund.get("profit_margin")
            forward_pe = fund.get("forward_pe")

            score = 0
            scoring_breakdown = []

            if ma50 > ma150 > ma200 and price > ma50:
                score += 15
                scoring_breakdown.append(("Trend Template", 15, "50MA > 150MA > 200MA and price above 50MA"))
            else:
                scoring_breakdown.append(("Trend Template", 0, "Trend template not fully confirmed"))

            if ma50_slope > 0 and ma200_slope > 0:
                score += 10
                scoring_breakdown.append(("MA Slope", 10, "50MA and 200MA are both rising"))
            else:
                scoring_breakdown.append(("MA Slope", 0, "MA slopes not both rising"))

            if reversal_123:
                score += 15
                scoring_breakdown.append(("1-2-3 Reversal", 15, "1-2-3 reversal confirmed"))
            else:
                scoring_breakdown.append(("1-2-3 Reversal", 0, "1-2-3 reversal not confirmed"))

            if rs > 20:
                score += 15
                scoring_breakdown.append(("Relative Strength", 15, "Outperforming SPY by >20%"))
            elif rs > 10:
                score += 10
                scoring_breakdown.append(("Relative Strength", 10, "Outperforming SPY by >10%"))
            elif rs > 0:
                score += 5
                scoring_breakdown.append(("Relative Strength", 5, "Outperforming SPY slightly"))
            else:
                scoring_breakdown.append(("Relative Strength", 0, "Underperforming SPY"))

            if rev_growth and rev_growth > 0.20:
                score += 10
                scoring_breakdown.append(("Revenue Growth", 10, "Revenue growth above 20%"))
            elif rev_growth and rev_growth > 0.10:
                score += 5
                scoring_breakdown.append(("Revenue Growth", 5, "Revenue growth above 10%"))
            else:
                scoring_breakdown.append(("Revenue Growth", 0, "Below threshold or unavailable"))

            if earnings_growth and earnings_growth > 0.20:
                score += 10
                scoring_breakdown.append(("Earnings Growth", 10, "Earnings growth above 20%"))
            elif earnings_growth and earnings_growth > 0.10:
                score += 5
                scoring_breakdown.append(("Earnings Growth", 5, "Earnings growth above 10%"))
            else:
                scoring_breakdown.append(("Earnings Growth", 0, "Below threshold or unavailable"))

            if profit_margin and profit_margin > 0.10:
                score += 5
                scoring_breakdown.append(("Profit Margin", 5, "Profit margin above 10%"))
            else:
                scoring_breakdown.append(("Profit Margin", 0, "Below 10% or unavailable"))

            if forward_pe and 0 < forward_pe < 25:
                score += 10
                scoring_breakdown.append(("Valuation", 10, "Forward PE below 25"))
            elif forward_pe and 25 <= forward_pe < 40:
                score += 5
                scoring_breakdown.append(("Valuation", 5, "Forward PE between 25-40"))
            else:
                scoring_breakdown.append(("Valuation", 0, "PE too high or unavailable"))

            if 50 <= current_rsi <= 70:
                score += 5
                scoring_breakdown.append(("RSI Quality", 5, "RSI in healthy zone 50-70"))
            elif current_rsi >= 80:
                score -= 10
                scoring_breakdown.append(("RSI Warning", -10, "Extremely overbought RSI >= 80"))
            elif current_rsi >= 70:
                score -= 5
                scoring_breakdown.append(("RSI Warning", -5, "Overbought RSI >= 70"))
            elif current_rsi <= 30:
                score -= 5
                scoring_breakdown.append(("RSI Warning", -5, "Oversold RSI <= 30"))
            else:
                scoring_breakdown.append(("RSI Quality", 0, "RSI neutral"))

            if pct_from_200 >= 50:
                score -= 10
                scoring_breakdown.append(("Extension Warning", -10, "Price >50% above 200MA"))
            elif pct_from_200 >= 30:
                score -= 5
                scoring_breakdown.append(("Extension Warning", -5, "Price >30% above 200MA"))
            else:
                scoring_breakdown.append(("Extension Warning", 0, "Not excessively extended"))

            if volume_ratio >= 1.5 and volume_ratio < 5:
                score += 5
                scoring_breakdown.append(("Volume", 5, "Volume above 1.5x average"))
            elif volume_ratio >= 5:
                score -= 5
                scoring_breakdown.append(("Volume", -5, "Possible climax volume >5x"))
            else:
                scoring_breakdown.append(("Volume", 0, "Normal volume"))

            if fg_score and fg_score >= 75:
                score -= 5
                scoring_breakdown.append(("Market Sentiment", -5, "Fear & Greed is high"))
            else:
                scoring_breakdown.append(("Market Sentiment", 0, "No sentiment penalty"))

            score = max(0, min(score, 100))

            results.append({
                "Ticker": ticker,
                "Price": f"${price:.2f}",
                "Score": score,
                "Label": get_label(score),
                "Mkt Cap": fmt_cap(fund.get("market_cap")),
                "RSI": current_rsi,
                "RSI Status": rsi_status,
                "Vol Ratio": volume_ratio,
                "Vol Status": volume_status,
                "Extension": extension_status,
                "52W Status": high_status,
                "50MA": f"${ma50:.2f}",
                "200MA": f"${ma200:.2f}",
                "52W High": f"${high52:.2f}",
                "52W Low": f"${low52:.2f}",
                "vs 50MA": f"{pct_from_50}%",
                "vs 200MA": f"{pct_from_200}%",
                "vs 52W High": f"{pct_from_high}%",
                "RS vs SPY": f"{rs}%",
                "123 Rev": "✅" if reversal_123 else "❌",
                "_price_raw": price,
                "_rs_raw": rs,
                "_rev_growth_raw": rev_growth,
                "_rsi_raw": current_rsi,
                "_ma50_slope": ma50_slope,
                "_ma200_slope": ma200_slope,
                "_fund": fund,
                "_scoring_breakdown": scoring_breakdown
            })
            stock_data[ticker] = df
        except Exception as e:
            skipped.append(ticker)
        progress.progress((i+1)/len(tickers))
    progress.empty()

if not results:
    st.error("No stocks loaded. Please refresh or check Yahoo Finance data.")
    st.stop()

df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

if skipped:
    st.warning(f"Could not load: {', '.join(skipped)}")

tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(["⚡ Quick Scan", "📊 Scanner", "📈 Chart", "💰 Revenue & EPS", "🌍 Macro", "📰 News"])

with tab0:
    st.markdown("### ⚡ Quick Scan — Daily Watchlist")
    st.caption("Score ≥ 80 | RSI 50–75 | Rev Growth > 10% | RS vs SPY > 10%")

    quick = df_results[
        (df_results["Score"] >= 80) &
        (df_results["_rsi_raw"] >= 50) &
        (df_results["_rsi_raw"] <= 75) &
        (df_results["_rs_raw"] > 10) &
        (df_results["_rev_growth_raw"].apply(lambda x: x > 0.10 if x else False))
    ].sort_values("Score", ascending=False)

    if quick.empty:
        st.info("No stocks meet all Quick Scan criteria today. Check the full Scanner tab.")
    else:
        st.success(f"✅ {len(quick)} stocks meet all criteria today!")
        for _, qrow in quick.iterrows():
            with st.expander(f"{qrow['Ticker']} — {qrow['Label']} — Score {qrow['Score']}"):
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Price", qrow["Price"])
                q2.metric("RSI", qrow["RSI"])
                q3.metric("RS vs SPY", qrow["RS vs SPY"])
                q4.metric("Mkt Cap", qrow["Mkt Cap"])
                qf = qrow["_fund"]
                if qf:
                    qf1, qf2, qf3 = st.columns(3)
                    qf1.metric("Rev Growth", f"{round(qf['rev_growth']*100,1)}%" if qf.get('rev_growth') else "N/A")
                    qf2.metric("Target", f"${qf['target']:.2f}" if qf.get('target') else "N/A")
                    qf3.metric("Upside", f"{qf['upside']}%" if qf.get('upside') else "N/A")

with tab1:
    def color_score(val):
        if val >= 90: return "background-color: #004d00; color: white; font-weight: bold"
        elif val >= 80: return "background-color: #008000; color: white; font-weight: bold"
        elif val >= 65: return "background-color: #1a5c1a; color: white"
        elif val >= 50: return "background-color: #5c5c1a; color: white"
        else: return "background-color: #3d0000; color: white"

    display_cols = ["Ticker","Price","Mkt Cap","Score","Label","RSI","RSI Status","50MA","200MA","vs 50MA","vs 200MA","vs 52W High","RS vs SPY","123 Rev","Vol Ratio","Vol Status","Extension","52W Status"]
    styled = df_results[display_cols].style.map(color_score, subset=["Score"])
    st.dataframe(styled, use_container_width=True, height=500)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🟢 Elite", len(df_results[df_results["Score"] >= 90]))
    c2.metric("🟩 Strong", len(df_results[(df_results["Score"] >= 80) & (df_results["Score"] < 90)]))
    c3.metric("🟨 Watchlist", len(df_results[(df_results["Score"] >= 65) & (df_results["Score"] < 80)]))
    c4.metric("🟧 Early", len(df_results[(df_results["Score"] >= 50) & (df_results["Score"] < 65)]))
    c5.metric("🔴 Ignore", len(df_results[df_results["Score"] < 50]))

with tab2:
    selected = st.selectbox("🔍 Search stock", df_results["Ticker"].tolist())
    row = df_results[df_results["Ticker"] == selected].iloc[0]
    fund = row["_fund"]

    warnings = []
    if "Overbought" in row["RSI Status"]: warnings.append(row["RSI Status"])
    if "Oversold" in row["RSI Status"]: warnings.append(row["RSI Status"])
    if "Extended" in row["Extension"]: warnings.append(row["Extension"])
    if "Climax" in row["Vol Status"]: warnings.append(row["Vol Status"])
    if warnings:
        st.warning(" | ".join(warnings))
    else:
        st.success("✅ No major overbought/oversold warnings")

    st.markdown(f"### {selected} — {row['Label']}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", row["Price"])
    c2.metric("Score", f"{int(row['Score'])}/100")
    c3.metric("RSI", row["RSI"])
    c4.metric("Mkt Cap", row["Mkt Cap"])

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("52W High", row["52W High"])
    c6.metric("vs 52W High", row["vs 52W High"])
    c7.metric("RS vs SPY", row["RS vs SPY"])
    c8.metric("RSI Status", row["RSI Status"])

    if fund:
        st.markdown("---")
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("🎯 Target", f"${fund['target']:.2f}" if fund.get('target') else "N/A")
        d2.metric("📈 Upside", f"{fund['upside']}%" if fund.get('upside') else "N/A")
        d3.metric("💰 Rev Growth", f"{round(fund['rev_growth']*100,1)}%" if fund.get('rev_growth') else "N/A")
        d4.metric("📉 Fwd PE", f"{round(fund['forward_pe'],1)}" if fund.get('forward_pe') else "N/A")

        d5, d6, d7, d8 = st.columns(4)
        d5.metric("💵 Margin", f"{round(fund['profit_margin']*100,1)}%" if fund.get('profit_margin') else "N/A")
        d6.metric("💚 Str Buy", fund.get('strong_buy', 0))
        d7.metric("🟢 Buy", fund.get('buy', 0))
        d8.metric("🟡 Hold", fund.get('hold', 0))

    st.markdown("---")
    st.markdown("### 🧮 Score Breakdown")
    breakdown_df = pd.DataFrame(row["_scoring_breakdown"], columns=["Category", "Points", "Reason"])
    positive_points = breakdown_df[breakdown_df["Points"] > 0]["Points"].sum()
    negative_points = breakdown_df[breakdown_df["Points"] < 0]["Points"].sum()

    b1, b2, b3 = st.columns(3)
    b1.metric("✅ Positive Points", int(positive_points))
    b2.metric("❌ Penalties", int(negative_points))
    b3.metric("🎯 Final Score", f"{int(row['Score'])}/100")

    for _, brow in breakdown_df.iterrows():
        pts = brow["Points"]
        if pts > 0:
            bg_color = "#166534"
            icon = "✅"
        elif pts < 0:
            bg_color = "#991B1B"
            icon = "❌"
        else:
            bg_color = "#374151"
            icon = "➖"
        st.markdown(f"""
        <div style="background:{bg_color};color:#FFFFFF;padding:10px 14px;border-radius:8px;margin-bottom:4px;font-weight:600;display:flex;justify-content:space-between;align-items:center;">
            <span>{icon} {brow['Category']}</span>
            <span>{'+' if pts > 0 else ''}{pts}</span>
        </div>
        <div style="padding:2px 14px 10px;color:#9CA3AF;font-size:0.8rem;">{brow['Reason']}</div>
        """, unsafe_allow_html=True)

    df = stock_data[selected]
    close = df["Close"].squeeze()
    vol = df["Volume"].squeeze()
    supports, resistances = get_support_resistance(close.iloc[-252:])

    st.markdown("---")
    st.markdown("### 📌 Chart Levels")

    lvl1, lvl2, lvl3, lvl4 = st.columns(4)
    lvl1.metric("Current Price", row["Price"])
    lvl2.metric("Target", f"${fund['target']:.2f}" if fund and fund.get("target") else "N/A")
    lvl3.metric("Support 1", f"${supports[0]}" if len(supports) > 0 else "N/A")
    lvl4.metric("Resistance 1", f"${resistances[0]}" if len(resistances) > 0 else "N/A")

    lvl5, lvl6, lvl7, lvl8 = st.columns(4)
    lvl5.metric("Support 2", f"${supports[1]}" if len(supports) > 1 else "N/A")
    lvl6.metric("Support 3", f"${supports[2]}" if len(supports) > 2 else "N/A")
    lvl7.metric("Resistance 2", f"${resistances[1]}" if len(resistances) > 1 else "N/A")
    lvl8.metric("Resistance 3", f"${resistances[2]}" if len(resistances) > 2 else "N/A")

    vol_cols = st.columns(3)
    latest_volume = int(vol.iloc[-1])
    avg_volume_50 = int(vol.rolling(50).mean().iloc[-1])
    vol_cols[0].metric("Volume Ratio", row["Vol Ratio"])
    vol_cols[1].metric("Latest Volume", f"{latest_volume:,}")
    vol_cols[2].metric("50D Avg Volume", f"{avg_volume_50:,}")

    st.markdown("---")
    show_sr = st.checkbox("Show Support/Resistance", value=True)
    show_target = st.checkbox("Show Analyst Target", value=True)
    show_volume = st.checkbox("Show Volume", value=True)

    try:
        timeframe = st.segmented_control("Timeframe", ["1M","3M","6M","YTD","1Y","5Y"], default="1Y")
    except:
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
    chart_supports = supports[:2]
    chart_resistances = resistances[:2]

    rows_count = 2 if show_volume else 1
    row_heights = [0.78, 0.22] if show_volume else [1.0]

    fig = make_subplots(rows=rows_count, cols=1, shared_xaxes=True, row_heights=row_heights, vertical_spacing=0.01)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot, name="Price", line=dict(color="white", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(50).mean(), name="50MA", line=dict(color="dodgerblue", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(200).mean(), name="200MA", line=dict(color="red", width=1.5)), row=1, col=1)

    if show_volume:
        colors = ["lime" if i == 0 or float(vol_plot.iloc[i]) >= float(vol_plot.iloc[i-1]) else "red" for i in range(len(vol_plot))]
        fig.add_trace(go.Bar(x=df_plot.index, y=vol_plot, name="Volume", marker_color=colors, opacity=0.4), row=2, col=1)

    label_x = df_plot.index[-1]

    if show_sr:
        used_y_positions = []
        for i, s in enumerate(chart_supports):
            adj_y = float(s)
            for used_y in used_y_positions:
                if abs(adj_y - used_y) / max(abs(used_y), 0.001) < 0.015:
                    adj_y = adj_y * (1 - 0.015 * (i + 1))
            used_y_positions.append(adj_y)
            fig.add_hline(y=float(s), line_dash="dash", line_color="lime", opacity=0.35, row=1, col=1)
            fig.add_annotation(
                x=label_x, y=adj_y,
                text=f"S{i+1}: ${s}",
                showarrow=False, xanchor="left", yanchor="middle",
                bgcolor="rgba(0,160,0,0.75)",
                font=dict(color="white", size=11),
                borderpad=3
            )

        used_y_positions_r = []
        for i, r in enumerate(chart_resistances):
            adj_y = float(r)
            for used_y in used_y_positions_r:
                if abs(adj_y - used_y) / max(abs(used_y), 0.001) < 0.015:
                    adj_y = adj_y * (1 + 0.015 * (i + 1))
            used_y_positions_r.append(adj_y)
            fig.add_hline(y=float(r), line_dash="dash", line_color="tomato", opacity=0.35, row=1, col=1)
            fig.add_annotation(
                x=label_x, y=adj_y,
                text=f"R{i+1}: ${r}",
                showarrow=False, xanchor="left", yanchor="middle",
                bgcolor="rgba(200,50,50,0.75)",
                font=dict(color="white", size=11),
                borderpad=3
            )

    if show_target and fund and fund.get('target'):
        fig.add_hline(y=fund['target'], line_dash="dot", line_color="gold", opacity=0.8, row=1, col=1)
        fig.add_annotation(
            x=label_x, y=fund['target'],
            text=f"Target: ${fund['target']:.2f}",
            showarrow=False, xanchor="left", yanchor="middle",
            bgcolor="rgba(200,160,0,0.85)",
            font=dict(color="white", size=11),
            borderpad=3
        )

    fig.update_layout(
        template="plotly_dark",
        title=dict(text=f"{selected} — {timeframe}", font=dict(size=16, color="white")),
        xaxis_rangeslider_visible=False,
        height=580,
        margin=dict(l=5, r=100, t=40, b=5),
        legend=dict(orientation="h", y=1.05, x=0, font=dict(color="white")),
        dragmode="drawline",
        newshape=dict(line_color="yellow"),
        modebar_add=["drawline", "drawopenpath", "drawrect", "eraseshape"],
        plot_bgcolor="#0e0e1a",
        paper_bgcolor="#0e0e1a",
        font=dict(color="white")
    )
    fig.update_xaxes(showgrid=False, zeroline=False, color="white")
    fig.update_yaxes(showgrid=True, gridcolor="#1e1e2e", zeroline=False, color="white")
    st.plotly_chart(fig, use_container_width=True)

    if st.button("↩️ Clear All Drawings"):
        st.rerun()

    st.markdown("---")
    st.markdown("### 🏦 Institutional Ownership")

    own1, own2, own3, own4 = st.columns(4)
    own1.metric("Institution Held", f"{fund.get('held_percent_institutions')*100:.1f}%" if fund and fund.get('held_percent_institutions') else "N/A")
    own2.metric("Insider Held", f"{fund.get('held_percent_insiders')*100:.1f}%" if fund and fund.get('held_percent_insiders') else "N/A")
    own3.metric("Shares Out", f"{fund.get('shares_outstanding'):,}" if fund and fund.get('shares_outstanding') else "N/A")
    own4.metric("Float Shares", f"{fund.get('float_shares'):,}" if fund and fund.get('float_shares') else "N/A")

    inst_data = get_institutional_holders(selected)
    if inst_data is not None and not inst_data.empty:
        st.dataframe(inst_data, use_container_width=True)
    else:
        st.info("No detailed holder data available from Yahoo Finance for this ticker.")
    st.caption("Data sourced from Yahoo Finance. May be delayed or unavailable for some tickers.")

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
                "Op Income ($M)": round(item.get("operatingIncome", 0)/1e6, 1),
            })
        df_rev = pd.DataFrame(rev_data)
        st.markdown("#### 📊 Actual Financials (Last 5 Years)")
        st.dataframe(df_rev, use_container_width=True)
        fig_rev = go.Figure()
        fig_rev.add_trace(go.Bar(x=df_rev["Year"], y=df_rev["Revenue ($M)"], name="Revenue", marker_color="dodgerblue"))
        fig_rev.add_trace(go.Scatter(x=df_rev["Year"], y=df_rev["EPS"], name="EPS", yaxis="y2", line=dict(color="gold", width=2)))
        fig_rev.update_layout(template="plotly_dark", title="Revenue & EPS",
            yaxis=dict(title="Revenue ($M)", color="white"),
            yaxis2=dict(title="EPS", overlaying="y", side="right", color="white"),
            height=350, paper_bgcolor="#0e0e1a", plot_bgcolor="#0e0e1a", font=dict(color="white"))
        st.plotly_chart(fig_rev, use_container_width=True)
    else:
        st.info("Add FMP_API_KEY to Streamlit secrets for full Revenue & EPS data.")
        fund2 = get_fundamentals(selected_rev)
        if fund2:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Rev Growth YoY", f"{round(fund2['rev_growth']*100,1)}%" if fund2.get('rev_growth') else "N/A")
            col2.metric("Trailing EPS", f"${fund2.get('eps_trailing', 'N/A')}")
            col3.metric("Forward EPS", f"${fund2.get('eps_forward', 'N/A')}")
            col4.metric("Profit Margin", f"{round(fund2['profit_margin']*100,1)}%" if fund2.get('profit_margin') else "N/A")

    if estimates and len(estimates) > 0:
        est_data = [{"Year": item.get("date","")[:4], "Est Rev ($M)": round(item.get("estimatedRevenueAvg",0)/1e6,1), "Est EPS": round(item.get("estimatedEpsAvg",0),2)} for item in estimates[:3]]
        st.markdown("#### 🔮 Estimates (Next 3 Years)")
        st.dataframe(pd.DataFrame(est_data), use_container_width=True)

with tab4:
    macro = get_macro()
    st.markdown("### 🌍 Macro Dashboard")
    if fg_score:
        fg_color = "🟢" if fg_score >= 60 else "🟡" if fg_score >= 40 else "🔴"
        st.metric(f"{fg_color} Fear & Greed", f"{fg_score} — {fg_label}")
    st.markdown("---")
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
    try:
        feed = feedparser.parse("https://feeds.reuters.com/reuters/businessNews")
        for entry in feed.entries[:5]:
            st.markdown(f"• [{entry.title}]({entry.link})")
    except:
        pass
