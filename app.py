import os
import threading
import time
from flask import Flask
import pandas as pd
import pandas_ta as ta
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

latest_signal = "Scanning market for setups..."


def send_telegram_alert(message):
  """Sends structured trading signal to Telegram."""
  if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print(f"Telegram credentials missing. Alert log:\n{message}", flush=True)
    return

  url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending Telegram alert: {e}", flush=True)


def fetch_candles(granularity="300", limit=100):
  """Fetches historical OHLC candle data from Coinbase public API."""
  # granularity: 300 = 5m, 900 = 15m, 3600 = 1h
  url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity={granularity}"
  headers = {"User-Agent": "BTC-Trading-Bot"}
  res = requests.get(url, headers=headers, timeout=10)

  if res.status_code == 200:
    data = res.json()
    # Coinbase returns [time, low, high, open, close, volume]
    df = pd.DataFrame(
        data, columns=["time", "low", "high", "open", "close", "volume"]
    )
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.sort_values("time").reset_index(drop=True)
    return df
  return None


def analyze_market_and_signal():
  global latest_signal
  df = fetch_candles(granularity="900", limit=100)  # 15-minute timeframe

  if df is None or len(df) < 50:
    return

  # Calculate Indicators
  df["EMA_9"] = ta.ema(df["close"], length=9)
  df["EMA_21"] = ta.ema(df["close"], length=21)
  df["RSI"] = ta.rsi(df["close"], length=14)
  df["ATR"] = ta.atr(df["high"], df["low"], df["close"], length=14)

  # Extract latest closed candle values
  latest = df.iloc[-1]
  previous = df.iloc[-2]

  entry_price = float(latest["close"])
  atr = float(latest["ATR"])

  # Signal Conditions
  bullish_cross = (previous["EMA_9"] <= previous["EMA_21"]) and (
      latest["EMA_9"] > latest["EMA_21"]
  )
  bearish_cross = (previous["EMA_9"] >= previous["EMA_21"]) and (
      latest["EMA_9"] < latest["EMA_21"]
  )

  # BUY Setup Check
  if bullish_cross and latest["RSI"] > 50:
    stop_loss = entry_price - (atr * 1.5)
    take_profit = entry_price + (atr * 3.0)  # 1:2 Risk-to-Reward Ratio

    alert_msg = (
        f"🟢 <b>BUY SIGNAL DETECTED</b>\n\n"
        f"<b>Asset:</b> BTC/USD (15m)\n"
        f"<b>Entry:</b> ${entry_price:,.2f}\n"
        f"<b>Stop-Loss (SL):</b> ${stop_loss:,.2f}\n"
        f"<b>Take-Profit (TP):</b> ${take_profit:,.2f}\n"
        f"<b>Risk/Reward Ratio:</b> 1:2\n"
        f"<b>RSI:</b> {latest['RSI']:.1f}"
    )

    latest_signal = f"BUY @ ${entry_price:,.2f} | SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f}"
    send_telegram_alert(alert_msg)
    time.sleep(900)  # Pause scans for 15 minutes to avoid duplicate alerts

  # SELL Setup Check
  elif bearish_cross and latest["RSI"] < 50:
    stop_loss = entry_price + (atr * 1.5)
    take_profit = entry_price - (atr * 3.0)  # 1:2 Risk-to-Reward Ratio

    alert_msg = (
        f"🔴 <b>SELL SIGNAL DETECTED</b>\n\n"
        f"<b>Asset:</b> BTC/USD (15m)\n"
        f"<b>Entry:</b> ${entry_price:,.2f}\n"
        f"<b>Stop-Loss (SL):</b> ${stop_loss:,.2f}\n"
        f"<b>Take-Profit (TP):</b> ${take_profit:,.2f}\n"
        f"<b>Risk/Reward Ratio:</b> 1:2\n"
        f"<b>RSI:</b> {latest['RSI']:.1f}"
    )

    latest_signal = f"SELL @ ${entry_price:,.2f} | SL: ${stop_loss:,.2f} | TP: ${take_profit:,.2f}"
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
    time.sleep(60)  # Scan market every minute


# Start scanner thread
threading.Thread(target=btc_monitor_loop, daemon=True).start()


@app.route("/")
def home():
  return f"BTC Signal Bot Active. Latest Status: {latest_signal}"


if __name__ == "__main__":
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)