import os
import threading
import time
from flask import Flask
import numpy as np
import pandas as pd
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

latest_signal = "Scanning market for setups..."


def send_telegram_alert(message):
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print(f"Telegram credentials missing. Alert log:\n{message}", flush=True)
    return

  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending Telegram alert: {e}", flush=True)


def fetch_candles(granularity="900"):
  """Fetches 15m OHLC candle data from Coinbase."""
  url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity={granularity}"
  headers = {"User-Agent": "BTC-Trading-Bot"}
  res = requests.get(url, headers=headers, timeout=10)

  if res.status_code == 200:
    data = res.json()
    df = pd.DataFrame(
        data, columns=["time", "low", "high", "open", "close", "volume"]
    )
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.sort_values("time").reset_index(drop=True)
    return df
  return None


def compute_indicators(df):
  """Calculates EMA, RSI, and ATR using native pandas."""
  # Exponential Moving Averages
  df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
  df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()

  # Relative Strength Index (RSI 14)
  delta = df["close"].diff()
  gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
  rs = gain / loss
  df["RSI"] = 100 - (100 / (1 + rs))

  # Average True Range (ATR 14)
  high_low = df["high"] - df["low"]
  high_close = np.abs(df["high"] - df["close"].shift())
  low_close = np.abs(df["low"] - df["close"].shift())
  ranges = pd.concat([high_low, high_close, low_close], axis=1)
  true_range = np.max(ranges, axis=1)
  df["ATR"] = true_range.rolling(14).mean()

  return df


def analyze_market_and_signal():
  global latest_signal
  df = fetch_candles()

  if df is None or len(df) < 30:
    return

  df = compute_indicators(df)

  latest = df.iloc[-1]
  previous = df.iloc[-2]

  entry_price = float(latest["close"])
  atr = float(latest["ATR"])

  bullish_cross = (previous["EMA_9"] <= previous["EMA_21"]) and (
      latest["EMA_9"] > latest["EMA_21"]
  )
  bearish_cross = (previous["EMA_9"] >= previous["EMA_21"]) and (
      latest["EMA_9"] < latest["EMA_21"]
  )

  # BUY Setup
  if bullish_cross and latest["RSI"] > 50:
    stop_loss = entry_price - (atr * 1.5)
    take_profit = entry_price + (atr * 3.0)

    alert_msg = (
        f"🟢 <b>BUY SIGNAL DETECTED</b>\n\n"
        f"<b>Asset:</b> BTC/USD (15m)\n"
        f"<b>Entry:</b> ${entry_price:,.2f}\n"
        f"<b>Stop-Loss (SL):</b> ${stop_loss:,.2f}\n"
        f"<b>Take-Profit (TP):</b> ${take_profit:,.2f}\n"
        f"<b>RSI:</b> {latest['RSI']:.1f}"
    )
    latest_signal = f"BUY @ ${entry_price:,.2f}"
    send_telegram_alert(alert_msg)
    time.sleep(900)

  # SELL Setup
  elif bearish_cross and latest["RSI"] < 50:
    stop_loss = entry_price + (atr * 1.5)
    take_profit = entry_price - (atr * 3.0)

    alert_msg = (
        f"🔴 <b>SELL SIGNAL DETECTED</b>\n\n"
        f"<b>Asset:</b> BTC/USD (15m)\n"
        f"<b>Entry:</b> ${entry_price:,.2f}\n"
        f"<b>Stop-Loss (SL):</b> ${stop_loss:,.2f}\n"
        f"<b>Take-Profit (TP):</b> ${take_profit:,.2f}\n"
        f"<b>RSI:</b> {latest['RSI']:.1f}"
    )
    latest_signal = f"SELL @ ${entry_price:,.2f}"
    send_telegram_alert(alert_msg)
    time.sleep(900)


def btc_monitor_loop():
  time.sleep(5)
  print("Trading Signal Scanner Active...", flush=True)
  while True:
    try:
      analyze_market_and_signal()
    except Exception as e:
      print(f"Error in signal scan: {e}", flush=True)
    time.sleep(60)


threading.Thread(target=btc_monitor_loop, daemon=True).start()


@app.route("/")
def home():
  return f"BTC Signal Bot Active. Status: {latest_signal}"


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)