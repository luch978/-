import requests
import asyncio
import time
import traceback
import nest_asyncio

nest_asyncio.apply()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = "7704135885:AAHU3UbcYckiwq1iVxzWLtlUeFQFwi45gWM"
CHAT_ID = 52119049

BASE = "https://fapi.binance.com"

settings = {
    "pump": {
        "price": 0.1,
        "time": 5,
        "volume": 0.1,
        "oi": 0.1,
        "active": True,
    },
    "dump": {
        "pump_before": 10.0,
        "time": 20,
        "rsi": 80.0,
        "active": False,
    },
}

waiting_for = {}
last_signal = {}
cooldown_seconds = 600
last_scan_info = {
    "symbols": 0,
    "last_error": "None",
    "last_scan": "Not started",
}


def log_error(name, e):
    text = f"{name}: {e}"
    print(text)
    last_scan_info["last_error"] = text


def safe_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        if isinstance(data, dict) and "code" in data and "msg" in data:
            print("BINANCE ERROR:", data)
            last_scan_info["last_error"] = str(data)
            return None

        if isinstance(data, str):
            print("BINANCE STRING ERROR:", data)
            last_scan_info["last_error"] = data
            return None

        return data

    except Exception as e:
        log_error("REQUEST ERROR", e)
        return None


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PUMP SETTINGS", callback_data="pump_menu")],
        [InlineKeyboardButton("DUMP SETTINGS", callback_data="dump_menu")],
        [InlineKeyboardButton("STATUS", callback_data="status")],
    ])


def pump_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PRICE %", callback_data="pump_price")],
        [InlineKeyboardButton("TIME MIN", callback_data="pump_time")],
        [InlineKeyboardButton("VOLUME X", callback_data="pump_volume")],
        [InlineKeyboardButton("OI %", callback_data="pump_oi")],
        [InlineKeyboardButton("START", callback_data="pump_start")],
        [InlineKeyboardButton("STOP", callback_data="pump_stop")],
        [InlineKeyboardButton("BACK", callback_data="main")],
    ])


def dump_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PUMP BEFORE %", callback_data="dump_pump_before")],
        [InlineKeyboardButton("TIME MIN", callback_data="dump_time")],
        [InlineKeyboardButton("RSI", callback_data="dump_rsi")],
        [InlineKeyboardButton("START", callback_data="dump_start")],
        [InlineKeyboardButton("STOP", callback_data="dump_stop")],
        [InlineKeyboardButton("BACK", callback_data="main")],
    ])


def status_text():
    return f"""
PUMP EARLY
Price: {settings["pump"]["price"]}%
Time: {settings["pump"]["time"]} min
Volume X: {settings["pump"]["volume"]}
OI: {settings["pump"]["oi"]}%
Active: {settings["pump"]["active"]}

DUMP OVERHEAT
Pump before: {settings["dump"]["pump_before"]}%
Time: {settings["dump"]["time"]} min
RSI: {settings["dump"]["rsi"]}
Active: {settings["dump"]["active"]}

SCANNER
Symbols: {last_scan_info["symbols"]}
Last scan: {last_scan_info["last_scan"]}
Last error: {last_scan_info["last_error"]}
"""


def get_symbols():
    data = safe_json(BASE + "/fapi/v1/ticker/24hr")

    if not isinstance(data, list):
        print("SCANNING: 0 symbols")
        last_scan_info["symbols"] = 0
        return []

    coins = []

    for x in data:
        if not isinstance(x, dict):
            continue

        symbol = x.get("symbol")
        volume = x.get("quoteVolume")

        if symbol and symbol.endswith("USDT"):
            try:
                coins.append((symbol, float(volume)))
            except:
                pass

    coins = sorted(coins, key=lambda x: x[1], reverse=True)
    result = [x[0] for x in coins[:120]]

    last_scan_info["symbols"] = len(result)
    return result


def get_klines(symbol, limit):
    data = safe_json(BASE + "/fapi/v1/klines", {
        "symbol": symbol,
        "interval": "1m",
        "limit": limit,
    })

    if not isinstance(data, list):
        return []

    return data


def get_price_change(symbol, minutes):
    data = get_klines(symbol, minutes + 1)

    if len(data) < 2:
        return 0, 0

    try:
        old_price = float(data[0][4])
        new_price = float(data[-1][4])

        if old_price == 0:
            return 0, new_price

        change = ((new_price - old_price) / old_price) * 100
        return change, new_price

    except Exception as e:
        log_error("PRICE ERROR", e)
        return 0, 0


def get_volume_spike(symbol):
    data = get_klines(symbol, 21)

    if len(data) < 21:
        return 0

    try:
        current_volume = float(data[-1][7])
        avg_volume = sum(float(c[7]) for c in data[:-1]) / 20

        if avg_volume == 0:
            return 0

        return current_volume / avg_volume

    except Exception as e:
        log_error("VOLUME ERROR", e)
        return 0


def rsi_calc(closes, period=14):
    if len(closes) < period + 1:
        return 0

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]

        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_rsi(symbol):
    data = get_klines(symbol, 20)

    try:
        closes = [float(c[4]) for c in data]
        return rsi_calc(closes)

    except Exception as e:
        log_error("RSI ERROR", e)
        return 0


def oi_period(minutes):
    if minutes <= 5:
        return "5m"
    if minutes <= 15:
        return "15m"
    if minutes <= 30:
        return "30m"
    if minutes <= 60:
        return "1h"
    return "4h"


def get_oi_change(symbol, minutes):
    data = safe_json(BASE + "/futures/data/openInterestHist", {
        "symbol": symbol,
        "period": oi_period(minutes),
        "limit": 2,
    })

    if not isinstance(data, list) or len(data) < 2:
        return 0

    try:
        old_oi = float(data[0]["sumOpenInterest"])
        new_oi = float(data[1]["sumOpenInterest"])

        if old_oi == 0:
            return 0

        return ((new_oi - old_oi) / old_oi) * 100

    except Exception as e:
        log_error("OI ERROR", e)
        return 0


def get_funding(symbol):
    data = safe_json(BASE + "/fapi/v1/premiumIndex", {"symbol": symbol})

    if not isinstance(data, dict):
        return 0

    try:
        return float(data.get("lastFundingRate", 0)) * 100

    except:
        return 0


def get_density(symbol):
    data = safe_json(BASE + "/fapi/v1/depth", {
        "symbol": symbol,
        "limit": 100,
    })

    if not isinstance(data, dict):
        return 0, 0, 0, 0

    try:
        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return 0, 0, 0, 0

        biggest_bid = max(bids, key=lambda x: float(x[0]) * float(x[1]))
        biggest_ask = max(asks, key=lambda x: float(x[0]) * float(x[1]))

        bid_price = float(biggest_bid[0])
        bid_usdt = float(biggest_bid[0]) * float(biggest_bid[1])

        ask_price = float(biggest_ask[0])
        ask_usdt = float(biggest_ask[0]) * float(biggest_ask[1])

        return bid_price, bid_usdt, ask_price, ask_usdt

    except Exception as e:
        log_error("DENSITY ERROR", e)
        return 0, 0, 0, 0


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("SCREENER MENU", reply_markup=main_menu())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(status_text(), reply_markup=main_menu())


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "main":
        await query.edit_message_text("SCREENER MENU", reply_markup=main_menu())

    elif data == "pump_menu":
        await query.edit_message_text("PUMP EARLY SETTINGS", reply_markup=pump_menu())

    elif data == "dump_menu":
        await query.edit_message_text("DUMP OVERHEAT SETTINGS", reply_markup=dump_menu())

    elif data == "status":
        await query.edit_message_text(status_text(), reply_markup=main_menu())

    elif data.endswith("_start"):
        mode = data.split("_")[0]
        settings[mode]["active"] = True
        await query.edit_message_text(
            f"{mode.upper()} STARTED",
            reply_markup=pump_menu() if mode == "pump" else dump_menu(),
        )

    elif data.endswith("_stop"):
        mode = data.split("_")[0]
        settings[mode]["active"] = False
        await query.edit_message_text(
            f"{mode.upper()} STOPPED",
            reply_markup=pump_menu() if mode == "pump" else dump_menu(),
        )

    elif data.startswith("pump_"):
        key = data.replace("pump_", "")
        waiting_for[query.message.chat_id] = ("pump", key)
        await query.message.reply_text(f"SEND PUMP {key.upper()}")

    elif data.startswith("dump_"):
        key = data.replace("dump_", "")
        waiting_for[query.message.chat_id] = ("dump", key)
        await query.message.reply_text(f"SEND DUMP {key.upper()}")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    if chat_id not in waiting_for:
        return

    mode, key = waiting_for[chat_id]

    try:
        value = float(update.message.text)

        if key == "time":
            value = int(value)

        settings[mode][key] = value
        del waiting_for[chat_id]

        await update.message.reply_text(
            f"SAVED {mode.upper()} {key} = {value}",
            reply_markup=pump_menu() if mode == "pump" else dump_menu(),
        )

    except:
        await update.message.reply_text("SEND ONLY NUMBER")


async def scanner(app):
    await asyncio.sleep(5)

    while True:
        try:
            last_scan_info["last_scan"] = time.strftime("%H:%M:%S")
            symbols = get_symbols()

            print(f"SCANNING: {len(symbols)} symbols")

            if len(symbols) == 0:
                await asyncio.sleep(30)
                continue

            for symbol in symbols:
                now = time.time()

                if settings["pump"]["active"]:
                    s = settings["pump"]
                    key = "pump_" + symbol

                    if key not in last_signal or now - last_signal[key] > cooldown_seconds:
                        price_change, last_price = get_price_change(symbol, s["time"])
                        volume_x = get_volume_spike(symbol)
                        oi_change = get_oi_change(symbol, s["time"])

                        if (
                            price_change >= s["price"]
                            and volume_x >= s["volume"]
                            and oi_change >= s["oi"]
                        ):
                            funding = get_funding(symbol)
                            bid_price, bid_usdt, ask_price, ask_usdt = get_density(symbol)

                            msg = f"""
PUMP EARLY SIGNAL

Coin: {symbol}
Price: {round(price_change, 2)}% / {s["time"]} min
Volume spike: x{round(volume_x, 2)}
OI: {round(oi_change, 2)}%
Funding: {round(funding, 4)}%
Last price: {last_price}

Density below:
{bid_price} / ${round(bid_usdt)}

Density above:
{ask_price} / ${round(ask_usdt)}

Reason:
Early move + volume spike + OI growth
"""
                            await app.bot.send_message(chat_id=CHAT_ID, text=msg)
                            last_signal[key] = now

                if settings["dump"]["active"]:
                    s = settings["dump"]
                    key = "dump_" + symbol

                    if key not in last_signal or now - last_signal[key] > cooldown_seconds:
                        price_change, last_price = get_price_change(symbol, s["time"])
                        rsi = get_rsi(symbol)

                        if price_change >= s["pump_before"] and rsi >= s["rsi"]:
                            funding = get_funding(symbol)
                            bid_price, bid_usdt, ask_price, ask_usdt = get_density(symbol)

                            msg = f"""
DUMP OVERHEAT WATCH

Coin: {symbol}
Pump: {round(price_change, 2)}% / {s["time"]} min
RSI: {round(rsi, 2)}
Funding: {round(funding, 4)}%
Last price: {last_price}

Density below:
{bid_price} / ${round(bid_usdt)}

Density above:
{ask_price} / ${round(ask_usdt)}

Reason:
Strong pump + overbought RSI
"""
                            await app.bot.send_message(chat_id=CHAT_ID, text=msg)
                            last_signal[key] = now

                await asyncio.sleep(0.1)

        except Exception as e:
            print("SCANNER ERROR:", e)
            print(traceback.format_exc())
            last_scan_info["last_error"] = str(e)

        await asyncio.sleep(30)


async def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except:
        pass

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    asyncio.create_task(scanner(app))

    print("BOT STARTED")

    while True:
        await asyncio.sleep(3600)


try:
    asyncio.run(main())
except Conflict:
    print("TELEGRAM CONFLICT: another bot instance is running. Stop other copies.")
except Exception as e:
    print("FATAL ERROR:", e)
    print(traceback.format_exc())
