import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import feedparser
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Stock Scanner V2", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 1rem !important; color: white !important; }
[data-testid="stMetricLabel"] { font-size: 0.65rem !important; color: #cccccc !important; }
[data-testid="stMetric"] { background: #1a1a2e; border-radius: 8px; padding: 8px 12px; border: 1px solid #2a2a3e; }
.stTabs [data-baseweb="tab"] p { color: black !important; font-size: 0.85rem; font-weight: 600; }
.stTabs [data-baseweb="tab"][aria-selected="true"] p { color: #2563eb !important; font-weight: 700; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
@media (max-width: 768px) {
    [data-testid="stMetricValue"] { font-size: 0.85rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.6rem !important; }
    .stTabs [data-baseweb="tab"] p { font-size: 0.75rem; }
}
</style>
""", unsafe_allow_html=True)

st.markdown("## 📈 Stock Scanner V2")

# FIX: st.secrets crashes the entire app if no secrets.toml file exists.
# Wrapped so the app runs with or without secrets configured.
try:
    FMP_API_KEY = st.secrets.get("FMP_API_KEY", None)
except Exception:
    FMP_API_KEY = None

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

# ---------- helpers ----------

# Compatibility: use_container_width is deprecated in new Streamlit and the
# replacement width="stretch" doesn't exist in old Streamlit. Support both.
def show_df(data, **kw):
    try:
        st.dataframe(data, width="stretch", **kw)
    except TypeError:
        st.dataframe(data, use_container_width=True, **kw)

def show_chart(fig, key=None):
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key=key)


def safe_num(x, default=None):
    """Return a clean float or default. Protects against None/NaN crashes."""
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default

def fmt_int(x):
    v = safe_num(x)
    return f"{int(v):,}" if v is not None else "N/A"

def fmt_price(x):
    v = safe_num(x)
    return f"${v:.2f}" if v is not None else "N/A"

def get_label(score):
    if score >= 90: return "🟢 Elite"
    elif score >= 80: return "🟩 Strong"
    elif score >= 65: return "🟨 Watchlist"
    elif score >= 50: return "🟧 Early"
    else: return "🔴 Ignore"

def get_verdict(overall, buy_score, risk_score):
    if overall >= 80 and buy_score >= 70 and risk_score <= 30:
        return "🟢 Strong Buy Setup"
    elif overall >= 65 and risk_score <= 40:
        return "🟨 Watchlist"
    elif risk_score >= 80:
        return "🔴 Avoid"
    elif risk_score >= 60:
        return "🟠 Elevated Risk"
    else:
        return "⬜ Neutral"

def get_buy_label(score):
    if score >= 80: return "🟢 Strong Buy Setup"
    elif score >= 60: return "🟩 Good Buy Setup"
    elif score >= 40: return "🟨 Watch Buy Setup"
    else: return "⬜ No Buy Setup"

def get_risk_label(score):
    if score >= 80: return "🔴 High Risk"
    elif score >= 60: return "🟠 Elevated Risk"
    elif score >= 40: return "🟡 Moderate Risk"
    else: return "🟢 Low Risk"

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
    return 100 - (100 / (1 + rs))

def get_buy_score(row_data, fund, fundamental_score=0):
    score = 0
    signals = []
    if row_data.get("_ma50_slope", 0) > 0:
        score += 15; signals.append("✅ 50MA slope rising")
    if row_data.get("_ma200_slope", 0) > 0:
        score += 10; signals.append("✅ 200MA slope rising")
    rsi = row_data.get("_rsi_raw", 50)
    if 50 <= rsi <= 70:
        score += 15; signals.append("✅ RSI in healthy zone 50-70")
    rs = row_data.get("_rs_raw", 0)
    if rs > 10:
        score += 20; signals.append(f"✅ Outperforming SPY by {rs:.1f}%")
    elif rs > 0:
        score += 10; signals.append(f"✅ Outperforming SPY by {rs:.1f}%")
    rev = row_data.get("_rev_growth_raw")
    if rev and rev > 0.20:
        score += 20; signals.append("✅ Revenue growth >20%")
    elif rev and rev > 0.10:
        score += 10; signals.append("✅ Revenue growth >10%")
    if fund:
        eg = fund.get("earnings_growth")
        if eg and eg > 0.20:
            score += 20; signals.append("✅ Earnings growth >20%")
        elif eg and eg > 0.10:
            score += 10; signals.append("✅ Earnings growth >10%")
    if fundamental_score >= 80:
        score += 20; signals.append("✅ Strong fundamental quality score")
    elif fundamental_score >= 60:
        score += 10; signals.append("✅ Good fundamental quality score")
    return min(score, 100), signals

def get_risk_score(row_data, fund, fundamental_score=0):
    score = 0
    signals = []
    rsi = row_data.get("_rsi_raw", 50)
    if rsi >= 80:
        score += 30; signals.append(f"⚠️ RSI extremely overbought ({rsi})")
    elif rsi >= 70:
        score += 15; signals.append(f"⚠️ RSI overbought ({rsi})")
    rs = row_data.get("_rs_raw", 0)
    if rs < -10:
        score += 25; signals.append(f"⚠️ Underperforming SPY by {abs(rs):.1f}%")
    elif rs < 0:
        score += 10; signals.append("⚠️ Underperforming SPY slightly")
    if row_data.get("_ma50_slope", 0) < 0:
        score += 20; signals.append("⚠️ 50MA slope falling")
    if row_data.get("_ma200_slope", 0) < 0:
        score += 15; signals.append("⚠️ 200MA slope falling")
    rev = row_data.get("_rev_growth_raw")
    if rev and rev < 0:
        score += 20; signals.append("⚠️ Revenue declining")
    if fund and fund.get("forward_pe") and fund["forward_pe"] > 60:
        score += 10; signals.append(f"⚠️ High forward PE ({fund['forward_pe']:.1f})")
    if fundamental_score < 40:
        score += 15; signals.append("⚠️ Weak fundamental quality score")
    return min(score, 100), signals

def get_fundamental_score(actuals, estimates):
    fundamental_score = 0
    fundamental_signals = []
    fundamental_warnings = []

    if not actuals or not isinstance(actuals, list) or len(actuals) < 2:
        return 0, [], ["⚠️ N/A — add FMP_API_KEY for full fundamental scoring"]

    try:
        revenues          = [item.get("revenue", 0)          for item in reversed(actuals)]
        gross_profits     = [item.get("grossProfit", 0)       for item in reversed(actuals)]
        operating_incomes = [item.get("operatingIncome", 0)   for item in reversed(actuals)]
        pretax_incomes    = [item.get("incomeBeforeTax", 0)   for item in reversed(actuals)]
        op_expenses       = [item.get("operatingExpenses", 0) for item in reversed(actuals)]
        cogs_list         = [item.get("costOfRevenue", 0)     for item in reversed(actuals)]

        if len(revenues) >= 3:
            if all(revenues[i] < revenues[i+1] for i in range(len(revenues)-1)):
                fundamental_score += 20
                fundamental_signals.append("✅ Revenue has increased year-on-year")
            else:
                fundamental_warnings.append("⚠️ Revenue not consistently increasing")

        if len(gross_profits) >= 3:
            if all(gross_profits[i] < gross_profits[i+1] for i in range(len(gross_profits)-1)):
                fundamental_score += 15
                fundamental_signals.append("✅ Gross profit increasing year-on-year")
            else:
                fundamental_warnings.append("⚠️ Gross profit not consistently increasing")

        if len(cogs_list) >= 2 and len(gross_profits) >= 2:
            if cogs_list[-1] > cogs_list[-2] and gross_profits[-1] > gross_profits[-2]:
                fundamental_score += 5
                fundamental_signals.append("✅ COGS rising alongside revenue and gross profit")
            elif cogs_list[-1] > cogs_list[-2] and gross_profits[-1] <= gross_profits[-2]:
                fundamental_warnings.append("⚠️ COGS rising while gross profit is weakening")

        if len(op_expenses) >= 2 and len(revenues) >= 2:
            opex_growth = (op_expenses[-1] - op_expenses[-2]) / max(abs(op_expenses[-2]), 1)
            rev_growth_rate = (revenues[-1] - revenues[-2]) / max(abs(revenues[-2]), 1)
            if op_expenses[-1] < op_expenses[-2]:
                fundamental_score += 10
                fundamental_signals.append("✅ Operating expenses declining — good cost control")
            elif opex_growth < rev_growth_rate:
                fundamental_score += 5
                fundamental_signals.append("✅ Operating expenses growing slower than revenue")
            else:
                fundamental_warnings.append("⚠️ Operating expenses growing faster than revenue")

        if len(operating_incomes) >= 2:
            if operating_incomes[-1] > operating_incomes[-2]:
                fundamental_score += 15
                fundamental_signals.append("✅ Operating income increasing — business becoming more profitable")
            else:
                fundamental_warnings.append("⚠️ Operating income declining")

        if len(pretax_incomes) >= 2:
            if pretax_incomes[-1] > pretax_incomes[-2]:
                fundamental_score += 10
                fundamental_signals.append("✅ Pre-tax income increasing")
            else:
                fundamental_warnings.append("⚠️ Pre-tax income declining")

        if estimates and len(estimates) > 0:
            try:
                est_rev = estimates[0].get("estimatedRevenueAvg", 0)
                actual_rev = actuals[0].get("revenue", 0)
                if est_rev and actual_rev:
                    beat_pct = (actual_rev - est_rev) / max(abs(est_rev), 1)
                    if beat_pct > 0.05:
                        fundamental_score += 25
                        fundamental_signals.append(f"✅ Strong revenue beat above estimate by {beat_pct*100:.1f}%")
                    elif beat_pct > 0:
                        fundamental_score += 15
                        fundamental_signals.append(f"✅ Actual revenue beat estimate by {beat_pct*100:.1f}%")
                    else:
                        fundamental_warnings.append(f"⚠️ Revenue missed estimate by {abs(beat_pct)*100:.1f}%")
            except Exception:
                pass

        if estimates and len(estimates) >= 2:
            try:
                fut_revs = [e.get("estimatedRevenueAvg", 0) for e in estimates]
                if all(fut_revs[i] < fut_revs[i+1] for i in range(len(fut_revs)-1)):
                    fundamental_score += 25
                    fundamental_signals.append("✅ Future revenue estimates are rising across upcoming periods")
                else:
                    fundamental_warnings.append("⚠️ Future revenue estimates are not consistently rising across upcoming periods")
            except Exception:
                pass

    except Exception as e:
        fundamental_warnings.append(f"⚠️ Could not fully calculate fundamentals: {str(e)[:50]}")

    return max(0, min(fundamental_score, 100)), fundamental_signals, fundamental_warnings

# ---------- data loaders ----------

def _clean_df(df):
    """Flatten MultiIndex columns, strip timezone, drop empty rows."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        # single-ticker frame like ('Close','AAPL') -> 'Close'
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    df = df.dropna(how="all")
    # FIX: batched downloads share one combined date index across all tickers,
    # so a ticker can end with NaN rows (no data yet for the newest dates).
    # Drop rows with no Close so iloc[-1] is always a real price.
    if "Close" in df.columns:
        df = df.dropna(subset=["Close"])
    return df if not df.empty and len(df) >= 50 else None

@st.cache_data(ttl=3600, show_spinner=False)
def get_all_stock_data(tickers_tuple):
    """FIX: one batched download for every ticker instead of 45 separate
    downloads — much faster and far less likely to be rate-limited by Yahoo."""
    out = {}
    try:
        data = yf.download(list(tickers_tuple), period="5y", auto_adjust=True,
                           progress=False, group_by="ticker", threads=True)
        if isinstance(data.columns, pd.MultiIndex):
            for t in tickers_tuple:
                try:
                    if t in data.columns.get_level_values(0):
                        df = _clean_df(data[t])
                        if df is not None:
                            out[t] = df
                except Exception:
                    pass
        else:
            # batch collapsed to a single frame (only one ticker succeeded)
            df = _clean_df(data)
            if df is not None and len(tickers_tuple) == 1:
                out[tickers_tuple[0]] = df
    except Exception:
        pass
    # fallback: retry missing tickers individually
    for t in tickers_tuple:
        if t in out:
            continue
        try:
            df = _clean_df(yf.download(t, period="5y", auto_adjust=True,
                                       progress=False, threads=False))
            if df is None:
                df = _clean_df(yf.Ticker(t).history(period="5y"))
            if df is not None:
                out[t] = df
        except Exception:
            pass
    return out

@st.cache_data(ttl=3600, show_spinner=False)
def get_fear_greed():
    """Returns (score, label, is_stock_index). Only the real stock-market
    Fear & Greed index is allowed to affect scoring."""
    try:
        import fear_and_greed
        data = fear_and_greed.get()
        return round(data.value), data.description, True
    except Exception:
        pass
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        d = r.json()["fear_and_greed"]
        return round(d["score"]), d["rating"], True
    except Exception:
        pass
    try:
        # FIX: alternative.me is the CRYPTO Fear & Greed index — keep only as a
        # clearly-labelled proxy and never let it change stock scores.
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        d = r.json()["data"][0]
        return int(d["value"]), d["value_classification"] + " (crypto proxy)", False
    except Exception:
        return None, None, False

@st.cache_data(ttl=3600, show_spinner=False)
def get_spy_return():
    """FIX: was uncached-error-fatal — a single failed SPY download killed the
    whole app. Now returns None on failure and the app degrades gracefully."""
    try:
        spy = _clean_df(yf.download("SPY", period="1y", auto_adjust=True,
                                    progress=False, threads=False))
        if spy is None:
            return None
        close = spy["Close"].squeeze().dropna()
        if len(close) < 2:
            return None
        return float(close.iloc[-1]) / float(close.iloc[0]) - 1
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_macro():
    macro = {}
    symbols = {
        "Oil": "CL=F", "Gold": "GC=F", "VIX": "^VIX", "USD": "DX-Y.NYB",
        "1Y Treasury": "^IRX", "10Y Treasury": "^TNX", "20Y Treasury": "^TYX"
    }
    for name, sym in symbols.items():
        try:
            df = yf.download(sym, period="5d", auto_adjust=True, progress=False, threads=False)
            close = df["Close"].squeeze().dropna()
            if len(close) >= 2:
                val = round(float(close.iloc[-1]), 2)
                prev = round(float(close.iloc[-2]), 2)
                macro[name] = {"value": val, "change": round(val - prev, 2)}
            elif len(close) == 1:
                macro[name] = {"value": round(float(close.iloc[-1]), 2), "change": 0}
            else:
                macro[name] = {"value": "N/A", "change": 0}
        except Exception:
            macro[name] = {"value": "N/A", "change": 0}
    return macro

def _fetch_fundamentals_one(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        strong_buy = buy = hold = sell = strong_sell = 0
        try:
            rec = stock.recommendations
            if rec is not None and not rec.empty:
                latest = rec.iloc[0] if "period" in rec.columns and str(rec.iloc[0].get("period")) == "0m" else rec.iloc[-1]
                strong_buy = int(latest.get("strongBuy", 0) or 0)
                buy        = int(latest.get("buy", 0) or 0)
                hold       = int(latest.get("hold", 0) or 0)
                sell       = int(latest.get("sell", 0) or 0)
                strong_sell= int(latest.get("strongSell", 0) or 0)
        except Exception:
            pass
        target  = safe_num(info.get("targetMeanPrice"))
        current = safe_num(info.get("currentPrice"))
        upside  = round((target - current) / current * 100, 1) if target and current else None
        return {
            "strong_buy": strong_buy, "buy": buy, "hold": hold,
            "sell": sell, "strong_sell": strong_sell,
            "target": target, "upside": upside,
            "rev_growth":       safe_num(info.get("revenueGrowth")),
            "earnings_growth":  safe_num(info.get("earningsGrowth")),
            "pe":               safe_num(info.get("trailingPE")),
            "forward_pe":       safe_num(info.get("forwardPE")),
            "profit_margin":    safe_num(info.get("profitMargins")),
            "eps_forward":      safe_num(info.get("forwardEps")),
            "eps_trailing":     safe_num(info.get("trailingEps")),
            "market_cap":       safe_num(info.get("marketCap")),
            "shares_outstanding":         safe_num(info.get("sharesOutstanding")),
            "held_percent_institutions":  safe_num(info.get("heldPercentInstitutions")),
            "held_percent_insiders":      safe_num(info.get("heldPercentInsiders")),
            "float_shares":               safe_num(info.get("floatShares")),
        }
    except Exception:
        return {}

@st.cache_data(ttl=3600, show_spinner=False)
def get_all_fundamentals(tickers_tuple):
    """FIX: fundamentals fetched in parallel (6 workers) instead of one slow
    sequential call per ticker. Each failure returns {} instead of breaking."""
    out = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_fundamentals_one, t): t for t in tickers_tuple}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception:
                out[t] = {}
    return out

@st.cache_data(ttl=3600, show_spinner=False)
def get_institutional_holders(ticker):
    try:
        stock = yf.Ticker(ticker)
        holders_list = []
        for attr, label in [("institutional_holders", "Institution"), ("mutualfund_holders", "Mutual Fund")]:
            try:
                df = getattr(stock, attr)
                if df is not None and not df.empty:
                    df = df.head(10 if label == "Institution" else 5).copy()
                    cols = [c for c in df.columns if any(k in str(c).lower() for k in ["holder","shares","pct","%","value","date"])]
                    if cols: df = df[cols]
                    df["Type"] = label
                    holders_list.append(df)
            except Exception:
                pass
        return pd.concat(holders_list, ignore_index=True).head(15) if holders_list else None
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_fmp_financials(ticker):
    if not FMP_API_KEY:
        return None, None
    try:
        r1 = requests.get(f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?limit=5&apikey={FMP_API_KEY}", timeout=15)
        r2 = requests.get(f"https://financialmodelingprep.com/api/v3/analyst-estimates/{ticker}?limit=3&apikey={FMP_API_KEY}", timeout=15)
        a, e = r1.json(), r2.json()
        # FMP returns an error dict (not a list) on bad key / limit exhausted
        if not isinstance(a, list): a = None
        if not isinstance(e, list): e = None
        return a, e
    except Exception:
        return None, None

@st.cache_data(ttl=1800, show_spinner=False)
def get_stock_news(ticker):
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        feed = feedparser.parse(url)
        return [{"title": e.title, "link": e.link, "published": getattr(e, "published", "")} for e in feed.entries[:6]]
    except Exception:
        return []

def detect_123_reversal(close):
    try:
        prices = close.values[-60:]
        lows = [(i, prices[i]) for i in range(2, len(prices)-2)
                if prices[i] < prices[i-1] and prices[i] < prices[i+1]]
        if len(lows) >= 2:
            p1_idx, p1 = lows[-2]
            p3_idx, p3 = lows[-1]
            if p3 > p1 and prices[-1] > max(prices[p1_idx:p3_idx]):
                return True
        return False
    except Exception:
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
        return (sorted([s for s in supports if s < price_now], reverse=True)[:3],
                sorted([r for r in resistances if r > price_now])[:3])
    except Exception:
        return [], []

# ---------- load everything ----------

fg_score, fg_label, fg_is_stock = get_fear_greed()
spy_return = get_spy_return()
if spy_return is None:
    st.warning("⚠️ Could not load SPY benchmark — Relative Strength scores are disabled this session.")

results = []
skipped = []

with st.spinner("Downloading price history (batched)..."):
    stock_data = get_all_stock_data(tuple(tickers))

with st.spinner("Loading fundamentals..."):
    all_fundamentals = get_all_fundamentals(tuple(t for t in tickers if t in stock_data))

with st.spinner("Scoring stocks..."):
    progress = st.progress(0)
    for i, ticker in enumerate(tickers):
        df = stock_data.get(ticker)
        if df is None:
            skipped.append(ticker)
            progress.progress((i+1)/len(tickers))
            continue
        try:
            close    = df["Close"].squeeze()
            vol      = df["Volume"].squeeze()
            close_1y = close.iloc[-252:] if len(close) >= 252 else close
            price    = round(float(close.iloc[-1]), 2)

            ma50_s  = close_1y.rolling(50).mean()
            ma150_s = close_1y.rolling(150).mean()
            ma200_s = close_1y.rolling(200).mean()
            ma50   = safe_num(ma50_s.iloc[-1])
            ma150  = safe_num(ma150_s.iloc[-1])
            ma200  = safe_num(ma200_s.iloc[-1])

            high52   = round(float(close_1y.max()), 2)
            low52    = round(float(close_1y.min()), 2)
            pct_from_50   = round((price - ma50)  / ma50  * 100, 1) if ma50  else 0.0
            pct_from_200  = round((price - ma200) / ma200 * 100, 1) if ma200 else 0.0
            pct_from_high = round((price - high52)/ high52* 100, 1)

            # FIX: slope lookups guarded — short histories made iloc[-6]/[-10]
            # land on NaN and corrupt comparisons
            ma50_slope  = 0.0
            ma200_slope = 0.0
            if ma50 and len(ma50_s.dropna()) >= 6:
                v = safe_num(ma50_s.iloc[-6])
                if v is not None: ma50_slope = ma50 - v
            if ma200 and len(ma200_s.dropna()) >= 10:
                v = safe_num(ma200_s.iloc[-10])
                if v is not None: ma200_slope = ma200 - v

            stock_return  = float(close_1y.iloc[-1]) / float(close_1y.iloc[0]) - 1
            rs            = round((stock_return - spy_return) * 100, 1) if spy_return is not None else 0.0
            reversal_123  = detect_123_reversal(close_1y)

            rsi_series    = calculate_rsi(close_1y).dropna()
            current_rsi   = round(float(rsi_series.iloc[-1]), 1) if not rsi_series.empty else 50.0
            if np.isnan(current_rsi): current_rsi = 50.0

            avg_vol_50    = safe_num(vol.rolling(50).mean().iloc[-1], 0)
            last_vol      = safe_num(vol.iloc[-1], 0)
            volume_ratio  = round(last_vol / avg_vol_50, 2) if avg_vol_50 and avg_vol_50 > 0 else 0

            if current_rsi >= 80:    rsi_status = "‼️ Extremely Overbought"
            elif current_rsi >= 70:  rsi_status = "⚠️ Overbought"
            elif current_rsi <= 20:  rsi_status = "‼️ Extremely Oversold"
            elif current_rsi <= 30:  rsi_status = "⚠️ Oversold"
            else:                    rsi_status = "✅ Neutral"

            if volume_ratio >= 5:    volume_status = "‼️ Climax Volume"
            elif volume_ratio >= 3:  volume_status = "⚠️ Very High Volume"
            elif volume_ratio >= 1.5:volume_status = "✅ Above Average"
            else:                    volume_status = "Normal"

            if pct_from_200 >= 50:   extension_status = "‼️ Very Extended vs 200MA"
            elif pct_from_200 >= 30: extension_status = "⚠️ Extended vs 200MA"
            elif pct_from_200 <= -30:extension_status = "⚠️ Washed Out vs 200MA"
            else:                    extension_status = "✅ Normal vs 200MA"

            if pct_from_high >= -5:    high_status = "Near 52W High"
            elif pct_from_high <= -40: high_status = "⚠️ Deeply Below 52W High"
            else:                      high_status = "Normal"

            fund            = all_fundamentals.get(ticker, {})
            rev_growth      = fund.get("rev_growth")
            earnings_growth = fund.get("earnings_growth")
            profit_margin   = fund.get("profit_margin")
            forward_pe      = fund.get("forward_pe")

            actuals, estimates = get_fmp_financials(ticker)
            fundamental_score, fundamental_signals, fundamental_warnings = get_fundamental_score(actuals, estimates)

            score = 0
            scoring_breakdown = []

            if ma50 and ma150 and ma200 and ma50 > ma150 > ma200 and price > ma50:
                score += 15; scoring_breakdown.append(("Trend Template", 15, "50MA > 150MA > 200MA and price above 50MA"))
            else:
                scoring_breakdown.append(("Trend Template", 0, "Trend template not fully confirmed"))

            if ma50_slope > 0 and ma200_slope > 0:
                score += 10; scoring_breakdown.append(("MA Slope", 10, "50MA and 200MA are both rising"))
            else:
                scoring_breakdown.append(("MA Slope", 0, "MA slopes not both rising"))

            if reversal_123:
                score += 15; scoring_breakdown.append(("1-2-3 Reversal", 15, "1-2-3 reversal confirmed"))
            else:
                scoring_breakdown.append(("1-2-3 Reversal", 0, "1-2-3 reversal not confirmed"))

            if spy_return is None:
                scoring_breakdown.append(("Relative Strength", 0, "SPY benchmark unavailable"))
            elif rs > 20:
                score += 15; scoring_breakdown.append(("Relative Strength", 15, "Outperforming SPY by >20%"))
            elif rs > 10:
                score += 10; scoring_breakdown.append(("Relative Strength", 10, "Outperforming SPY by >10%"))
            elif rs > 0:
                score += 5;  scoring_breakdown.append(("Relative Strength", 5,  "Outperforming SPY slightly"))
            else:
                scoring_breakdown.append(("Relative Strength", 0, "Underperforming SPY"))

            if rev_growth and rev_growth > 0.20:
                score += 10; scoring_breakdown.append(("Revenue Growth", 10, "Revenue growth above 20%"))
            elif rev_growth and rev_growth > 0.10:
                score += 5;  scoring_breakdown.append(("Revenue Growth", 5,  "Revenue growth above 10%"))
            else:
                scoring_breakdown.append(("Revenue Growth", 0, "Below threshold or unavailable"))

            if earnings_growth and earnings_growth > 0.20:
                score += 10; scoring_breakdown.append(("Earnings Growth", 10, "Earnings growth above 20%"))
            elif earnings_growth and earnings_growth > 0.10:
                score += 5;  scoring_breakdown.append(("Earnings Growth", 5,  "Earnings growth above 10%"))
            else:
                scoring_breakdown.append(("Earnings Growth", 0, "Below threshold or unavailable"))

            if profit_margin and profit_margin > 0.10:
                score += 5; scoring_breakdown.append(("Profit Margin", 5, "Profit margin above 10%"))
            else:
                scoring_breakdown.append(("Profit Margin", 0, "Below 10% or unavailable"))

            if forward_pe and 0 < forward_pe < 25:
                score += 10; scoring_breakdown.append(("Valuation", 10, "Forward PE below 25"))
            elif forward_pe and 25 <= forward_pe < 40:
                score += 5;  scoring_breakdown.append(("Valuation", 5,  "Forward PE between 25-40"))
            else:
                scoring_breakdown.append(("Valuation", 0, "PE too high or unavailable"))

            if 50 <= current_rsi <= 70:
                score += 5;  scoring_breakdown.append(("RSI Quality", 5,   "RSI in healthy zone 50-70"))
            elif current_rsi >= 80:
                score -= 10; scoring_breakdown.append(("RSI Warning", -10, "Extremely overbought RSI >= 80"))
            elif current_rsi >= 70:
                score -= 5;  scoring_breakdown.append(("RSI Warning", -5,  "Overbought RSI >= 70"))
            elif current_rsi <= 30:
                score -= 5;  scoring_breakdown.append(("RSI Warning", -5,  "Oversold RSI <= 30"))
            else:
                scoring_breakdown.append(("RSI Quality", 0, "RSI neutral"))

            if pct_from_200 >= 50:
                score -= 10; scoring_breakdown.append(("Extension Warning", -10, "Price >50% above 200MA"))
            elif pct_from_200 >= 30:
                score -= 5;  scoring_breakdown.append(("Extension Warning", -5,  "Price >30% above 200MA"))
            else:
                scoring_breakdown.append(("Extension Warning", 0, "Not excessively extended"))

            if 1.5 <= volume_ratio < 5:
                score += 5;  scoring_breakdown.append(("Volume", 5,  "Volume above 1.5x average"))
            elif volume_ratio >= 5:
                score -= 5;  scoring_breakdown.append(("Volume", -5, "Possible climax volume >5x"))
            else:
                scoring_breakdown.append(("Volume", 0, "Normal volume"))

            # FIX: crypto F&G proxy no longer silently penalises stock scores
            if fg_score and fg_is_stock and fg_score >= 75:
                score -= 5; scoring_breakdown.append(("Market Sentiment", -5, "Fear & Greed is high"))
            else:
                scoring_breakdown.append(("Market Sentiment", 0, "No sentiment penalty"))

            score = max(0, min(score, 100))

            row_data = {
                "_price_raw": price, "_rs_raw": rs, "_rev_growth_raw": rev_growth,
                "_rsi_raw": current_rsi, "_ma50_slope": ma50_slope, "_ma200_slope": ma200_slope,
            }
            buy_score,  buy_signals  = get_buy_score(row_data, fund, fundamental_score)
            risk_score, risk_signals = get_risk_score(row_data, fund, fundamental_score)
            net_score = buy_score - risk_score
            verdict   = get_verdict(score, buy_score, risk_score)

            results.append({
                "Ticker": ticker, "Price": f"${price:.2f}", "Score": score,
                "Label": get_label(score), "Verdict": verdict,
                "Mkt Cap": fmt_cap(fund.get("market_cap")),
                "RSI": current_rsi, "RSI Status": rsi_status,
                "Vol Ratio": volume_ratio, "Vol Status": volume_status,
                "Extension": extension_status, "52W Status": high_status,
                "50MA": fmt_price(ma50), "200MA": fmt_price(ma200),
                "52W High": f"${high52:.2f}", "52W Low": f"${low52:.2f}",
                "vs 50MA": f"{pct_from_50}%", "vs 200MA": f"{pct_from_200}%",
                "vs 52W High": f"{pct_from_high}%", "RS vs SPY": f"{rs}%" if spy_return is not None else "N/A",
                "1-2-3 Reversal": "✅" if reversal_123 else "❌",
                "Buy Setup": buy_score,  "Buy Label": get_buy_label(buy_score),
                "Risk Score": risk_score,"Risk Label": get_risk_label(risk_score),
                "Net Score": net_score,  "Fund Score": fundamental_score,
                "_price_raw": price, "_rs_raw": rs, "_rev_growth_raw": rev_growth,
                "_rsi_raw": current_rsi, "_ma50_slope": ma50_slope, "_ma200_slope": ma200_slope,
                "_fund": fund, "_scoring_breakdown": scoring_breakdown,
                "_buy_signals": buy_signals, "_risk_signals": risk_signals,
                "_fundamental_signals": fundamental_signals,
                "_fundamental_warnings": fundamental_warnings,
                "_actuals": actuals, "_estimates": estimates,
            })
        except Exception:
            skipped.append(ticker)
        progress.progress((i+1)/len(tickers))
    progress.empty()

if not results:
    st.error("No stocks loaded. Yahoo Finance may be rate-limiting — wait a minute and refresh.")
    st.stop()

df_results = pd.DataFrame(results).sort_values("Score", ascending=False)

if skipped:
    st.warning(f"Could not load: {', '.join(skipped)}")

tab0, tab1, tab_buy, tab_sell, tab2, tab3, tab4, tab5 = st.tabs([
    "⚡ Quick Scan", "📊 Scanner", "🟢 Buying Signals",
    "🔴 Risk Warnings", "🔎 Analysis", "📑 Fundamentals", "🌍 Macro", "📰 News"
])

with tab0:
    st.markdown("### ⚡ Quick Scan — Daily Watchlist")
    st.caption("Score ≥ 80 | Buy Setup ≥ 70 | Risk < 40 | RSI 50–70 | Rev Growth > 10% | RS vs SPY > 10%")
    quick = df_results[
        (df_results["Score"] >= 80) &
        (df_results["Buy Setup"] >= 70) &
        (df_results["Risk Score"] < 40) &
        (df_results["_rsi_raw"] >= 50) &
        (df_results["_rsi_raw"] <= 70) &
        (df_results["_rs_raw"] > 10) &
        (df_results["_rev_growth_raw"].apply(lambda x: bool(x) and not pd.isna(x) and x > 0.10))
    ].sort_values("Net Score", ascending=False)

    if quick.empty:
        st.info("No stocks meet all Quick Scan criteria today. Check the full Scanner tab.")
    else:
        st.success(f"✅ {len(quick)} stocks meet all criteria today!")
        for _, qrow in quick.iterrows():
            with st.expander(f"{qrow['Ticker']} — {qrow['Verdict']} — Score {qrow['Score']} | Net {qrow['Net Score']}"):
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Price", qrow["Price"])
                q2.metric("Buy Setup", f"{qrow['Buy Setup']}/100")
                q3.metric("Risk Score", f"{qrow['Risk Score']}/100")
                q4.metric("Fund Score", qrow["Fund Score"])
                q5, q6, q7, q8 = st.columns(4)
                q5.metric("RSI", qrow["RSI"])
                q6.metric("RS vs SPY", qrow["RS vs SPY"])
                q7.metric("Net Score", qrow["Net Score"])
                q8.metric("Mkt Cap", qrow["Mkt Cap"])
                qf = qrow["_fund"]
                if qf:
                    qf1, qf2, qf3 = st.columns(3)
                    qf1.metric("Rev Growth", f"{round(qf['rev_growth']*100,1)}%" if qf.get('rev_growth') else "N/A")
                    qf2.metric("Target",     f"${qf['target']:.2f}"              if qf.get('target')     else "N/A")
                    qf3.metric("Upside",     f"{qf['upside']}%"                  if qf.get('upside')     else "N/A")

with tab1:
    def color_score(val):
        if val >= 90: return "background-color: #004d00; color: white; font-weight: bold"
        elif val >= 80: return "background-color: #008000; color: white; font-weight: bold"
        elif val >= 65: return "background-color: #1a5c1a; color: white"
        elif val >= 50: return "background-color: #5c5c1a; color: white"
        else: return "background-color: #3d0000; color: white"

    display_cols = [
        "Ticker","Price","Mkt Cap","Score","Label","Verdict",
        "Buy Setup","Buy Label","Risk Score","Risk Label","Net Score","Fund Score",
        "RSI","RSI Status","50MA","200MA","vs 50MA","vs 200MA","vs 52W High",
        "RS vs SPY","1-2-3 Reversal","Vol Ratio","Vol Status","Extension","52W Status"
    ]
    # FIX: Styler API compatibility across pandas versions
    try:
        styled = df_results[display_cols].style.map(color_score, subset=["Score"])
    except AttributeError:
        styled = df_results[display_cols].style.applymap(color_score, subset=["Score"])
    try:
        styled = styled.format({"RSI": "{:.1f}", "Vol Ratio": "{:.2f}"})
    except Exception:
        pass
    show_df(styled, height=500)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🟢 Elite",     len(df_results[df_results["Score"] >= 90]))
    c2.metric("🟩 Strong",    len(df_results[(df_results["Score"] >= 80) & (df_results["Score"] < 90)]))
    c3.metric("🟨 Watchlist", len(df_results[(df_results["Score"] >= 65) & (df_results["Score"] < 80)]))
    c4.metric("🟧 Early",     len(df_results[(df_results["Score"] >= 50) & (df_results["Score"] < 65)]))
    c5.metric("🔴 Ignore",    len(df_results[df_results["Score"] < 50]))

with tab_buy:
    st.markdown("### 🟢 Buying Signals")
    st.caption("Stocks showing possible buy setups — sorted by Net Score (Buy Setup minus Risk)")
    buy_df = df_results[df_results["Buy Setup"] >= 60].sort_values("Net Score", ascending=False)
    if buy_df.empty:
        st.info("No strong buying setups today.")
    else:
        st.success(f"✅ {len(buy_df)} stocks with possible buy setups")
        for _, brow in buy_df.iterrows():
            with st.expander(f"{brow['Ticker']} — {brow['Buy Label']} — Net {brow['Net Score']} (Buy {brow['Buy Setup']} / Risk {brow['Risk Score']})"):
                b1, b2, b3, b4, b5 = st.columns(5)
                b1.metric("Price",         brow["Price"])
                b2.metric("Overall Score", f"{brow['Score']}/100")
                b3.metric("Buy Setup",     f"{brow['Buy Setup']}/100")
                b4.metric("Risk Score",    f"{brow['Risk Score']}/100")
                b5.metric("Net Score",     brow["Net Score"])
                st.markdown("**Buy Setup Signals:**")
                for sig in brow["_buy_signals"]:
                    st.markdown(f"  {sig}")

with tab_sell:
    st.markdown("### 🔴 Risk Warnings")
    st.caption("Stocks showing possible sell/risk warnings — Risk Score ≥ 60")
    risk_df = df_results[df_results["Risk Score"] >= 60].sort_values("Risk Score", ascending=False)
    if risk_df.empty:
        st.info("No major risk warnings today.")
    else:
        st.warning(f"⚠️ {len(risk_df)} stocks with possible risk warnings")
        for _, srow in risk_df.iterrows():
            with st.expander(f"{srow['Ticker']} — {srow['Risk Label']} — Risk {srow['Risk Score']}"):
                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Price",         srow["Price"])
                s2.metric("Overall Score", f"{srow['Score']}/100")
                s3.metric("Risk Score",    f"{srow['Risk Score']}/100")
                s4.metric("RSI",           srow["RSI"])
                s5.metric("Net Score",     srow["Net Score"])
                st.markdown("**Risk Warning Signals:**")
                for sig in srow["_risk_signals"]:
                    st.markdown(f"  {sig}")

with tab2:
    selected = st.selectbox("🔍 Search stock", df_results["Ticker"].tolist())
    row  = df_results[df_results["Ticker"] == selected].iloc[0]
    fund = row["_fund"]
    supports, resistances = get_support_resistance(stock_data[selected]["Close"].squeeze().iloc[-252:])

    st.markdown("### 📋 Executive Summary")
    warnings = []
    if "Overbought" in row["RSI Status"]: warnings.append(row["RSI Status"])
    if "Oversold"   in row["RSI Status"]: warnings.append(row["RSI Status"])
    if "Extended"   in row["Extension"]:  warnings.append(row["Extension"])
    if "Climax"     in row["Vol Status"]: warnings.append(row["Vol Status"])
    st.warning(" | ".join(warnings)) if warnings else st.success("✅ No major warnings")

    st.markdown(f"#### {selected} — {row['Verdict']}")
    e1,e2,e3,e4 = st.columns(4)
    e1.metric("Price", row["Price"]); e2.metric("Overall Score", f"{int(row['Score'])}/100")
    e3.metric("Mkt Cap", row["Mkt Cap"]); e4.metric("Verdict", row["Verdict"])

    e5,e6,e7,e8 = st.columns(4)
    e5.metric("🟢 Buy Setup",   f"{row['Buy Setup']}/100");  e6.metric("Buy Label",  row["Buy Label"])
    e7.metric("🔴 Risk Score",  f"{row['Risk Score']}/100"); e8.metric("Risk Label", row["Risk Label"])

    e9,e10,e11,e12 = st.columns(4)
    e9.metric("Net Score", row["Net Score"]); e10.metric("Fund Score", row["Fund Score"])
    if fund:
        e11.metric("🎯 Target", f"${fund['target']:.2f}" if fund.get('target') else "N/A")
        e12.metric("📈 Upside", f"{fund['upside']}%"     if fund.get('upside') else "N/A")

    st.markdown("---")
    st.markdown("### 📡 Signal Summary")
    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("#### ✅ Buy Setup Signals")
        for sig in row["_buy_signals"]:
            st.markdown(f'<div style="background:#166534;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{sig}</div>', unsafe_allow_html=True)
        if not row["_buy_signals"]: st.info("No active buy setup signals")
    with sc2:
        st.markdown("#### ⚠️ Risk Warning Signals")
        for sig in row["_risk_signals"]:
            st.markdown(f'<div style="background:#991B1B;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{sig}</div>', unsafe_allow_html=True)
        if not row["_risk_signals"]: st.success("No active risk warning signals")

    st.markdown("---")
    st.markdown("### 📊 Technical Analysis")
    t1,t2,t3,t4 = st.columns(4)
    t1.metric("RSI", row["RSI"]); t2.metric("RSI Status", row["RSI Status"])
    t3.metric("Vol Ratio", row["Vol Ratio"]); t4.metric("Vol Status", row["Vol Status"])
    t5,t6,t7,t8 = st.columns(4)
    t5.metric("vs 50MA", row["vs 50MA"]); t6.metric("vs 200MA", row["vs 200MA"])
    t7.metric("RS vs SPY", row["RS vs SPY"]); t8.metric("Extension", row["Extension"])
    t9,t10,t11,t12 = st.columns(4)
    t9.metric("52W High", row["52W High"]); t10.metric("vs 52W High", row["vs 52W High"])
    t11.metric("52W Low", row["52W Low"]); t12.metric("52W Status", row["52W Status"])
    if fund:
        st.markdown("---")
        f1,f2,f3,f4 = st.columns(4)
        f1.metric("💰 Rev Growth", f"{round(fund['rev_growth']*100,1)}%" if fund.get('rev_growth') else "N/A")
        f2.metric("📉 Fwd PE",     f"{round(fund['forward_pe'],1)}"      if fund.get('forward_pe') else "N/A")
        f3.metric("💵 Margin",     f"{round(fund['profit_margin']*100,1)}%" if fund.get('profit_margin') else "N/A")
        f4.metric("💚 Str Buy",    fund.get('strong_buy', 0))

    st.markdown("---")
    st.markdown("### 📑 Fundamental Quality")
    fq1,fq2,fq3,fq4 = st.columns(4)
    fq1.metric("Fund Score", f"{row['Fund Score']}/100")
    fq2.metric("Str Buy", fund.get('strong_buy',0) if fund else "N/A")
    fq3.metric("Buy",     fund.get('buy',0)        if fund else "N/A")
    fq4.metric("Hold",    fund.get('hold',0)       if fund else "N/A")

    fqc1, fqc2 = st.columns(2)
    with fqc1:
        st.markdown("#### ✅ Fundamental Strengths")
        for sig in row["_fundamental_signals"]:
            st.markdown(f'<div style="background:#166534;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{sig}</div>', unsafe_allow_html=True)
        if not row["_fundamental_signals"]: st.info("No signals — add FMP_API_KEY for full analysis")
    with fqc2:
        st.markdown("#### ⚠️ Fundamental Warnings")
        for warn in row["_fundamental_warnings"]:
            st.markdown(f'<div style="background:#991B1B;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{warn}</div>', unsafe_allow_html=True)
        if not row["_fundamental_warnings"]: st.success("No fundamental warnings")

    st.markdown("---")
    st.markdown("### 🧮 Score Breakdown")
    breakdown_df = pd.DataFrame(row["_scoring_breakdown"], columns=["Category","Points","Reason"])
    pos = int(breakdown_df[breakdown_df["Points"] > 0]["Points"].sum())
    neg = int(breakdown_df[breakdown_df["Points"] < 0]["Points"].sum())
    b1,b2,b3 = st.columns(3)
    b1.metric("✅ Positive Points", pos)
    b2.metric("❌ Penalties", neg)
    b3.metric("🎯 Final Score", f"{int(row['Score'])}/100")
    for _, brow in breakdown_df.iterrows():
        pts  = brow["Points"]
        bg   = "#166534" if pts > 0 else "#991B1B" if pts < 0 else "#374151"
        icon = "✅" if pts > 0 else "❌" if pts < 0 else "➖"
        st.markdown(f"""
        <div style="background:{bg};color:#FFF;padding:10px 14px;border-radius:8px;margin-bottom:4px;font-weight:600;display:flex;justify-content:space-between;">
            <span>{icon} {brow['Category']}</span><span>{'+' if pts>0 else ''}{pts}</span>
        </div>
        <div style="padding:2px 14px 10px;color:#9CA3AF;font-size:0.8rem;">{brow['Reason']}</div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📌 Chart Levels")
    df_sel    = stock_data[selected]
    close_sel = df_sel["Close"].squeeze()
    vol_sel   = df_sel["Volume"].squeeze()

    lvl1,lvl2,lvl3,lvl4 = st.columns(4)
    lvl1.metric("Current Price", row["Price"])
    lvl2.metric("Target",        f"${fund['target']:.2f}" if fund and fund.get("target") else "N/A")
    lvl3.metric("Support 1",     f"${supports[0]}"    if len(supports) > 0 else "N/A")
    lvl4.metric("Resistance 1",  f"${resistances[0]}" if len(resistances) > 0 else "N/A")

    lvl5,lvl6,lvl7,lvl8 = st.columns(4)
    lvl5.metric("Support 2",    f"${supports[1]}"    if len(supports) > 1 else "N/A")
    lvl6.metric("Support 3",    f"${supports[2]}"    if len(supports) > 2 else "N/A")
    lvl7.metric("Resistance 2", f"${resistances[1]}" if len(resistances) > 1 else "N/A")
    lvl8.metric("Resistance 3", f"${resistances[2]}" if len(resistances) > 2 else "N/A")

    vc1,vc2,vc3 = st.columns(3)
    vc1.metric("Volume Ratio",   row["Vol Ratio"])
    vc2.metric("Latest Volume",  fmt_int(vol_sel.iloc[-1]))
    vc3.metric("50D Avg Volume", fmt_int(vol_sel.rolling(50).mean().iloc[-1]))

    st.markdown("---")
    st.markdown("### 📈 Interactive Chart")
    show_sr     = st.checkbox("Show Support/Resistance", value=True)
    show_target = st.checkbox("Show Analyst Target",     value=True)
    show_volume = st.checkbox("Show Volume",             value=True)

    try:
        timeframe = st.segmented_control("Timeframe", ["1M","3M","6M","YTD","1Y","5Y"], default="1Y")
        if timeframe is None: timeframe = "1Y"
    except Exception:
        timeframe = st.radio("Timeframe", ["1M","3M","6M","YTD","1Y","5Y"], horizontal=True, index=4)

    # FIX: yfinance sometimes returns a timezone-aware index; comparing it with a
    # naive Timestamp.now() raises TypeError. Index is normalised in _clean_df,
    # but strip again here defensively.
    if getattr(df_sel.index, "tz", None) is not None:
        df_sel = df_sel.copy()
        df_sel.index = df_sel.index.tz_localize(None)

    now = pd.Timestamp.now()
    if timeframe == "1M":   df_plot = df_sel[df_sel.index >= now - pd.DateOffset(months=1)]
    elif timeframe == "3M": df_plot = df_sel[df_sel.index >= now - pd.DateOffset(months=3)]
    elif timeframe == "6M": df_plot = df_sel[df_sel.index >= now - pd.DateOffset(months=6)]
    elif timeframe == "YTD":df_plot = df_sel[df_sel.index >= pd.Timestamp(now.year, 1, 1)]
    elif timeframe == "1Y": df_plot = df_sel[df_sel.index >= now - pd.DateOffset(years=1)]
    else:                   df_plot = df_sel

    close_plot = df_plot["Close"].squeeze()
    vol_plot   = df_plot["Volume"].squeeze()
    chart_supports    = supports[:2]
    chart_resistances = resistances[:2]

    rows_n = 2 if show_volume else 1
    r_hts  = [0.78, 0.22] if show_volume else [1.0]
    fig = make_subplots(rows=rows_n, cols=1, shared_xaxes=True, row_heights=r_hts, vertical_spacing=0.01)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot, name="Price", line=dict(color="white", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(50).mean(),  name="50MA",  line=dict(color="dodgerblue", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=close_plot.rolling(200).mean(), name="200MA", line=dict(color="red",        width=1.5)), row=1, col=1)

    if show_volume and len(vol_plot) > 0:
        clrs = ["lime" if i==0 or float(vol_plot.iloc[i])>=float(vol_plot.iloc[i-1]) else "red" for i in range(len(vol_plot))]
        fig.add_trace(go.Bar(x=df_plot.index, y=vol_plot, name="Volume", marker_color=clrs, opacity=0.4), row=2, col=1)

    label_x = df_plot.index[-1] if len(df_plot) > 0 else None
    if show_sr and label_x is not None:
        used_s = []
        for i, s in enumerate(chart_supports):
            adj = float(s)
            for uy in used_s:
                if abs(adj-uy)/max(abs(uy),0.001) < 0.015: adj *= (1-0.015*(i+1))
            used_s.append(adj)
            fig.add_hline(y=float(s), line_dash="dash", line_color="lime", opacity=0.35, row=1, col=1)
            fig.add_annotation(x=label_x, y=adj, text=f"S{i+1}: ${s}", showarrow=False,
                xanchor="left", yanchor="middle", bgcolor="rgba(0,160,0,0.75)",
                font=dict(color="white", size=11), borderpad=3)
        used_r = []
        for i, r in enumerate(chart_resistances):
            adj = float(r)
            for uy in used_r:
                if abs(adj-uy)/max(abs(uy),0.001) < 0.015: adj *= (1+0.015*(i+1))
            used_r.append(adj)
            fig.add_hline(y=float(r), line_dash="dash", line_color="tomato", opacity=0.35, row=1, col=1)
            fig.add_annotation(x=label_x, y=adj, text=f"R{i+1}: ${r}", showarrow=False,
                xanchor="left", yanchor="middle", bgcolor="rgba(200,50,50,0.75)",
                font=dict(color="white", size=11), borderpad=3)

    if show_target and fund and fund.get("target") and label_x is not None:
        fig.add_hline(y=fund["target"], line_dash="dot", line_color="gold", opacity=0.8, row=1, col=1)
        fig.add_annotation(x=label_x, y=fund["target"], text=f"Target: ${fund['target']:.2f}", showarrow=False,
            xanchor="left", yanchor="middle", bgcolor="rgba(200,160,0,0.85)",
            font=dict(color="white", size=11), borderpad=3)

    fig.update_layout(
        template="plotly_dark",
        title=dict(text=f"{selected} — {timeframe}", font=dict(size=16, color="white")),
        xaxis_rangeslider_visible=False, height=580,
        margin=dict(l=5, r=100, t=40, b=5),
        legend=dict(orientation="h", y=1.05, x=0, font=dict(color="white")),
        dragmode="drawline", newshape=dict(line_color="yellow"),
        modebar_add=["drawline","drawopenpath","drawrect","eraseshape"],
        plot_bgcolor="#0e0e1a", paper_bgcolor="#0e0e1a", font=dict(color="white")
    )
    fig.update_xaxes(showgrid=False, zeroline=False, color="white")
    fig.update_yaxes(showgrid=True, gridcolor="#1e1e2e", zeroline=False, color="white")
    show_chart(fig)

    if st.button("↩️ Clear All Drawings"): st.rerun()

    st.markdown("---")
    st.markdown("### 🏦 Institutional Ownership")
    own1,own2,own3,own4 = st.columns(4)
    own1.metric("Institution Held", f"{fund.get('held_percent_institutions')*100:.1f}%" if fund and fund.get('held_percent_institutions') else "N/A")
    own2.metric("Insider Held",     f"{fund.get('held_percent_insiders')*100:.1f}%"     if fund and fund.get('held_percent_insiders')     else "N/A")
    own3.metric("Shares Out",  fmt_int(fund.get('shares_outstanding')) if fund else "N/A")
    own4.metric("Float Shares", fmt_int(fund.get('float_shares'))      if fund else "N/A")
    inst_data = get_institutional_holders(selected)
    if inst_data is not None and not inst_data.empty:
        show_df(inst_data)
    else:
        st.info("No detailed holder data available from Yahoo Finance for this ticker.")
    st.caption("Data sourced from Yahoo Finance. May be delayed or unavailable for some tickers.")

with tab3:
    selected_rev = st.selectbox("Select stock", df_results["Ticker"].tolist(), key="rev_select")
    row_rev   = df_results[df_results["Ticker"] == selected_rev].iloc[0]
    actuals   = row_rev["_actuals"]
    estimates = row_rev["_estimates"]

    st.markdown("### 📑 Fundamental Quality")
    fqc1, fqc2 = st.columns(2)
    with fqc1:
        st.markdown("#### ✅ Strengths")
        for sig in row_rev["_fundamental_signals"]:
            st.markdown(f'<div style="background:#166534;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{sig}</div>', unsafe_allow_html=True)
        if not row_rev["_fundamental_signals"]: st.info("No signals — add FMP_API_KEY")
    with fqc2:
        st.markdown("#### ⚠️ Warnings")
        for warn in row_rev["_fundamental_warnings"]:
            st.markdown(f'<div style="background:#991B1B;color:#FFF;padding:8px 12px;border-radius:6px;margin-bottom:4px;">{warn}</div>', unsafe_allow_html=True)
        if not row_rev["_fundamental_warnings"]: st.success("No fundamental warnings")

    st.markdown("---")
    if actuals and len(actuals) > 0:
        rev_data = [{
            "Year":              item.get("calendarYear",""),
            "Revenue ($M)":      round(item.get("revenue",0)/1e6,1),
            "Gross Profit ($M)": round(item.get("grossProfit",0)/1e6,1),
            "Op Income ($M)":    round(item.get("operatingIncome",0)/1e6,1),
            "Net Income ($M)":   round(item.get("netIncome",0)/1e6,1),
            "EPS":               round(item.get("eps",0),2),
            "Op Expenses ($M)":  round(item.get("operatingExpenses",0)/1e6,1),
            "COGS ($M)":         round(item.get("costOfRevenue",0)/1e6,1),
        } for item in reversed(actuals)]
        df_rev = pd.DataFrame(rev_data)
        st.markdown("#### 📊 Income Statement (Last 5 Years)")
        show_df(df_rev)
        fig_rev = go.Figure()
        fig_rev.add_trace(go.Bar(x=df_rev["Year"], y=df_rev["Revenue ($M)"],      name="Revenue",      marker_color="dodgerblue"))
        fig_rev.add_trace(go.Bar(x=df_rev["Year"], y=df_rev["Gross Profit ($M)"], name="Gross Profit", marker_color="lime"))
        fig_rev.add_trace(go.Scatter(x=df_rev["Year"], y=df_rev["EPS"], name="EPS", yaxis="y2", line=dict(color="gold", width=2)))
        fig_rev.update_layout(
            template="plotly_dark", title="Revenue, Gross Profit & EPS", barmode="group",
            yaxis=dict(title="$ Million", color="white"),
            yaxis2=dict(title="EPS", overlaying="y", side="right", color="white"),
            height=400, paper_bgcolor="#0e0e1a", plot_bgcolor="#0e0e1a", font=dict(color="white"))
        show_chart(fig_rev)
    else:
        st.info("Add FMP_API_KEY to Streamlit secrets for full Revenue & EPS data.")
        fund2 = row_rev["_fund"]
        if fund2:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Rev Growth YoY", f"{round(fund2['rev_growth']*100,1)}%" if fund2.get('rev_growth') else "N/A")
            c2.metric("Trailing EPS",   f"${fund2.get('eps_trailing','N/A')}")
            c3.metric("Forward EPS",    f"${fund2.get('eps_forward','N/A')}")
            c4.metric("Profit Margin",  f"{round(fund2['profit_margin']*100,1)}%" if fund2.get('profit_margin') else "N/A")

    if estimates and len(estimates) > 0:
        est_data = [{
            "Year":         e.get("date","")[:4],
            "Est Rev ($M)": round(e.get("estimatedRevenueAvg",0)/1e6,1),
            "Est EPS":      round(e.get("estimatedEpsAvg",0),2)
        } for e in estimates[:3]]
        st.markdown("#### 🔮 Revenue & EPS Estimates (Next 3 Years)")
        show_df(pd.DataFrame(est_data))

with tab4:
    macro = get_macro()
    st.markdown("### 🌍 Macro Dashboard")
    if fg_score:
        fg_color = "🟢" if fg_score >= 60 else "🟡" if fg_score >= 40 else "🔴"
        suffix = "" if fg_is_stock else " — crypto proxy, stock index unavailable"
        st.metric(f"{fg_color} Fear & Greed", f"{fg_score} — {fg_label}{suffix}")
    st.markdown("---")
    macro_items = list(macro.items())
    for j in range(0, len(macro_items), 4):
        cols = st.columns(4)
        for k, (name, data) in enumerate(macro_items[j:j+4]):
            label = name + " (proxy)" if "Treasury" in name else name
            cols[k].metric(label,
                f"{data['value']}%" if "Treasury" in name and data['value'] != "N/A" else str(data['value']),
                delta=f"{data['change']:+.2f}")

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
    # FIX: the Reuters RSS feed was shut down years ago and always returned
    # nothing. Replaced with CNBC Top News, with Yahoo Finance as backup.
    macro_feeds = [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://finance.yahoo.com/news/rssindex",
    ]
    shown = 0
    for feed_url in macro_feeds:
        if shown >= 5:
            break
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                if shown >= 5:
                    break
                st.markdown(f"• [{entry.title}]({entry.link})")
                shown += 1
        except Exception:
            continue
    if shown == 0:
        st.info("No macro news available right now.")
