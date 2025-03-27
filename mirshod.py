import requests
import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)
from telegram.error import TelegramError, NetworkError, Conflict
import html

# Load environment variables from .env file
load_dotenv()

# Set up logging to debug issues
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load sensitive information from environment variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7684629360:AAEEGcts8t-FV2rkFHjX140PykViPF1fLpA")
if not BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
    exit(1)

EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY", "021088e30325b16dce1c8b16")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "EISI552Y1AN7QPCJ")

CHANNEL_USERNAME = '@UDEA_Finance_Club'
EXCHANGE_API_URL = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/UZS"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/coins/markets"

# List of currencies for UZS comparison and currency converter
CURRENCIES = ["UZS", "USD", "GBP", "JPY", "EUR", "RUB", "QAR", "KZT"]

# Cache for market data with timestamps
market_data_cache = {
    "sp500": {"data": None, "last_updated": None},
    "crypto": {"data": None, "last_updated": None},
    "commodity": {"data": None, "last_updated": None},
    "currency": {"data": None, "last_updated": None},
    "uzs_rates": {"data": None, "last_updated": None}
}
CACHE_DURATION = timedelta(minutes=5)  # Refresh data every 5 minutes

# Redesigned main menu with a more compact layout and additional emojis
MAIN_MENU_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("ℹ️ About", callback_data="about_bot"),
        InlineKeyboardButton("📈 Markets", callback_data="market_prices"),
    ],
    [
        InlineKeyboardButton("🇺🇿 UZS Rates", callback_data="uzs_comparison"),
        InlineKeyboardButton("💱 Convert", callback_data="currency_calculator"),
    ],
    [
        InlineKeyboardButton("👨‍💼 Contact Admin", callback_data="admin_contact"),
    ],
])

# Redesigned Market Prices submenu with a more compact layout and additional emojis
MARKET_PRICES_KEYBOARD = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("📊 S&P 500", callback_data="market_sp500"),
        InlineKeyboardButton("🚀 Crypto", callback_data="market_crypto"),
    ],
    [
        InlineKeyboardButton("⛏️ Commodities", callback_data="market_commodity"),
        InlineKeyboardButton("💵 Currencies", callback_data="market_currency"),
    ],
    [
        InlineKeyboardButton("⬅️ Back to Main", callback_data="back_to_main"),
    ],
])

# Function to create a currency selection keyboard
def get_currency_keyboard(callback_prefix):
    buttons = [InlineKeyboardButton(text=cur, callback_data=f"{callback_prefix}_{cur}") for cur in CURRENCIES]
    keyboard = []
    for i in range(0, len(buttons), 4):
        row = buttons[i:i + 4]
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# States for the currency conversion conversation
FROM_CURRENCY, TO_CURRENCY, AMOUNT = range(3)

# Utility function to escape HTML special characters
def escape_html(text):
    return html.escape(str(text))

# Function to fetch UZS exchange rates with error handling
def get_uzs_exchange_rates():
    try:
        response = requests.get(EXCHANGE_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("result") == "success":
            rates = data.get("conversion_rates", {})
            if not rates:
                logger.error("No exchange rate data found in response.")
                return None
            return {currency: rates.get(currency, "N/A") for currency in CURRENCIES}
        else:
            logger.error(f"API response unsuccessful: {data.get('error-type', 'Unknown error')}")
            return None
    except requests.RequestException as e:
        logger.error(f"Error fetching UZS exchange rates: {e}")
        return None

# Function to fetch exchange rate between two currencies
def get_exchange_rate(from_currency, to_currency):
    try:
        response = requests.get(f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/{from_currency}", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("result") == "success":
            rates = data.get("conversion_rates", {})
            if not rates:
                logger.error("No exchange rate data found in response.")
                return None
            rate = rates.get(to_currency)
            if rate is None:
                logger.error(f"Exchange rate for {to_currency} not found.")
                return None
            return rate
        else:
            logger.error(f"API response unsuccessful: {data.get('error-type', 'Unknown error')}")
            return None
    except requests.RequestException as e:
        logger.error(f"Error fetching exchange rate from {from_currency} to {to_currency}: {e}")
        return None

# Function to fetch S&P 500 stock prices using Alpha Vantage
def get_sp500_stock_prices():
    try:
        symbols = ["AAPL", "MSFT", "AMZN", "GOOGL"]  # Reduced to 4 symbols to stay within rate limits
        prices = []
        
        for symbol in symbols:
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY
            }
            response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "Time Series (Daily)" in data:
                latest_date = list(data["Time Series (Daily)"].keys())[0]
                latest_price = float(data["Time Series (Daily)"][latest_date]["4. close"])
                prices.append((symbol, latest_price))
            else:
                error_message = data.get('Note', data.get('Information', 'Unknown error'))
                logger.warning(f"Could not fetch data for {symbol}: {error_message}")
                prices.append((symbol, "N/A"))
            time.sleep(12)  # Alpha Vantage free tier: 5 requests per minute

        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": "SPY",
            "apikey": ALPHA_VANTAGE_API_KEY
        }
        response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "Time Series (Daily)" in data:
            latest_date = list(data["Time Series (Daily)"].keys())[0]
            sp500_index = float(data["Time Series (Daily)"][latest_date]["4. close"]) * 10
        else:
            error_message = data.get('Note', data.get('Information', 'Unknown error'))
            logger.warning(f"Could not fetch data for SPY: {error_message}")
            sp500_index = "N/A"

        if all(price == "N/A" for _, price in prices) and sp500_index == "N/A":
            logger.error("Failed to fetch S&P 500 data for all symbols and index.")
            return "❌ Failed to fetch S&P 500 data. The API may be down or the API key may be invalid."

        message = "<b>S&P 500 Stock Prices 📈</b>\n"
        for symbol, price in prices:
            price_str = f"${price:.2f}" if isinstance(price, float) else price
            message += f"{escape_html(symbol)}: {escape_html(price_str)}\n"
        sp500_str = f"{sp500_index:.2f}" if isinstance(sp500_index, float) else sp500_index
        message += f"<b>S&P 500 Index:</b> {escape_html(sp500_str)}\n"
        return message
    except requests.RequestException as e:
        logger.error(f"Error fetching S&P 500 stock prices: {e}")
        return "❌ Error fetching S&P 500 stock prices. Please try again later."

# Function to fetch Crypto Market prices using CoinGecko
def get_crypto_prices():
    try:
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 10,
            "page": 1,
            "sparkline": "false"
        }
        response = requests.get(COINGECKO_API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            message = "<b>Crypto Market 🚀</b>\n"
            for coin in data:
                name = coin["symbol"].upper()
                price = coin["current_price"]
                message += f"{escape_html(name)}: ${price:,.2f}\n"
            return message
        else:
            logger.error(f"Invalid response from CoinGecko API: {data}")
            return "❌ Unable to fetch cryptocurrency prices."
    except requests.RequestException as e:
        logger.error(f"Error fetching cryptocurrency prices: {e}")
        return "❌ Error fetching cryptocurrency prices."

# Function to fetch Commodity Market prices using Alpha Vantage
def get_commodity_prices():
    try:
        commodities = [
            ("GOLD", "Gold (XAU/USD)"),
        ]
        prices = []
        
        for symbol, name in commodities:
            logger.info(f"Fetching data for {name} ({symbol})...")
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "apikey": ALPHA_VANTAGE_API_KEY
            }
            response = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "Time Series (Daily)" in data:
                latest_date = list(data["Time Series (Daily)"].keys())[0]
                latest_price = float(data["Time Series (Daily)"][latest_date]["4. close"])
                prices.append((name, latest_price))
                logger.info(f"Successfully fetched data for {name}: {latest_price}")
            else:
                error_message = data.get('Note', data.get('Information', 'Unknown error'))
                logger.warning(f"Could not fetch data for {name} ({symbol}): {error_message}")
                prices.append((name, "N/A"))
            time.sleep(12)

        message = "<b>Commodity Market ⛏️</b>\n"
        for name, price in prices:
            price_str = f"${price:,.2f}" if isinstance(price, float) else price
            message += f"{escape_html(name)}: {escape_html(price_str)}\n"
        return message
    except requests.RequestException as e:
        logger.error(f"Error fetching commodity prices: {e}")
        return "❌ Error fetching commodity prices."

# Function to fetch Currency Market prices using ExchangeRate-API
def get_currency_prices():
    try:
        response = requests.get(f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD", timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("result") == "success":
            rates = data.get("conversion_rates", {})
            if not rates:
                logger.error("No currency rate data found in response.")
                return "❌ Unable to fetch currency prices."
            
            pairs = [
                ("USD/EUR", "EUR"),
                ("GBP/USD", "GBP"),
                ("USD/JPY", "JPY"),
                ("USD/CHF", "CHF"),
                ("EUR/GBP", "EUR", "GBP"),
                ("AUD/USD", "AUD"),
                ("USD/CAD", "CAD"),
                ("NZD/USD", "NZD"),
                ("EUR/JPY", "EUR", "JPY"),
                ("GBP/JPY", "GBP", "JPY")
            ]
            
            message = "<b>Currency Market 💱</b>\n"
            for pair in pairs:
                if len(pair) == 2:
                    base, target = "USD", pair[1]
                    rate = rates.get(target, "N/A")
                    if rate != "N/A":
                        rate = 1 / rate if base == "USD" else rate
                        message += f"{escape_html(pair[0])}: {rate:.2f}\n"
                    else:
                        message += f"{escape_html(pair[0])}: N/A\n"
                else:
                    base, target = pair[1], pair[2]
                    base_to_usd = rates.get(base, "N/A")
                    target_to_usd = rates.get(target, "N/A")
                    if base_to_usd != "N/A" and target_to_usd != "N/A":
                        rate = (1 / base_to_usd) * target_to_usd
                        message += f"{escape_html(pair[0])}: {rate:.2f}\n"
                    else:
                        message += f"{escape_html(pair[0])}: N/A\n"
            return message
        else:
            logger.error(f"API response unsuccessful: {data.get('error-type', 'Unknown error')}")
            return "❌ Unable to fetch currency prices."
    except requests.RequestException as e:
        logger.error(f"Error fetching currency prices: {e}")
        return "❌ Error fetching currency prices."

# Function to fetch and cache market data
async def fetch_market_data(category):
    now = datetime.utcnow()
    cache_entry = market_data_cache[category]
    
    if cache_entry["data"] and cache_entry["last_updated"] and (now - cache_entry["last_updated"]) < CACHE_DURATION:
        return cache_entry["data"]

    if category == "sp500":
        data = get_sp500_stock_prices()
    elif category == "crypto":
        data = get_crypto_prices()
    elif category == "commodity":
        data = get_commodity_prices()
    elif category == "currency":
        data = get_currency_prices()
    elif category == "uzs_rates":
        data = get_uzs_exchange_rates()
    else:
        data = "❌ Invalid category."

    market_data_cache[category]["data"] = data
    market_data_cache[category]["last_updated"] = now
    return data

# Function to show the main menu with inline buttons as a new message
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_start=False):
    menu_text = "<b>🌟 Welcome to UDEA Finance Bot! 🌟</b>\n\nChoose an option below:" if is_start else "<b>🌟 Choose an option below:</b>"
    if update.callback_query:
        query = update.callback_query
        await query.message.reply_text(menu_text, reply_markup=MAIN_MENU_KEYBOARD, parse_mode='HTML')
        logger.info("Main menu sent as a new message (callback).")
    else:
        await update.message.reply_text(menu_text, reply_markup=MAIN_MENU_KEYBOARD, parse_mode='HTML')
        logger.info("Main menu sent as a new message (start).")

# Function to show the Market Prices submenu with inline buttons as a new message
async def show_market_prices_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = "<b>📈 Market Prices 📉</b>\n\nSelect a market to explore:"
    query = update.callback_query
    await query.message.reply_text(menu_text, reply_markup=MARKET_PRICES_KEYBOARD, parse_mode='HTML')
    logger.info("Market Prices menu sent as a new message.")

# /start command handler with subscription check
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"Received /start command from user {user_id}")
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if chat_member.status in ['member', 'administrator', 'creator']:
            logger.info(f"User {user_id} is a member of the channel, showing main menu")
            await show_main_menu(update, context, is_start=True)
        else:
            logger.info(f"User {user_id} is not a member of the channel, prompting to join")
            welcome_text = (
                "<b>🚀 Welcome to UDEA Finance Bot!</b>\n\n"
                "To get started, please join our official channel first! 📢\n\n"
                "<b>🔒 Why join?</b>\n"
                "We provide real-time financial data, market news, and currency tools for free! "
                "Joining the channel helps support the bot and keeps you updated with the latest news.\n\n"
                "👉 Join here: <a href='https://t.me/UDEA_Finance_Club'>UDEA Finance Club</a>"
            )
            await update.message.reply_text(welcome_text, parse_mode='HTML')
    except TelegramError as e:
        logger.error(f"Telegram error while checking subscription for user {user_id}: {e}")
        await update.message.reply_text("❌ An error occurred while checking subscription. Please try again.")

# Handler for the "Currency Calculator" button
async def start_currency_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info("Currency Calculator button pressed.")
    new_text = "💱 Choose the currency you want to convert from:"
    await query.message.reply_text(new_text, reply_markup=get_currency_keyboard("from"), parse_mode='HTML')
    logger.info("Currency calculator started as a new message.")
    return FROM_CURRENCY

# Handler for selecting the "from" currency
async def select_from_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    from_currency = query.data.split("_")[1]
    context.user_data["from_currency"] = from_currency
    logger.info(f"User selected 'from' currency: {from_currency}")
    new_text = "💱 Now, choose the currency you want to convert to:"
    await query.message.reply_text(new_text, reply_markup=get_currency_keyboard("to"), parse_mode='HTML')
    logger.info("Updated to 'to' currency selection as a new message.")
    return TO_CURRENCY

# Handler for selecting the "to" currency
async def select_to_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    to_currency = query.data.split("_")[1]
    context.user_data["to_currency"] = to_currency
    logger.info(f"User selected 'to' currency: {to_currency}")
    new_text = "💱 Enter the amount you want to convert:"
    await query.message.reply_text(new_text, parse_mode='HTML')
    logger.info("Updated to amount input as a new message.")
    return AMOUNT

# Handler for the amount input in the currency conversion process
async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
        from_currency = context.user_data.get("from_currency")
        to_currency = context.user_data.get("to_currency")

        rate = get_exchange_rate(from_currency, to_currency)
        if rate:
            converted_amount = round(amount * rate, 2)
            await update.message.reply_text(f"{amount} {from_currency} = {converted_amount} {to_currency} 💱", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ Error fetching exchange rate.", parse_mode='HTML')

        context.user_data.clear()
        await show_main_menu(update, context)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("Please enter a valid number.", parse_mode='HTML')
        return AMOUNT
    except Exception as e:
        logger.error(f"Unexpected error while converting currency: {e}")
        await update.message.reply_text("❌ An error occurred while converting currency. Please try again.", parse_mode='HTML')
        return ConversationHandler.END

# Handler for inline button callbacks (excluding currency conversion)
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    callback_data = query.data
    logger.info(f"Callback received: {callback_data} from user {update.effective_user.id}")

    try:
        if callback_data == "about_bot":
            about_text = (
                "<b>ℹ️ About UDEA Finance Bot</b>\n\n"
                "Welcome to the UDEA Finance Bot, created by the UDEA Finance Club! 🎉\n\n"
                "Our mission is to empower students and finance enthusiasts with real-time market data, currency rates, and financial insights. 📊💰\n\n"
                "Led by Mirshod Yaxshiyev, this bot provides:\n"
                "✅ Stock prices (S&P 500)\n"
                "✅ Cryptocurrency updates\n"
                "✅ Commodity and currency markets\n"
                "✅ UZS exchange rates\n\n"
                "Start exploring the world of finance today! 🚀"
            )
            await query.message.reply_text(about_text, parse_mode='HTML')
            logger.info("About bot message sent as a new message.")
            await show_main_menu(update, context)

        elif callback_data == "admin_contact":
            admin_text = (
                "<b>👨‍💼 Contact Admin</b>\n\n"
                "Need help or have questions? Reach out to the admin of UDEA Finance Club! 📩\n\n"
                "👉 Contact: <a href='https://t.me/mirshodbek_yakhshiyev'>@mirshodbek_yakhshiyev</a>\n"
            )
            await query.message.reply_text(admin_text, parse_mode='HTML')
            logger.info("Admin contact message sent as a new message.")
            await show_main_menu(update, context)

        elif callback_data == "market_prices":
            await show_market_prices_menu(update, context)

        elif callback_data == "uzs_comparison":
            rates = await fetch_market_data("uzs_rates")
            if rates:
                message = "<b>🇺🇿 UZS Exchange Rates</b>\n\n"
                for currency, rate in rates.items():
                    if rate != "N/A":
                        message += f"1 {escape_html(currency)} = {round(1 / rate, 2)} UZS\n"
                    else:
                        message += f"1 {escape_html(currency)} = N/A\n"
                await query.message.reply_text(message, parse_mode="HTML")
                logger.info("UZS exchange rates message sent as a new message.")
            else:
                error_message = "❌ Error: Unable to fetch currency rates."
                await query.message.reply_text(error_message, parse_mode='HTML')
                logger.info("UZS exchange rates error message sent as a new message.")
            await show_main_menu(update, context)

        elif callback_data == "market_sp500":
            logger.info("Fetching S&P 500 stock prices...")
            data = await fetch_market_data("sp500")
            logger.info(f"S&P 500 data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            await query.message.reply_text(new_message, parse_mode='HTML')
            logger.info("S&P 500 message sent as a new message.")
            await show_market_prices_menu(update, context)

        elif callback_data == "market_crypto":
            logger.info("Fetching Crypto Market prices...")
            data = await fetch_market_data("crypto")
            logger.info(f"Crypto Market data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            await query.message.reply_text(new_message, parse_mode='HTML')
            logger.info("Crypto Market message sent as a new message.")
            await show_market_prices_menu(update, context)

        elif callback_data == "market_commodity":
            logger.info("Fetching Commodity Market prices...")
            try:
                data = await asyncio.wait_for(fetch_market_data("commodity"), timeout=30)
                logger.info(f"Commodity Market data fetched: {data}")
                new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
                await query.message.reply_text(new_message, parse_mode='HTML')
                logger.info("Commodity Market message sent as a new message.")
            except asyncio.TimeoutError:
                logger.error("Fetching commodity prices timed out after 30 seconds.")
                error_message = "❌ Fetching commodity prices timed out. Please try again later."
                await query.message.reply_text(error_message, parse_mode='HTML')
                logger.info("Commodity Market timeout message sent as a new message.")
            await show_market_prices_menu(update, context)

        elif callback_data == "market_currency":
            logger.info("Fetching Currency Market prices...")
            data = await fetch_market_data("currency")
            logger.info(f"Currency Market data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            await query.message.reply_text(new_message, parse_mode='HTML')
            logger.info("Currency Market message sent as a new message.")
            await show_market_prices_menu(update, context)

        elif callback_data == "back_to_main":
            await show_main_menu(update, context)

        else:
            logger.warning(f"Unknown callback data received: {callback_data} from user {update.effective_user.id}")
            error_message = "❌ Unknown command. Please try again."
            await query.message.reply_text(error_message, parse_mode='HTML')
            logger.info("Unknown command message sent as a new message.")
            await show_main_menu(update, context)

    except TelegramError as e:
        logger.error(f"Telegram error while handling callback: {e}")
        await query.message.reply_text("❌ An error occurred while handling the callback. Please try again.", parse_mode='HTML')
        await show_main_menu(update, context)

# Handler for unexpected text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Please select an option from the menu.", parse_mode='HTML')
    await show_main_menu(update, context)
    logger.info(f"User {update.effective_user.id} sent unexpected text: {update.message.text}")

# Error handler to catch and handle exceptions
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if isinstance(context.error, Conflict):
        logger.error("Conflict error detected. This usually means multiple bot instances are running or a webhook is set.")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ A conflict occurred. The bot may be running elsewhere. Please try again later.", parse_mode='HTML')
        logger.info("Exiting the bot due to Conflict error.")
        os._exit(1)  # Exit the application cleanly
    elif isinstance(context.error, NetworkError):
        logger.error("Network error occurred. This might be a temporary issue with Telegram's servers.")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ A network error occurred. Please try again later.", parse_mode='HTML')
    elif isinstance(context.error, TelegramError):
        logger.error(f"Telegram error: {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ A Telegram error occurred. Please try again.", parse_mode='HTML')
    else:
        logger.error(f"Unexpected error: {context.error}")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ An unexpected error occurred. Please try again.", parse_mode='HTML')

# Main function to run the bot
def main():
    # Build the application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add an error handler
    application.add_error_handler(error_handler)

    # Check and delete any existing webhook to ensure polling works
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Check current webhook status
            webhook_info = application.bot.get_webhook_info()
            logger.info(f"Current webhook info: {webhook_info}")
            if webhook_info.url:
                logger.info(f"Webhook is set to {webhook_info.url}. Deleting webhook...")
                application.bot.delete_webhook(drop_pending_updates=True)
                logger.info("Webhook deleted successfully.")
                # Verify webhook deletion
                webhook_info = application.bot.get_webhook_info()
                logger.info(f"Webhook info after deletion: {webhook_info}")
                if webhook_info.url:
                    logger.error("Webhook still exists after deletion attempt.")
                    continue
            break
        except TelegramError as e:
            logger.error(f"Failed to delete webhook (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                logger.critical("Failed to delete webhook after maximum retries. Exiting.")
                exit(1)
            time.sleep(2)  # Wait before retrying

    # Add conversation handler for currency conversion
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_currency_calculator, pattern="^currency_calculator$")],
        states={
            FROM_CURRENCY: [CallbackQueryHandler(select_from_currency, pattern="^from_")],
            TO_CURRENCY: [CallbackQueryHandler(select_to_currency, pattern="^to_")],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)],
        },
        fallbacks=[],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot is starting...")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Conflict as e:
        logger.error(f"Conflict error during polling: {e}. This usually means another instance of the bot is running.")
        logger.info("Please ensure only one instance of the bot is running and no webhook is set.")
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during polling: {e}")
        exit(1)

if __name__ == "__main__":
    main()
