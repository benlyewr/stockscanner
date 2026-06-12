"""
daily_alert.py — scans the watchlist after market close and sends a Telegram
message when buy signals hit. Runs on GitHub Actions (see .github/workflows/).

Uses the same Buy Setup / Risk Score logic as the Streamlit app (app.py),
minus the FMP fundamental score (no key needed). Alert threshold:
Buy Setup >= 70 and Risk Score < 40  -> included in the alert.
"""

import os
import sys
import requests
import numpy as np
import pandas as pd
import yfinance as yf

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

BUY_THRESHOLD  = 70   # Buy Setup score required to alert
RISK_CEILING   = 40   # Risk Score must be below this

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


def safe_num(x, default=None):
    try:
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def calculate_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def clean_df(df):
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    if getattr(df.index, "tz", None) is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    df = df.dropna(how="all")
    if "Close" in df.columns:
        df = df.dropna(subset=["Close"])
    return df if not df.empty and len(df) >= 50 else None


def get_all_stock_data(symbols):
    out = {}
    try:
        data = yf.download(symbols, period="2y", auto_adjust=True,
                           progress=False, group_by="ticker", threads=True)
        if isinstance(data.columns, pd.MultiIndex):
            for t in symbols:
                try:
                    if t in data.columns.get_level_values(0):
                        df = clean_df(data[t])
                        if df is not None:
                            out[t] = df
                except Exception:
                    pass
    except Exception:
        pass
    for t in symbols:
        if t in out:
            continue
        try:
            df = clean_df(yf.download(t, period="2y", auto_adjust=True,
                                      progress=False, threads=False))
            if df is not None:
                out[t] = df
        except Exception:
            pass
    return out


def get_fundamentals(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
        return {
            "rev_growth":      safe_num(info.get("revenueGrowth")),
            "earnings_growth": safe_num(info.get("earningsGrowth")),
            "forward_pe":      safe_num(info.get("forwardPE")),
        }
    except Exception:
        return {}


def spy_return():
    try:
        spy = clean_df(yf.download("SPY", period="1y", auto_adjust=True,
                                   progress=False, threads=False))
        if spy is None:
            return None
        close = spy["Close"].squeeze().dropna()
        return float(close.iloc[-1]) / float(close.iloc[0]) - 1
    except Exception:
        return None


def score_ticker(df, fund, spy_ret):
    """Same Buy Setup / Risk logic as app.py (minus FMP fundamental score)."""
    close = df["Close"].squeeze()
    close_1y = close.iloc[-252:] if len(close) >= 252 else close
    price = round(float(close.iloc[-1]), 2)

    ma50_s = close_1y.rolling(50).mean()
    ma200_s = close_1y.rolling(200).mean()
    ma50 = safe_num(ma50_s.iloc[-1])
    ma200 = safe_num(ma200_s.iloc[-1])

    ma50_slope = 0.0
    ma200_slope = 0.0
    if ma50 and len(ma50_s.dropna()) >= 6:
        v = safe_num(ma50_s.iloc[-6])
        if v is not None:
            ma50_slope = ma50 - v
    if ma200 and len(ma200_s.dropna()) >= 10:
        v = safe_num(ma200_s.iloc[-10])
        if v is not None:
            ma200_slope = ma200 - v

    stock_ret = float(close_1y.iloc[-1]) / float(close_1y.iloc[0]) - 1
    rs = round((stock_ret - spy_ret) * 100, 1) if spy_ret is not None else 0.0

    rsi_series = calculate_rsi(close_1y).dropna()
    rsi = round(float(rsi_series.iloc[-1]), 1) if not rsi_series.empty else 50.0
    if np.isnan(rsi):
        rsi = 50.0

    rev = fund.get("rev_growth")
    eg = fund.get("earnings_growth")
    fpe = fund.get("forward_pe")

    # --- Buy Setup score (mirrors get_buy_score in app.py) ---
    buy = 0
    reasons = []
    if ma50_slope > 0:
        buy += 15; reasons.append("50MA rising")
    if ma200_slope > 0:
        buy += 10; reasons.append("200MA rising")
    if 50 <= rsi <= 70:
        buy += 15; reasons.append(f"RSI healthy ({rsi})")
    if rs > 10:
        buy += 20; reasons.append(f"+{rs}% vs SPY")
    elif rs > 0:
        buy += 10; reasons.append(f"+{rs}% vs SPY")
    if rev and rev > 0.20:
        buy += 20; reasons.append("Rev growth >20%")
    elif rev and rev > 0.10:
        buy += 10; reasons.append("Rev growth >10%")
    if eg and eg > 0.20:
        buy += 20; reasons.append("EPS growth >20%")
    elif eg and eg > 0.10:
        buy += 10; reasons.append("EPS growth >10%")
    buy = min(buy, 100)

    # --- Risk score (mirrors get_risk_score in app.py, minus fund score) ---
    risk = 0
    if rsi >= 80:
        risk += 30
    elif rsi >= 70:
        risk += 15
    if rs < -10:
        risk += 25
    elif rs < 0:
        risk += 10
    if ma50_slope < 0:
        risk += 20
    if ma200_slope < 0:
        risk += 15
    if rev and rev < 0:
        risk += 20
    if fpe and fpe > 60:
        risk += 10
    risk = min(risk, 100)

    return {"price": price, "buy": buy, "risk": risk,
            "rsi": rsi, "rs": rs, "reasons": reasons}


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing — printing message instead:\n")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)
    print("Telegram response:", r.status_code, r.text[:200])
    return r.ok


def main():
    print(f"Scanning {len(tickers)} tickers...")
    spy_ret = spy_return()
    data = get_all_stock_data(tickers)
    print(f"Loaded {len(data)} tickers.")

    hits = []
    for t, df in data.items():
        try:
            fund = get_fundamentals(t)
            s = score_ticker(df, fund, spy_ret)
            if s["buy"] >= BUY_THRESHOLD and s["risk"] < RISK_CEILING:
                hits.append((t, s))
        except Exception as e:
            print(f"{t}: skipped ({e})")

    hits.sort(key=lambda x: x[1]["buy"] - x[1]["risk"], reverse=True)

    today = pd.Timestamp.now().strftime("%d %b %Y")
    if hits:
        lines = [f"📈 <b>Stock Scanner — Buy Signals ({today})</b>",
                 f"Criteria: Buy ≥ {BUY_THRESHOLD}, Risk &lt; {RISK_CEILING}", ""]
        for t, s in hits:
            lines.append(
                f"🟢 <b>{t}</b>  ${s['price']:.2f}\n"
                f"   Buy {s['buy']}/100 | Risk {s['risk']}/100 | RSI {s['rsi']}\n"
                f"   {', '.join(s['reasons'][:4])}"
            )
        msg = "\n".join(lines)
    else:
        msg = (f"📈 <b>Stock Scanner ({today})</b>\n"
               f"No buy signals today (Buy ≥ {BUY_THRESHOLD}, Risk &lt; {RISK_CEILING}). "
               f"{len(data)} tickers scanned.")

    ok = send_telegram(msg)
    print("Done." if ok else "Finished (message printed, not sent).")


if __name__ == "__main__":
    sys.exit(main())
