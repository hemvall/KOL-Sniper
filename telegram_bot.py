import os
import re
import logging
import asyncio
from typing import Optional

import requests
import shlex
import io
import contextlib
import csv

import logger as trade_logger
from dotenv import load_dotenv
from telegram import __version__ as ptb_version
from telegram import InputMediaPhoto, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN_REGEX = re.compile(r"0x[a-fA-F0-9]{40}")
COINGECKO_CONTRACT_URL = "https://api.coingecko.com/api/v3/coins/ethereum/contract/{}"
AUTO_LOG_ENABLED = False


def fetch_token_info(address: str) -> Optional[dict]:
    """Fetch token info from CoinGecko by contract address."""
    url = COINGECKO_CONTRACT_URL.format(address.lower())
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.info("CoinGecko returned %s for %s", r.status_code, address)
            return None
        data = r.json()
        return data
    except Exception as e:
        logger.exception("Error fetching token info: %s", e)
        return None


def format_token_message(data: dict, contract: str, deep_link_base: str) -> str:
    name = data.get("name") or "Unknown"
    symbol = data.get("symbol") or ""
    market = data.get("market_data", {})
    price = market.get("current_price", {}).get("usd")
    mcap = market.get("market_cap", {}).get("usd")
    change24 = market.get("price_change_percentage_24h")
    homepage = data.get("links", {}).get("homepage", [None])[0]

    parts = []
    parts.append(f"{name} ({symbol})")
    parts.append(f"Contract: `{contract}`")
    if price is not None:
        parts.append(f"Price (USD): ${price:,.6g}")
    if mcap is not None:
        parts.append(f"Market Cap (USD): ${mcap:,.0f}")
    if change24 is not None:
        arrow = '🟢' if change24 >= 0 else '🔴'
        parts.append(f"24h change: {arrow} {change24:.2f}%")
    if homepage:
        parts.append(f"Website: {homepage}")

    deep_link = deep_link_base.rstrip("/") + "/" + contract
    parts.append(f"GMGN: {deep_link}")

    return "\n".join(parts)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    found = TOKEN_REGEX.findall(text)
    if not found:
        return

    deep_link_base = os.getenv("GMGN_DEEP_LINK", "https://gmgn.ai/sol/token")

    for contract in set(found):
        await update.message.reply_text(f"Looking up {contract}...")
        data = await asyncio.to_thread(fetch_token_info, contract)
        if not data:
            await update.message.reply_text(
                f"No data found for {contract}.\nGMGN link: {deep_link_base.rstrip('/')}/{contract}"
            )
            continue

        msg = format_token_message(data, contract, deep_link_base)
        image = data.get("image", {}).get("large")
        try:
            if image:
                await update.message.reply_photo(photo=image, caption=msg)
            else:
                await update.message.reply_text(msg)
        except Exception:
            await update.message.reply_text(msg)

        # Optional: auto-log detected contracts to calls.csv
        try:
            if AUTO_LOG_ENABLED:
                bet = os.getenv('DEFAULT_BET_SOL', '0')
                channel = getattr(update.effective_chat, 'title', str(update.effective_chat.id))
                trade_logger.log_call(mint=contract, bet_sol=bet, channel=channel, note='auto-logged')
                await update.message.reply_text(f"Auto-logged {contract} (bet={bet})")
        except Exception:
            logger.exception("Auto-log failed")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Hello! I watch messages for token contract addresses (0x...).\n"
        "When I see one I'll look it up and reply with info + a GMGN deep link.\n"
        "Use /gm <contract> to get a deep-link immediately."
    )
    await update.message.reply_text(text)
    await menu_command(update, context)


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with this chat's id — paste it into TELEGRAM_CHAT_ID in .env."""
    chat = update.effective_chat
    await update.message.reply_text(
        f"chat id: {chat.id}\n(set TELEGRAM_CHAT_ID={chat.id} in .env for buy notifications)"
    )


async def gm_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /gm 0x...
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /gm <contract_address>")
        return

    contract = args[0]

    deep_link_base = os.getenv("GMGN_DEEP_LINK", "https://gmgn.ai/sol/token")
    deep_link = deep_link_base.rstrip('/') + '/' + contract
    await update.message.reply_text(f"Open GMGN: {deep_link}")


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /recent [n]
    args = context.args
    n = None
    if args:
        try:
            n = int(args[0])
        except Exception:
            pass
    try:
        text = format_recent_calls_text(n)
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text(f"Error fetching recent calls: {e}")


async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Usage examples:
    /log mint=0x... bet=0.3 entry=1.2e-7 exit=1.9e-7 note=quick
    /log 0x... 0.3
    """
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /log mint=<contract> bet=<size> [entry=..] [exit=..] [ath=..] [note=..]")
        return

    # Parse key=value pairs or positional (mint bet)
    params = {}
    for i, a in enumerate(args):
        if "=" in a:
            k, v = a.split("=", 1)
            params[k.lstrip('-')] = v
        else:
            # positional: first -> mint, second -> bet
            if i == 0:
                params.setdefault('mint', a)
            elif i == 1:
                params.setdefault('bet', a)

    mint = params.get('mint')
    bet = params.get('bet') or params.get('bet_sol') or os.getenv('DEFAULT_BET_SOL', '0')
    entry = params.get('entry')
    exitp = params.get('exit')
    ath = params.get('ath')
    pnl = params.get('pnl')
    note = params.get('note', '')

    if not mint:
        await update.message.reply_text("Missing mint parameter.")
        return

    try:
        trade_logger.log_call(mint=mint, bet_sol=bet, channel=str(update.effective_chat.id),
                              entry=entry, exit=exitp, ath=ath, pnl_pct=(float(pnl) if pnl else None), note=note)
        await update.message.reply_text("Logged.")
    except Exception as e:
        await update.message.reply_text(f"Error logging: {e}")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            trade_logger.stats()
        await update.message.reply_text("```" + buf.getvalue() + "```")
    except Exception as e:
        await update.message.reply_text(f"Error running stats: {e}")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            trade_logger.show()
        await update.message.reply_text("```" + buf.getvalue() + "```")
    except Exception as e:
        await update.message.reply_text(f"Error running list: {e}")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = [
        [InlineKeyboardButton("Lookup GM", callback_data="menu_gm")],
        [InlineKeyboardButton("Recent", callback_data="menu_recent")],
        [InlineKeyboardButton("Quick Log", callback_data="menu_log")],
        [InlineKeyboardButton("Stats", callback_data="menu_stats")],
        [InlineKeyboardButton("List", callback_data="menu_list")],
        [InlineKeyboardButton("Toggle Auto-Log", callback_data="menu_toggle_autolog")],
    ]
    await update.message.reply_text("Quick menu:", reply_markup=InlineKeyboardMarkup(kb))


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    chat = query.message.chat_id

    if data == 'menu_stats':
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                trade_logger.stats()
            await query.message.reply_text("```" + buf.getvalue() + "```")
        except Exception as e:
            await query.message.reply_text(f"Error running stats: {e}")
        return

    if data == 'menu_recent':
        try:
            text = format_recent_calls_text()
            await query.message.reply_text(text)
        except Exception as e:
            await query.message.reply_text(f"Error fetching recent calls: {e}")
        return

    if data == 'menu_list':
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                trade_logger.show()
            await query.message.reply_text("```" + buf.getvalue() + "```")
        except Exception as e:
            await query.message.reply_text(f"Error running list: {e}")
        return

    if data == 'menu_toggle_autolog':
        # toggle runtime flag
        global AUTO_LOG_ENABLED
        AUTO_LOG_ENABLED = not AUTO_LOG_ENABLED
        await query.message.reply_text(f"AUTO_LOG set to {AUTO_LOG_ENABLED}")
        return

    if data == 'menu_gm':
        await query.message.reply_text("Usage: /gm <contract>\nExample: /gm 0x1234...\nI'll return a GMGN deep-link for the contract.")
        return

    if data == 'menu_log':
        await query.message.reply_text("Quick log templates:\n/log 0x<contract> <bet>\n/log mint=0x... bet=0.3 entry=... exit=... note=...")
        return


def _read_calls(n: int | None = None):
    path = os.getenv('CALLS_CSV', 'calls.csv')
    if not os.path.exists(path):
        return []
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    if n is None:
        return list(reversed(rows))
    return list(reversed(rows))[:n]


def format_recent_calls_text(n: int | None = None) -> str:
    rows = _read_calls(n)
    if not rows:
        return "No calls logged."
    deep_link_base = os.getenv('GMGN_DEEP_LINK', 'https://gmgn.ai/sol/token')
    parts = [f"Recent {len(rows)} calls:"]
    for r in rows:
        ts = r.get('ts','')[:16]
        mint = r.get('mint','')
        mint_short = mint[:12]
        bet = str(r.get('bet_sol',''))
        pnl_raw = r.get('pnl_pct','')
        try:
            pnl_val = float(pnl_raw)
            emoji = '🟢' if pnl_val > 0 else ('🔴' if pnl_val < 0 else '⚪')
            pnl = f"{emoji} {pnl_val:+.2f}%"
        except Exception:
            pnl = str(pnl_raw)
        note = r.get('note','')
        channel = r.get('channel','')
        deep = deep_link_base.rstrip('/') + '/' + mint
        parts.append(f"{ts}  {mint_short} ({deep})  bet={bet}  {pnl}  {note} {channel}")
    return "\n".join(parts)


def main() -> None:
    # Load environment from a local .env file if present (convenience for local runs)
    try:
        load_dotenv()
        if os.path.exists('.env'):
            logger.info("Loaded environment variables from .env")
    except Exception:
        logger.debug("Couldn't load .env (python-dotenv missing?)", exc_info=True)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    # Defensive: users sometimes export the token with surrounding quotes
    token = token.strip()
    if (token.startswith('"') and token.endswith('"')) or (
        token.startswith("'") and token.endswith("'")
    ):
        token = token[1:-1]
        logger.info("Stripped surrounding quotes from TELEGRAM_BOT_TOKEN")

    # Basic format check to give a clear error instead of an obscure InvalidToken
    if not re.match(r'^\d+:[A-Za-z0-9_-]+$', token):
        logger.error(
            "TELEGRAM_BOT_TOKEN looks invalid. It should be like '123456:ABC-DEF' without quotes. Got: %s",
            token,
        )
        return

    # initialize runtime flags
    global AUTO_LOG_ENABLED
    AUTO_LOG_ENABLED = os.getenv('AUTO_LOG', 'false').lower() in ('1', 'true', 'yes')
    if AUTO_LOG_ENABLED:
        logger.info("AUTO_LOG enabled (runtime)")

    logger.info("python-telegram-bot version: %s", ptb_version)

    app = ApplicationBuilder().token(token).build()

    # Register bot commands so they are visible in the Telegram UI (quick access)
    try:
        commands = [
            BotCommand('start', 'Start the bot and show menu'),
            BotCommand('menu', 'Open quick menu'),
            BotCommand('recent', 'Show recent calls'),
            BotCommand('gm', 'Get GMGN deep-link for a contract'),
            BotCommand('log', 'Quickly log a call'),
            BotCommand('stats', 'Show trade stats'),
            BotCommand('list', 'List logged calls'),
        ]
        app.bot.set_my_commands(commands)
    except Exception:
        logger.exception("Failed to set bot commands (non-fatal)")

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('gm', gm_command))
    app.add_handler(CommandHandler('id', id_command))
    app.add_handler(CommandHandler('log', log_command))
    app.add_handler(CommandHandler('stats', stats_command))
    app.add_handler(CommandHandler('list', list_command))
    app.add_handler(CommandHandler('menu', menu_command))
    app.add_handler(CallbackQueryHandler(handle_menu_callback))
    app.add_handler(CommandHandler('recent', lambda u,c: asyncio.create_task(recent_command(u,c))))

    logger.info("Starting bot, listening for messages containing contract addresses...")
    app.run_polling()


if __name__ == "__main__":
    main()
