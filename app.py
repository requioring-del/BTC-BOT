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

MAX_ACTIVE_TRADES = 5
EXECUTION_TIMEFRAME = "5m"
BIAS_TIMEFRAME = "15m"

BOT_ACTIVE = True
COOLDOWN_SECONDS = 60
last_alert_time = {s: 0 for s in SYMBOLS}

DB_FILE = "positions.json"

# --- PERSISTENT STATE MANAGEMENT ---
def load_positions():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_positions():
    try:
        with open(DB_FILE, "w") as f:
            json.dump(active_positions, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save positions: {e}")


active_positions = load_positions()
latest_prices = {s: 0.0 for s in SYMBOLS}


def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"\n[ERROR] Telegram send error: {e}")


def handle_exit_signal(sig, frame):
    print("[SYSTEM] Exit signal received.")
    save_positions()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit_signal)
signal.signal(signal.SIGTERM, handle_exit_signal)


# --- TELEGRAM COMMAND HANDLERS ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ACTIVE
    BOT_ACTIVE = True
    await update.message.reply_text("🟢 *Orochi Position Manager Active*", parse_mode="Markdown")


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_ACTIVE
    BOT_ACTIVE = False
    await update.message.reply_text("🔴 *Orochi Position Manager Paused*", parse_mode="Markdown")


async def trades_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays real-time open positions, entry prices, and live P/L."""
    if not active_positions:
        await update.message.reply_text(
            f"ℹ️ *No active positions.* Searching for setups...\n"
            f"• *Slot Usage:* `0/{MAX_ACTIVE_TRADES}`\n"
            f"• *BTC Price:* `${latest_prices.get('btcusdt', 0):,.2f}`",
            parse_mode="Markdown"
        )
        return

    msg = f"📊 *ACTIVE POSITIONS ({len(active_positions)}/{MAX_ACTIVE_TRADES})*\n\n"
    for symbol, pos in list(active_positions.items()):
        curr_price = latest_prices.get(symbol, pos["entry"])
        direction = pos["type"]
        entry = pos["entry"]
        lev = pos["lev"]

        if direction == "BULLISH":
            pnl_pct = ((curr_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - curr_price) / entry) * 100

        roe = pnl_pct * lev
        status_icon = "🟢" if roe >= 0 else "🔴"

        msg += (
            f"{status_icon} *{symbol.upper()}* ({direction})\n"
            f"• *Entry:* ${entry:,.2f} | *Current:* ${curr_price:,.2f}\n"
            f"• *Leverage:* `{lev}x` | *Confidence:* `{pos.get('confidence', 85)}%`\n"
            f"• *Unrealized P/L:* `{pnl_pct:+.2f}%` (`{roe:+.2f}% ROE`)\n"
            f"• *SL:* ${pos['sl']:,.2f} | *TP3:* ${pos['tp3']:,.2f}\n\n"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")


async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually closes all tracked positions."""
    global active_positions
    count = len(active_positions)
    active_positions.clear()
    save_positions()
    await update.message.reply_text(
        f"🚨 *Closed all {count} active positions.* Trade slots reset to 0/{MAX_ACTIVE_TRADES}.",
        parse_mode="Markdown"
    )


async def force_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forces an instant scan of all assets without blocking."""
    await update.message.reply_text("🔍 *Running forced Orochi SMC Scan...*", parse_mode="Markdown")
    
    for symbol in SYMBOLS:
        live_price = latest_prices.get(symbol, 0)
        if live_price == 0:
            await update.message.reply_text(f"⚠️ *{symbol.upper()}:* Price feed establishing, try in 3 seconds...", parse_mode="Markdown")
            continue

        htf_highs, htf_lows, htf_closes = await fetch_klines(symbol, BIAS_TIMEFRAME)
        ltf_highs, ltf_lows, ltf_closes = await fetch_klines(symbol, EXECUTION_TIMEFRAME)

        if not htf_closes or not ltf_closes:
            continue

        htf_ema = calculate_ema(htf_closes, 20)
        bias_bullish = live_price > htf_ema
        bias_bearish = live_price < htf_ema

        ltf_closes[-1] = live_price
        signal_type, invalidation, confidence = evaluate_setup(ltf_highs, ltf_lows, ltf_closes, bias_bullish, bias_bearish)

        if signal_type == "BULLISH" and invalidation > 0:
            sl = invalidation
            risk = live_price - sl
            if risk > 0:
                sl_pct = (risk / live_price) * 100
                rec_leverage = min(max(int(5 / sl_pct), 2), 20)

                tp1 = live_price + (risk * 1.2)
                tp2 = live_price + (risk * 2.2)
                tp3 = live_price + (risk * 3.5)

                roe1 = (risk * 1.2 / live_price) * 100 * rec_leverage
                roe2 = (risk * 2.2 / live_price) * 100 * rec_leverage
                roe3 = (risk * 3.5 / live_price) * 100 * rec_leverage

                msg = (
                    f"⚡ *FORCED SETUP: BULLISH ({symbol.upper()})*\n"
                    f"🎯 *Confidence:* `{confidence}%`\n"
                    f"⚡ *Recommended Leverage:* `{rec_leverage}x` Cross\n\n"
                    f"• *Entry:* ${live_price:,.2f}\n"
                    f"• *Stop Loss:* ${sl:,.2f} (-{sl_pct:.2f}%)\n\n"
                    f"🎯 *TP 1 (25% position):* ${tp1:,.2f} (+{roe1:.1f}% ROE)\n"
                    f"🎯 *TP 2 (50% position):* ${tp2:,.2f} (+{roe2:.1f}% ROE)\n"
                    f"🎯 *TP 3 (25% position):* ${tp3:,.2f} (+{roe3:.1f}% ROE)\n\n"
                    f"🛡️ *Management:* Move SL to Breakeven after TP1 is hit."
                )
                await update.message.reply_text(msg, parse_mode="Markdown")

        elif signal_type == "BEARISH" and invalidation > 0:
            sl = invalidation
            risk = sl - live_price
            if risk > 0:
                sl_pct = (risk / live_price) * 100
                rec_leverage = min(max(int(5 / sl_pct), 2), 20)

                tp1 = live_price - (risk * 1.2)
                tp2 = live_price - (risk * 2.2)
                tp3 = live_price - (risk * 3.5)

                roe1 = (risk * 1.2 / live_price) * 100 * rec_leverage
                roe2 = (risk * 2.2 / live_price) * 100 * rec_leverage
                roe3 = (risk * 3.5 / live_price) * 100 * rec_leverage

                msg = (
                    f"⚡ *FORCED SETUP: BEARISH ({symbol.upper()})*\n"
                    f"🎯 *Confidence:* `{confidence}%`\n"
                    f"⚡ *Recommended Leverage:* `{rec_leverage}x` Cross\n\n"
                    f"• *Entry:* ${live_price:,.2f}\n"
                    f"• *Stop Loss:* ${sl:,.2f} (-{sl_pct:.2f}%)\n\n"
                    f"🎯 *TP 1 (25% position):* ${tp1:,.2f} (+{roe1:.1f}% ROE)\n"
                    f"🎯 *TP 2 (50% position):* ${tp2:,.2f} (+{roe2:.1f}% ROE)\n"
                    f"🎯 *TP 3 (25% position):* ${tp3:,.2f} (+{roe3:.1f}% ROE)\n\n"
                    f"🛡️ *Management:* Move SL to Breakeven after TP1 is hit."
                )
                await update.message.reply_text(msg, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"❌ *TRADE REFUSED ({symbol.upper()})*\n"
                f"• *Reason:* Insufficient market structure or low probability setup.",
                parse_mode="Markdown"
            )


# --- ASYNCHRONOUS DATA FETCHING ---
def _fetch_klines_sync(symbol, interval, limit=50):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5).json()
        highs = [float(c[2]) for c in res]
        lows = [float(c[3]) for c in res]
        closes = [float(c[4]) for c in res]
        return highs, lows, closes
    except Exception:
        return [], [], []


async def fetch_klines(symbol, interval, limit=50):
    return await asyncio.to_thread(_fetch_klines_sync, symbol, interval, limit)


# --- TECHNICAL ANALYSIS ENGINE ---
def calculate_ema(prices, period=20):
    if len(prices) < period:
        return prices[-1] if len(prices) > 0 else 0
    prices = np.array(prices, dtype=float)
    weights = np.exp(np.linspace(-1.0, 0.0, period))
    weights /= weights.sum()
    return float(np.convolve(prices, weights, mode="valid")[-1])


def evaluate_setup(highs, lows, closes, bias_bullish, bias_bearish):
    if len(closes) < 15:
        return None, 0, 0

    recent_high = max(highs[-15:-1])
    recent_low = min(lows[-15:-1])
    current_close = closes[-1]

    if bias_bullish and current_close >= recent_low:
        confidence = 82
        if current_close > recent_high:
            confidence += 10
        return "BULLISH", recent_low, confidence

    if bias_bearish and current_close <= recent_high:
        confidence = 84
        if current_close < recent_low:
            confidence += 10
        return "BEARISH", recent_high, confidence

    return None, 0, 0


def check_active_trade_exits(symbol, live_price):
    if symbol not in active_positions:
        return

    pos = active_positions[symbol]
    direction = pos["type"]
    sl = pos["sl"]
    tp3 = pos["tp3"]

    if direction == "BULLISH":
        if live_price <= sl:
            send_telegram_alert(f"🔴 *STOP LOSS HIT ({symbol.upper()})*\nClosed position at ${live_price:,.2f}.")
            del active_positions[symbol]
            save_positions()
        elif live_price >= tp3:
            send_telegram_alert(f"🎯 *TP3 HIT ({symbol.upper()})*\nFully closed trade at ${live_price:,.2f}.")
            del active_positions[symbol]
            save_positions()

    elif direction == "BEARISH":
        if live_price >= sl:
            send_telegram_alert(f"🔴 *STOP LOSS HIT ({symbol.upper()})*\nClosed position at ${live_price:,.2f}.")
            del active_positions[symbol]
            save_positions()
        elif live_price <= tp3:
            send_telegram_alert(f"🎯 *TP3 HIT ({symbol.upper()})*\nFully closed trade at ${live_price:,.2f}.")
            del active_positions[symbol]
            save_positions()


async def monitor_symbol(symbol):
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@trade"

    while True:
        try:
            async with websockets.connect(stream_url, ping_interval=20, ping_timeout=10) as ws:
                print(f"[{symbol.upper()}] Real-time stream active.")

                while True:
                    response = await ws.recv()
                    if not BOT_ACTIVE:
                        await asyncio.sleep(1)
                        continue

                    data = json.loads(response)
                    live_price = float(data["p"])
                    latest_prices[symbol] = live_price

                    check_active_trade_exits(symbol, live_price)

                    if len(active_positions) >= MAX_ACTIVE_TRADES or symbol in active_positions:
                        await asyncio.sleep(0.2)
                        continue

                    now = time.time()
                    if now - last_alert_time[symbol] < COOLDOWN_SECONDS:
                        await asyncio.sleep(0.2)
                        continue

                    htf_highs, htf_lows, htf_closes = await fetch_klines(symbol, BIAS_TIMEFRAME)
                    ltf_highs, ltf_lows, ltf_closes = await fetch_klines(symbol, EXECUTION_TIMEFRAME)

                    if not htf_closes or not ltf_closes:
                        continue

                    htf_ema = calculate_ema(htf_closes, 20)
                    bias_bullish = live_price > htf_ema
                    bias_bearish = live_price < htf_ema

                    ltf_closes[-1] = live_price
                    signal_type, invalidation, confidence = evaluate_setup(ltf_highs, ltf_lows, ltf_closes, bias_bullish, bias_bearish)

                    if signal_type == "BULLISH" and invalidation > 0:
                        sl = invalidation
                        risk = live_price - sl
                        if risk > 0:
                            sl_pct = (risk / live_price) * 100

                            if 0.05 <= sl_pct <= 2.5:
                                rec_leverage = min(max(int(5 / sl_pct), 2), 20)

                                tp1 = live_price + (risk * 1.2)
                                tp2 = live_price + (risk * 2.2)
                                tp3 = live_price + (risk * 3.5)

                                roe1 = (risk * 1.2 / live_price) * 100 * rec_leverage
                                roe2 = (risk * 2.2 / live_price) * 100 * rec_leverage
                                roe3 = (risk * 3.5 / live_price) * 100 * rec_leverage

                                active_positions[symbol] = {
                                    "type": "BULLISH",
                                    "entry": live_price,
                                    "sl": sl,
                                    "tp1": tp1,
                                    "tp2": tp2,
                                    "tp3": tp3,
                                    "lev": rec_leverage,
                                    "confidence": confidence
                                }
                                save_positions()

                                msg = (
                                    f"⚡ *OROCHI SMC BULLISH SETUP ({symbol.upper()})*\n"
                                    f"📌 *Active Slots:* `{len(active_positions)}/{MAX_ACTIVE_TRADES}`\n"
                                    f"🎯 *Confidence Rate:* `{confidence}%`\n"
                                    f"⏳ *Timeframe:* `{EXECUTION_TIMEFRAME}` | *Bias:* `{BIAS_TIMEFRAME}`\n"
                                    f"⚡ *Leverage:* `{rec_leverage}x` Cross\n\n"
                                    f"• *Entry:* ${live_price:,.2f}\n"
                                    f"• *Stop Loss:* ${sl:,.2f} (-{sl_pct:.2f}%)\n\n"
                                    f"🎯 *TP 1 (25% position):* ${tp1:,.2f} (+{roe1:.1f}% ROE)\n"
                                    f"🎯 *TP 2 (50% position):* ${tp2:,.2f} (+{roe2:.1f}% ROE)\n"
                                    f"🎯 *TP 3 (25% position):* ${tp3:,.2f} (+{roe3:.1f}% ROE)\n\n"
                                    f"🛡️ *Management:* Move SL to Breakeven after TP1 is hit."
                                )
                                send_telegram_alert(msg)
                                last_alert_time[symbol] = now

                    elif signal_type == "BEARISH" and invalidation > 0:
                        sl = invalidation
                        risk = sl - live_price
                        if risk > 0:
                            sl_pct = (risk / live_price) * 100

                            if 0.05 <= sl_pct <= 2.5:
                                rec_leverage = min(max(int(5 / sl_pct), 2), 20)

                                tp1 = live_price - (risk * 1.2)
                                tp2 = live_price - (risk * 2.2)
                                tp3 = live_price - (risk * 3.5)

                                roe1 = (risk * 1.2 / live_price) * 100 * rec_leverage
                                roe2 = (risk * 2.2 / live_price) * 100 * rec_leverage
                                roe3 = (risk * 3.5 / live_price) * 100 * rec_leverage

                                active_positions[symbol] = {
                                    "type": "BEARISH",
                                    "entry": live_price,
                                    "sl": sl,
                                    "tp1": tp1,
                                    "tp2": tp2,
                                    "tp3": tp3,
                                    "lev": rec_leverage,
                                    "confidence": confidence
                                }
                                save_positions()

                                msg = (
                                    f"⚡ *OROCHI SMC BEARISH SETUP ({symbol.upper()})*\n"
                                    f"📌 *Active Slots:* `{len(active_positions)}/{MAX_ACTIVE_TRADES}`\n"
                                    f"🎯 *Confidence Rate:* `{confidence}%`\n"
                                    f"⏳ *Timeframe:* `{EXECUTION_TIMEFRAME}` | *Bias:* `{BIAS_TIMEFRAME}`\n"
                                    f"⚡ *Leverage:* `{rec_leverage}x` Cross\n\n"
                                    f"• *Entry:* ${live_price:,.2f}\n"
                                    f"• *Stop Loss:* ${sl:,.2f} (-{sl_pct:.2f}%)\n\n"
                                    f"🎯 *TP 1 (25% position):* ${tp1:,.2f} (+{roe1:.1f}% ROE)\n"
                                    f"🎯 *TP 2 (50% position):* ${tp2:,.2f} (+{roe2:.1f}% ROE)\n"
                                    f"🎯 *TP 3 (25% position):* ${tp3:,.2f} (+{roe3:.1f}% ROE)\n\n"
                                    f"🛡️ *Management:* Move SL to Breakeven after TP1 is hit."
                                )
                                send_telegram_alert(msg)
                                last_alert_time[symbol] = now

        except Exception as e:
            print(f"[{symbol.upper()}] Stream reconnecting ({e})...")
            await asyncio.sleep(3)


async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("botstart", start_cmd))
    app.add_handler(CommandHandler("botstop", stop_cmd))
    app.add_handler(CommandHandler("trades", trades_cmd))
    app.add_handler(CommandHandler("close", close_cmd))
    app.add_handler(CommandHandler("force", force_cmd))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    for symbol in SYMBOLS:
        asyncio.create_task(monitor_symbol(symbol))

    send_telegram_alert("🐉 *Orochi Position Manager Fixed*\nState persistence enabled & non-blocking /force implemented.")

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())