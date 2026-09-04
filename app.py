import asyncio
import json
import os
import signal
import sys
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

# Maximum available leverage per asset
LEVERAGE_LIMITS = {"btcusdt": "1x - 200x", "solusdt": "1x - 20x"}

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


# --- SHUTDOWN & OFFLINE ALERTS ---
def handle_exit_signal(sig, frame):
    """Sends an emergency alert when Render stops or restarts the bot."""
    print("[SYSTEM] Exit signal received. Sending offline notification...")
    send_telegram_alert(
        "⚠️ *SYSTEM ALERT: Orochi Has Gone Offline*\n\n"
        "🔴 The scanner has stopped or is undergoing a redeploy on Render.\n"
        "Price streaming and active setup monitoring are temporarily inactive."
    )
    sys.exit(0)


# Register process termination signals for Render
signal.signal(signal.SIGINT, handle_exit_signal)
signal.signal(signal.SIGTERM, handle_exit_signal)


# --- TELEGRAM CONTROLS ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ACTIVE
    BOT_ACTIVE = True
    await update.message.reply_text(
        "🟢 *Orochi Framework Scanner Active*\nMonitoring market structure, high-gain setups (2-5%+), leverage parameters, and FVG zones.",
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
    if lows[-1] > highs[-3]:
        return "BULLISH_FVG", highs[-3], lows[-1]
    if highs[-1] < lows[-3]:
        return "BEARISH_FVG", lows[-3], highs[-1]
    return None, 0, 0


def detect_structure_break(highs, lows, closes):
    """Detects Break of Structure (BOS)."""
    recent_high = max(highs[-15:-2])
    recent_low = min(lows[-15:-2])
    current_close = closes[-1]

    if current_close > recent_high:
        return "BULLISH_BOS", recent_low
    if current_close < recent_low:
        return "BEARISH_BOS", recent_high

    return None, 0


def calculate_confidence(fvg_size_pct, sl_pct):
    """Calculates setup confidence based on FVG depth and tightness of invalidation."""
    confidence = 75

    if abs(sl_pct) < 0.5:
        confidence += 15
    elif abs(sl_pct) < 1.0:
        confidence += 10
    else:
        confidence += 5

    if fvg_size_pct > 0.15:
        confidence += 10

    return min(confidence, 98)


async def monitor_symbol(symbol):
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"

    async with websockets.connect(stream_url) as ws:
        print(f"[{symbol.upper()}] Orochi High-Target Stream Connected...")

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
            closes[-1] = live_price

            fvg_type, fvg_low, fvg_high = detect_fvg(opens, highs, lows, closes)
            structure_signal, invalidation_level = detect_structure_break(
                highs, lows, closes
            )
            max_leverage = LEVERAGE_LIMITS.get(symbol, "1x - 20x")

            # --- BULLISH SETUP (Targeting 2.5% to 5.0% gains) ---
            if structure_signal == "BULLISH_BOS" and fvg_type == "BULLISH_FVG":
                sl = invalidation_level

                # Scaled take-profit targets for high-gain unleveraged returns
                tp1 = live_price * 1.025  # +2.5% Gain
                tp2 = live_price * 1.050  # +5.0% Gain

                sl_pct = ((sl - live_price) / live_price) * 100
                tp1_pct = ((tp1 - live_price) / live_price) * 100
                tp2_pct = ((tp2 - live_price) / live_price) * 100

                risk_amt = live_price - sl
                reward_amt = tp1 - live_price
                rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 1.5

                fvg_size_pct = ((fvg_high - fvg_low) / fvg_low) * 100
                confidence = calculate_confidence(fvg_size_pct, sl_pct)

                msg = (
                    f"⚡ *OROCHI SMC BULLISH SETUP ({symbol.upper()})*\n"
                    f"🔥 *Signal:* Bullish BOS + High-Expansion FVG\n"
                    f"🎯 *Confidence Rate:* `{confidence}%`\n"
                    f"⚙️ *Available Leverage:* `{max_leverage}`\n\n"
                    f"• *Entry:* ${live_price:,.2f}\n"
                    f"• *Stop Loss:* ${sl:,.2f} ({sl_pct:.2f}%)\n\n"
                    f"🎯 *Take Profit 1 (50% position):* ${tp1:,.2f} (+{tp1_pct:.2f}%) | 1:{rr_ratio:.1f} RR\n"
                    f"🎯 *Take Profit 2 (50% position):* ${tp2:,.2f} (+{tp2_pct:.2f}%) | 1:{rr_ratio * 2:.1f} RR\n\n"
                    f"📍 *Fair Value Gap (FVG) Zone:* ${fvg_low:,.2f} - ${fvg_high:,.2f}"
                )
                send_telegram_alert(msg)
                last_alert_time[symbol] = now

            # --- BEARISH SETUP (Targeting 2.5% to 5.0% gains) ---
            elif (
                structure_signal == "BEARISH_BOS" and fvg_type == "BEARISH_FVG"
            ):
                sl = invalidation_level

                # Scaled take-profit targets for high-gain unleveraged returns
                tp1 = live_price * (1 - 0.025)  # +2.5% Gain
                tp2 = live_price * (1 - 0.050)  # +5.0% Gain

                sl_pct = ((live_price - sl) / live_price) * 100
                tp1_pct = ((live_price - tp1) / live_price) * 100
                tp2_pct = ((live_price - tp2) / live_price) * 100

                risk_amt = sl - live_price
                reward_amt = live_price - tp1
                rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 1.5

                fvg_size_pct = ((fvg_high - fvg_low) / fvg_low) * 100
                confidence = calculate_confidence(fvg_size_pct, sl_pct)

                msg = (
                    f"⚡ *OROCHI SMC BEARISH SETUP ({symbol.upper()})*\n"
                    f"📉 *Signal:* Bearish BOS + High-Expansion FVG\n"
                    f"🎯 *Confidence Rate:* `{confidence}%`\n"
                    f"⚙️ *Available Leverage:* `{max_leverage}`\n\n"
                    f"• *Entry:* ${live_price:,.2f}\n"
                    f"• *Stop Loss:* ${sl:,.2f} ({sl_pct:.2f}%)\n\n"
                    f"🎯 *Take Profit 1 (50% position):* ${tp1:,.2f} (+{tp1_pct:.2f}%) | 1:{rr_ratio:.1f} RR\n"
                    f"🎯 *Take Profit 2 (50% position):* ${tp2:,.2f} (+{tp2_pct:.2f}%) | 1:{rr_ratio * 2:.1f} RR\n\n"
                    f"📍 *Fair Value Gap (FVG) Zone:* ${fvg_high:,.2f} - ${fvg_low:,.2f}"
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
        "Monitoring real-time ticks. High-gain targets (+2.5% TP1, +5.0% TP2 unleveraged) and system failure/offline alerts active."
    )
    await asyncio.gather(*(monitor_symbol(s) for s in SYMBOLS))


if __name__ == "__main__":
    asyncio.run(main())