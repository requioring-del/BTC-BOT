import asyncio
import json
import os
import numpy as np
import requests
import websockets

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8695599623")

# Monitor multiple symbols
SYMBOLS = ["btcusdt", "solusdt"]


def send_telegram_alert(message):
    """Sends trade signal alerts to Telegram."""
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
    """Calculates Exponential Moving Average."""
    prices = np.array(prices, dtype=float)
    weights = np.exp(np.linspace(-1.0, 0.0, period))
    weights /= weights.sum()
    ema = np.convolve(prices, weights, mode="full")[: len(prices)]
    ema[:period] = ema[period]
    return ema[-1]


def calculate_rsi(prices, period=14):
    """Calculates Relative Strength Index."""
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


async def fetch_historical_closes(symbol):
    """Fetches last 50 closed 15m candles from Binance API."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval=15m&limit=50"
    res = requests.get(url).json()
    # Extract closing prices (index 4 in Binance kline response)
    closes = [float(candle[4]) for candle in res]
    return closes


async def monitor_symbol(symbol):
    # Binance websocket streams 15m candle updates
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@kline_15m"

    async with websockets.connect(stream_url) as ws:
        print(f"[{symbol.upper()}] Monitoring 15m signals...")

        while True:
            response = await ws.recv()
            data = json.loads(response)
            kline = data["k"]

            # Only calculate on candle CLOSE ('x': True)
            if kline["x"]:
                closes = await fetch_historical_closes(symbol)
                price = closes[-1]

                ema9 = calculate_ema(closes, 9)
                ema21 = calculate_ema(closes, 21)
                rsi = calculate_rsi(closes, 14)

                # Bullish Crossover (EMA9 > EMA21 and RSI not overbought)
                if ema9 > ema21 and rsi < 68:
                    msg = (
                        f"🟢 *BULLISH TRADE SETUP ({symbol.upper()})*\n\n"
                        f"• *Price:* ${price:,.2f}\n"
                        f"• *Signal:* 9 EMA crossed above 21 EMA\n"
                        f"• *RSI (14):* {rsi:.1f} (Healthy Momentum)\n"
                        f"• *Timeframe:* 15m Candle Close"
                    )
                    send_telegram_alert(msg)

                # Bearish Crossover (EMA9 < EMA21 and RSI not oversold)
                elif ema9 < ema21 and rsi > 32:
                    msg = (
                        f"🔴 *BEARISH TRADE SETUP ({symbol.upper()})*\n\n"
                        f"• *Price:* ${price:,.2f}\n"
                        f"• *Signal:* 9 EMA crossed below 21 EMA\n"
                        f"• *RSI (14):* {rsi:.1f} (Downside Momentum)\n"
                        f"• *Timeframe:* 15m Candle Close"
                    )
                    send_telegram_alert(msg)


async def main():
    send_telegram_alert(
        "🚀 *Trade Setup Bot Online*\nMonitoring BTC & SOL on 15m timeframe."
    )
    # Run streams concurrently for BTC and SOL
    await asyncio.gather(*(monitor_symbol(s) for s in SYMBOLS))


if __name__ == "__main__":
    asyncio.run(main())