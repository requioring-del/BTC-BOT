import asyncio
import json
import os
import time
import numpy as np
import requests
import websockets

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8695599623")
SYMBOLS = ["btcusdt", "solusdt"]

# Alert cooldown per symbol (in seconds) to avoid spamming single crossovers
COOLDOWN_SECONDS = 300  # 5 minutes
last_alert_time = {"btcusdt": 0, "solusdt": 0}


def send_telegram_alert(message):
    """Sends real-time trade signal alerts to Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"\n[ERROR] Telegram send error: {e}")


def calculate_ema(prices, period):
    prices = np.array(prices, dtype=float)
    weights = np.exp(np.linspace(-1.0, 0.0, period))
    weights /= weights.sum()
    ema = np.convolve(prices, weights, mode="full")[: len(prices)]
    ema[:period] = ema[period]
    return ema[-1]


def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[: period + 1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.0
        else:
            upval = 0.0
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi[-1]


def fetch_historical_prices(symbol):
    """Fetches recent prices and highs/lows for calculations."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval=1m&limit=50"
    res = requests.get(url).json()
    closes = [float(candle[4]) for candle in res]
    lows = [float(candle[3]) for candle in res]
    highs = [float(candle[2]) for candle in res]
    return closes, lows, highs


async def monitor_symbol(symbol):
    # Connect directly to the real-time trade ticker stream
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"

    async with websockets.connect(stream_url) as ws:
        print(f"[{symbol.upper()}] Monitoring live trade ticks...")

        while True:
            response = await ws.recv()
            data = json.loads(response)
            live_price = float(data["p"])

            now = time.time()
            if now - last_alert_time[symbol] < COOLDOWN_SECONDS:
                continue  # Skip evaluation if in cooldown window

            closes, lows, highs = fetch_historical_prices(symbol)
            closes[-1] = live_price  # Replace latest candle close with live price

            ema9 = calculate_ema(closes, 9)
            ema21 = calculate_ema(closes, 21)
            rsi = calculate_rsi(closes, 14)

            # Bullish Trigger
            if ema9 > ema21 and rsi < 68:
                sl = min(lows[-5:])  # Local swing low
                risk = live_price - sl
                if risk > 0:
                    tp = live_price + (risk * 1.5)  # 1:1.5 Risk-to-Reward Ratio

                    msg = (
                        f"🟢 *REAL-TIME BULLISH SETUP ({symbol.upper()})*\n\n"
                        f"• *Entry Price:* ${live_price:,.2f}\n"
                        f"• *Stop Loss (SL):* ${sl:,.2f}\n"
                        f"• *Take Profit (TP):* ${tp:,.2f} (1:1.5 RR)\n\n"
                        f"• *Signal:* 9 EMA crossed above 21 EMA\n"
                        f"• *RSI (14):* {rsi:.1f}"
                    )
                    send_telegram_alert(msg)
                    last_alert_time[symbol] = now

            # Bearish Trigger
            elif ema9 < ema21 and rsi > 32:
                sl = max(highs[-5:])  # Local swing high
                risk = sl - live_price
                if risk > 0:
                    tp = live_price - (risk * 1.5)  # 1:1.5 Risk-to-Reward Ratio

                    msg = (
                        f"🔴 *REAL-TIME BEARISH SETUP ({symbol.upper()})*\n\n"
                        f"• *Entry Price:* ${live_price:,.2f}\n"
                        f"• *Stop Loss (SL):* ${sl:,.2f}\n"
                        f"• *Take Profit (TP):* ${tp:,.2f} (1:1.5 RR)\n\n"
                        f"• *Signal:* 9 EMA crossed below 21 EMA\n"
                        f"• *RSI (14):* {rsi:.1f}"
                    )
                    send_telegram_alert(msg)
                    last_alert_time[symbol] = now


async def main():
    send_telegram_alert(
        "⚡ *Instant Trade Scanner Online*\nMonitoring live BTC & SOL trades with instant TP/SL setup generation."
    )
    await asyncio.gather(*(monitor_symbol(s) for s in SYMBOLS))


if __name__ == "__main__":
    asyncio.run(main())