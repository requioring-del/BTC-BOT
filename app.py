import asyncio
import json
import os
import time
import numpy as np
import requests
import websockets
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", "8811292743:AAEJBiVXN7j0hysvOpx7TjqHnN44goXX_-o"
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8695599623")
SYMBOLS = ["btcusdt", "solusdt"]

BOT_ACTIVE = True
COOLDOWN_SECONDS = 300
last_alert_time = {"btcusdt": 0, "solusdt": 0}


def send_telegram_alert(message):
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


# --- TELEGRAM CONTROLS ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ACTIVE
    BOT_ACTIVE = True
    await update.message.reply_text(
        "🟢 *Orochi Framework Scanner Active*\nMonitoring market structure, FVGs, and Order Blocks.",
        parse_mode="Markdown",
    )


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ACTIVE
    BOT_ACTIVE = False
    await update.message.reply_text(
        "🔴 *Orochi Framework Scanner Paused*\nNotifications disabled.",
        parse_mode="Markdown",
    )


# --- OROCHI / SMC ANALYSIS ENGINE ---
def fetch_klines(symbol, limit=50):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval=1m&limit={limit}"
    res = requests.get(url).json()
    opens = [float(c[1]) for c in res]
    highs = [float(c[2]) for c in res]
    lows = [float(c[3]) for c in res]
    closes = [float(c[4]) for c in res]
    return opens, highs, lows, closes


def detect_fvg(opens, highs, lows, closes):
    """Detects Bullish or Bearish Fair Value Gaps in recent candles."""
    # Bullish FVG: Low of candle[i] > High of candle[i-2]
    if lows[-1] > highs[-3]:
        return "BULLISH_FVG", highs[-3], lows[-1]
    # Bearish FVG: High of candle[i] < Low of candle[i-2]
    if highs[-1] < lows[-3]:
        return "BEARISH_FVG", lows[-3], highs[-1]
    return None, 0, 0


def detect_structure_break(highs, lows, closes):
    """Detects Break of Structure (BOS) or Change of Character (CHoCH)."""
    recent_high = max(highs[-15:-2])
    recent_low = min(lows[-15:-2])
    current_close = closes[-1]

    if current_close > recent_high:
        return "BULLISH_BOS", recent_low
    if current_close < recent_low:
        return "BEARISH_BOS", recent_high

    return None, 0


async def monitor_symbol(symbol):
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"

    async with websockets.connect(stream_url) as ws:
        print(f"[{symbol.upper()}] Orochi Structure Stream Connected...")

        while True:
            response = await ws.recv()
            if not BOT_ACTIVE:
                await asyncio.sleep(1)
                continue

            data = json.loads(response)
            live_price = float(data["p"])

            now = time.time()
            if now - last_alert_time[symbol] < COOLDOWN_SECONDS:
                continue

            opens, highs, lows, closes = fetch_klines(symbol)
            closes[-1] = live_price  # Bind live price to active candle

            fvg_type, fvg_low, fvg_high = detect_fvg(opens, highs, lows, closes)
            structure_signal, invalidation_level = detect_structure_break(
                highs, lows, closes
            )

            # --- BULLISH SETUP: Bullish BOS + Bullish FVG ---
            if structure_signal == "BULLISH_BOS" and fvg_type == "BULLISH_FVG":
                sl = invalidation_level
                risk = live_price - sl
                if risk > 0:
                    tp = live_price + (risk * 1.5)
                    msg = (
                        f"⚡ *OROCHI SMC SETUP ({symbol.upper()})*\n"
                        f"🔥 *Signal:* Bullish BOS + FVG Expansion\n\n"
                        f"• *Entry:* ${live_price:,.2f}\n"
                        f"• *Stop Loss:* ${sl:,.2f} (Swing Low)\n"
                        f"• *Take Profit:* ${tp:,.2f} (1:1.5 RR)\n\n"
                        f"• *FVG Imbalance Zone:* ${fvg_low:,.2f} - ${fvg_high:,.2f}"
                    )
                    send_telegram_alert(msg)
                    last_alert_time[symbol] = now

            # --- BEARISH SETUP: Bearish BOS + Bearish FVG ---
            elif (
                structure_signal == "BEARISH_BOS" and fvg_type == "BEARISH_FVG"
            ):
                sl = invalidation_level
                risk = sl - live_price
                if risk > 0:
                    tp = live_price - (risk * 1.5)
                    msg = (
                        f"⚡ *OROCHI SMC SETUP ({symbol.upper()})*\n"
                        f"📉 *Signal:* Bearish BOS + FVG Expansion\n\n"
                        f"• *Entry:* ${live_price:,.2f}\n"
                        f"• *Stop Loss:* ${sl:,.2f} (Swing High)\n"
                        f"• *Take Profit:* ${tp:,.2f} (1:1.5 RR)\n\n"
                        f"• *FVG Imbalance Zone:* ${fvg_high:,.2f} - ${fvg_low:,.2f}"
                    )
                    send_telegram_alert(msg)
                    last_alert_time[symbol] = now


async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("botstart", start_cmd))
    app.add_handler(CommandHandler("botstop", stop_cmd))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    send_telegram_alert(
        "🐉 *Orochi Framework Online*\n"
        "Scanning real-time market structure, liquidity sweeps & FVGs."
    )
    await asyncio.gather(*(monitor_symbol(s) for s in SYMBOLS))


if __name__ == "__main__":
    asyncio.run(main())