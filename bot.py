import requests
import asyncio
import time

proxies = {
    "http": "http://z8Nfpp:87j2oy@185.240.94.115:8000",
    "https": "http://z8Nfpp:87j2oy@185.240.94.115:8000"
}

session = requests.Session()
session.proxies.update(proxies)
requests = session

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = "7704135885:AAHU3UbcYckiwq1iVxzWLtlUeFQFwi45gWM"
CHAT_ID = 52119049
BASE = "https://fapi.binance.com"

settings = {

    "pump": {
        "price": 1.0,
        "time": 5,
        "volume": 3.0,
        "oi": 0.5,
        "active": False
    },

    "dump": {
        "pump_before": 10.0,
        "time": 20,
        "rsi": 80.0,
        "active": False
    },

    "vol": {
        "tf": "3m",
        "candles": 5,
        "max_old_volume": 700000,
        "min_new_volume": 2000000,
        "active": False
    }

}

waiting_for = {}
last_signal = {}
cooldown_seconds = 600


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PUMP SETTINGS", callback_data="pump_menu")],
        [InlineKeyboardButton("DUMP SETTINGS", callback_data="dump_menu")],
        [InlineKeyboardButton("VOL SETTINGS", callback_data="vol_menu")],
        [InlineKeyboardButton("STATUS", callback_data="status")]
    ])


def pump_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PRICE %", callback_data="pump_price")],
        [InlineKeyboardButton("TIME MIN", callback_data="pump_time")],
        [InlineKeyboardButton("VOLUME X", callback_data="pump_volume")],
        [InlineKeyboardButton("OI %", callback_data="pump_oi")],
        [InlineKeyboardButton("START", callback_data="pump_start")],
        [InlineKeyboardButton("STOP", callback_data="pump_stop")],
        [InlineKeyboardButton("BACK", callback_data="main")]
    ])


def dump_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PUMP BEFORE %", callback_data="dump_pump_before")],
        [InlineKeyboardButton("TIME MIN", callback_data="dump_time")],
        [InlineKeyboardButton("RSI", callback_data="dump_rsi")],
        [InlineKeyboardButton("START", callback_data="dump_start")],
        [InlineKeyboardButton("STOP", callback_data="dump_stop")],
        [InlineKeyboardButton("BACK", callback_data="main")]
    ])


def vol_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("TIMEFRAME", callback_data="vol_tf")],
        [InlineKeyboardButton("CANDLES", callback_data="vol_candles")],
        [InlineKeyboardButton("MAX OLD VOL", callback_data="vol_max_old_volume")],
        [InlineKeyboardButton("MIN NEW VOL", callback_data="vol_min_new_volume")],
        [InlineKeyboardButton("START", callback_data="vol_start")],
        [InlineKeyboardButton("STOP", callback_data="vol_stop")],
        [InlineKeyboardButton("BACK", callback_data="main")]
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

VOLUME SPIKE
TF: {settings["vol"]["tf"]}
Candles: {settings["vol"]["candles"]}
Old volume <= {settings["vol"]["max_old_volume"]}
New volume >= {settings["vol"]["min_new_volume"]}
Active: {settings["vol"]["active"]}
"""


def get_symbols():
    data = requests.get(BASE + "/fapi/v1/ticker/24hr", timeout=10).json()

    coins = []

    for x in data:
        if x["symbol"].endswith("USDT"):
            coins.append((x["symbol"], float(x["quoteVolume"])))

    coins.sort(key=lambda x: x[1], reverse=True)

    return [x[0] for x in coins[:120]]


def get_klines(symbol, limit):
    params = {
        "symbol": symbol,
        "interval": "1m",
        "limit": limit
    }

    return requests.get(
        BASE + "/fapi/v1/klines",
        params=params,
        timeout=10
    ).json()

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "main":
        await query.edit_message_text(
            "SCREENER MENU",
            reply_markup=main_menu()
        )

    elif data == "pump_menu":
        await query.edit_message_text(
            "PUMP EARLY SETTINGS",
            reply_markup=pump_menu()
        )

    elif data == "dump_menu":
        await query.edit_message_text(
            "DUMP OVERHEAT SETTINGS",
            reply_markup=dump_menu()
        )

    elif data == "vol_menu":
        await query.edit_message_text(
            "VOLUME SPIKE SETTINGS",
            reply_markup=vol_menu()
        )

    elif data == "status":
        await query.edit_message_text(
            status_text(),
            reply_markup=main_menu()
        )

    elif data.endswith("_start"):
        mode = data.split("_")[0]
        settings[mode]["active"] = True

        if mode == "pump":
            menu = pump_menu()
        elif mode == "dump":
            menu = dump_menu()
        else:
            menu = vol_menu()

        await query.edit_message_text(
            f"{mode.upper()} STARTED",
            reply_markup=menu
        )

    elif data.endswith("_stop"):
        mode = data.split("_")[0]
        settings[mode]["active"] = False

        if mode == "pump":
            menu = pump_menu()
        elif mode == "dump":
            menu = dump_menu()
        else:
            menu = vol_menu()

        await query.edit_message_text(
            f"{mode.upper()} STOPPED",
            reply_markup=menu
        )

    elif data.startswith("pump_"):
        key = data.replace("pump_", "")
        waiting_for[query.message.chat_id] = ("pump", key)
        await query.message.reply_text(f"SEND PUMP {key.upper()}")

    elif data.startswith("dump_"):
        key = data.replace("dump_", "")
        waiting_for[query.message.chat_id] = ("dump", key)
        await query.message.reply_text(f"SEND DUMP {key.upper()}")

    elif data.startswith("vol_"):
        key = data.replace("vol_", "")

        if key in ["start", "stop"]:
            return

        waiting_for[query.message.chat_id] = ("vol", key)

        if key == "tf":
            await query.message.reply_text("SEND: 1m, 3m or 5m")
        else:
            await query.message.reply_text(f"SEND VOL {key.upper()}")

elif data.startswith("vol_"):
    key = data.replace("vol_", "")

    if key in ["start", "stop"]:
        return

    waiting_for[query.message.chat_id] = ("vol", key)

    if key == "tf":
        await query.message.reply_text("SEND 1m, 3m or 5m")
    else:
        await query.message.reply_text(f"SEND VOL {key.upper()}")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    if chat_id not in waiting_for:
        return

    mode, key = waiting_for[chat_id]

    try:

        if key == "tf":
            value = update.message.text.strip()

            if value not in ["1m", "3m", "5m"]:
                await update.message.reply_text("ONLY: 1m, 3m or 5m")
                return

        else:
            value = float(update.message.text)

            if key == "candles":
                value = int(value)

            if key == "time":
                value = int(value)

        settings[mode][key] = value

        del waiting_for[chat_id]

        if mode == "pump":
            menu = pump_menu()
        elif mode == "dump":
            menu = dump_menu()
        else:
            menu = vol_menu()

        await update.message.reply_text(
            f"SAVED {mode.upper()} {key} = {value}",
            reply_markup=menu
        )

    except:
        await update.message.reply_text("SEND ONLY NUMBER")
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

                await asyncio.sleep(0.15)

        except Exception as e:
            print("ERROR:", e)

        await asyncio.sleep(30)

async def post_init(app):
    asyncio.create_task(scanner(app))

app = Application.builder().token(TOKEN).post_init(post_init).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

print("BOT STARTED")
app.run_polling()
