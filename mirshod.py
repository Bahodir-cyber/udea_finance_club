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
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7684629360:AAEGZy3hjknZNhMk79D4ntsjKtzpa3q_KRE")
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

# Cache InlineKeyboardMarkup objects for main menu and Market Prices submenu
MAIN_MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("ℹ About the Bot", callback_data="about_bot")],
    [InlineKeyboardButton("📊 Market Prices", callback_data="market_prices")],
    [InlineKeyboardButton("🇺🇿 UZS Price Comparison", callback_data="uzs_comparison")],
    [InlineKeyboardButton("👤 Admin Contact", callback_data="admin_contact")],
    [InlineKeyboardButton("💱 Currency Calculator", callback_data="currency_calculator")],
])

MARKET_PRICES_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("S&P 500 Stock Prices", callback_data="market_sp500")],
    [InlineKeyboardButton("Crypto Market", callback_data="market_crypto")],
    [InlineKeyboardButton("Commodity Market", callback_data="market_commodity")],
    [InlineKeyboardButton("Currency Market", callback_data="market_currency")],
    [InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")],
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
    except requests.Timeout:
        logger.error("Exchange rate API request timed out.")
        return None
    except requests.RequestException as e:
        logger.error(f"Error fetching UZS exchange rates: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching UZS exchange rates: {e}")
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
    except requests.Timeout:
        logger.error("Exchange rate API request timed out.")
        return None
    except requests.RequestException as e:
        logger.error(f"Error fetching exchange rate from {from_currency} to {to_currency}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching exchange rate from {from_currency} to {to_currency}: {e}")
        return None

# Function to fetch S&P 500 stock prices using Alpha Vantage
def get_sp500_stock_prices():
    try:
        symbols = ["AAPL", "MSFT", "AMZN", "TSLA", "GOOGL", "META", "NVDA", "BRK.B", "JNJ", "JPM"]
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
                logger.warning(f"Could not fetch data for {symbol}: {data.get('Note', 'Unknown error')}")
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
            sp500_index = "N/A"

        message = "<b>S&P 500 Stock Prices 📈</b>\n"
        for symbol, price in prices:
            price_str = f"${price:.2f}" if isinstance(price, float) else price
            message += f"{escape_html(symbol)}: {escape_html(price_str)}\n"
        sp500_str = f"{sp500_index:.2f}" if isinstance(sp500_index, float) else sp500_index
        message += f"<b>S&P 500 Index:</b> {escape_html(sp500_str)}\n"
        return message
    except requests.Timeout:
        logger.error("Alpha Vantage API request timed out.")
        return "❌ Alpha Vantage API request timed out."
    except requests.RequestException as e:
        logger.error(f"Error fetching S&P 500 stock prices: {e}")
        return "❌ Error fetching S&P 500 stock prices."
    except Exception as e:
        logger.error(f"Unexpected error while fetching S&P 500 stock prices: {e}")
        return "❌ Unexpected error while fetching S&P 500 stock prices."

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
            logger.error("Invalid response from CoinGecko API.")
            return "❌ Unable to fetch cryptocurrency prices."
    except requests.Timeout:
        logger.error("CoinGecko API request timed out.")
        return "❌ CoinGecko API request timed out."
    except requests.RequestException as e:
        logger.error(f"Error fetching cryptocurrency prices: {e}")
        return "❌ Error fetching cryptocurrency prices."
    except Exception as e:
        logger.error(f"Unexpected error while fetching cryptocurrency prices: {e}")
        return "❌ Unexpected error while fetching cryptocurrency prices."

# Function to fetch Commodity Market prices using Alpha Vantage
def get_commodity_prices():
    try:
        commodities = [
            ("GOLD", "Gold (XAU/USD)"),
        ]
        prices = []
        
        for symbol, name in commodities:
            logger.info(f"Fetching data for {name} ({symbol})...")
            try:
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
                    error_message = data.get('Note', 'Unknown error')
                    logger.warning(f"Could not fetch data for {name} ({symbol}): {error_message}")
                    prices.append((name, "N/A"))
                time.sleep(12)
            except requests.Timeout:
                logger.error(f"API request timed out for {name} ({symbol})")
                prices.append((name, "N/A"))
                continue
            except requests.RequestException as e:
                logger.error(f"Error fetching data for {name} ({symbol}): {e}")
                prices.append((name, "N/A"))
                continue
            except Exception as e:
                logger.error(f"Unexpected error while fetching data for {name} ({symbol}): {e}")
                prices.append((name, "N/A"))
                continue

        message = "<b>Commodity Market ⛏️</b>\n"
        for name, price in prices:
            price_str = f"${price:,.2f}" if isinstance(price, float) else price
            message += f"{escape_html(name)}: {escape_html(price_str)}\n"
        logger.info("Commodity prices fetched successfully.")
        return message
    except Exception as e:
        logger.error(f"Unexpected error in get_commodity_prices: {e}")
        return "❌ Unexpected error while fetching commodity prices."

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
    except requests.Timeout:
        logger.error("Exchange rate API request timed out.")
        return "❌ Exchange rate API request timed out."
    except requests.RequestException as e:
        logger.error(f"Error fetching currency prices: {e}")
        return "❌ Error fetching currency prices."
    except Exception as e:
        logger.error(f"Unexpected error while fetching currency prices: {e}")
        return "❌ Unexpected error while fetching currency prices."

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

# Function to show the main menu with inline buttons
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_start=False):
    try:
        menu_text = "<b>🎉 Welcome to the bot! Please select an option below:</b>" if is_start else "<b>Please select an option below:</b>"
        if update.callback_query:
            query = update.callback_query
            current_text = query.message.text or ""
            logger.info(f"Showing main menu (callback). Current text: {current_text}, New text: {menu_text}")
            if current_text != menu_text:
                await query.message.edit_text(menu_text, reply_markup=MAIN_MENU_KEYBOARD, parse_mode='HTML')
                logger.info("Main menu updated successfully (edit).")
            else:
                logger.info("Skipping main menu edit: content unchanged.")
            return
        else:
            await update.message.reply_text(menu_text, reply_markup=MAIN_MENU_KEYBOARD, parse_mode='HTML')
            logger.info("Main menu displayed successfully (new message).")
    except TelegramError as e:
        logger.error(f"Telegram error while showing main menu: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred while showing the main menu. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected error while showing main menu: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred while showing the main menu. Please try again.")

# Function to show the Market Prices submenu with inline buttons
async def show_market_prices_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        menu_text = "<b>📊 Market Prices</b>\nPlease select a market data option below:"
        if update.callback_query:
            query = update.callback_query
            current_text = query.message.text or ""
            logger.info(f"Showing market prices menu (callback). Current text: {current_text}, New text: {menu_text}")
            if current_text != menu_text:
                await query.message.edit_text(menu_text, reply_markup=MARKET_PRICES_KEYBOARD, parse_mode='HTML')
                logger.info("Market Prices menu updated successfully (edit).")
            else:
                logger.info("Skipping market prices menu edit: content unchanged.")
            return
        else:
            await update.message.reply_text(menu_text, reply_markup=MARKET_PRICES_KEYBOARD, parse_mode='HTML')
            logger.info("Market Prices menu displayed successfully (new message).")
    except TelegramError as e:
        logger.error(f"Telegram error while showing Market Prices menu: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred while showing the Market Prices menu. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected error while showing Market Prices menu: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred while showing the Market Prices menu. Please try again.")

# /start command handler with subscription check and error handling
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
                "<b>🚀 Welcome!</b>\n\n"
                "Hello! 🎉 To fully use this bot, you need to join our official channel first. 📢\n\n"
                "<b>🔒 Why is this required?</b>\n"
                "We provide you with real-time financial data, market news, and currency tools for free! "
                "By joining the channel, you support the bot and stay updated with important news.\n\n"
                "👉 Join here: <a href='https://t.me/UDEA_Finance_Club'>UDEA Finance Club</a>"
            )
            await update.message.reply_text(welcome_text, parse_mode='HTML')
        logger.info(f"User {user_id} started the bot.")
    except TelegramError as e:
        logger.error(f"Telegram error while checking subscription for user {user_id}: {e}")
        await update.message.reply_text("❌ An error occurred while checking subscription. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected error while checking subscription for user {user_id}: {e}")
        await update.message.reply_text("❌ An error occurred while checking subscription. Please try again.")

# Handler for the "Currency Calculator" button
async def start_currency_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info("Currency Calculator button pressed.")
    try:
        current_text = query.message.text or ""
        new_text = "Choose the currency you want to convert from:"
        logger.info(f"Starting currency calculator. Current text: {current_text}, New text: {new_text}")
        if current_text != new_text:
            await query.message.edit_text(new_text, reply_markup=get_currency_keyboard("from"), parse_mode='HTML')
            logger.info("Currency calculator started successfully (edit).")
        else:
            logger.info("Skipping currency calculator edit: content unchanged.")
    except TelegramError as e:
        logger.error(f"Telegram error while starting currency calculator: {e}")
        await query.message.reply_text("❌ An error occurred while starting the currency calculator. Please try again.")
    return FROM_CURRENCY

# Handler for selecting the "from" currency
async def select_from_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    from_currency = query.data.split("_")[1]
    context.user_data["from_currency"] = from_currency
    logger.info(f"User selected 'from' currency: {from_currency}")
    try:
        current_text = query.message.text or ""
        new_text = "Now, choose the currency you want to convert to:"
        logger.info(f"Selecting 'from' currency. Current text: {current_text}, New text: {new_text}")
        if current_text != new_text:
            await query.message.edit_text(new_text, reply_markup=get_currency_keyboard("to"), parse_mode='HTML')
            logger.info("Updated to 'to' currency selection successfully (edit).")
        else:
            logger.info("Skipping 'to' currency selection edit: content  content unchanged.")
    except TelegramError as e:
        logger.error(f"Telegram error while selecting 'from' currency: {e}")
        await query.message.reply_text("❌ An error occurred while selecting the currency. Please try again.")
    return TO_CURRENCY

# Handler for selecting the "to" currency
async def select_to_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    to_currency = query.data.split("_")[1]
    context.user_data["to_currency"] = to_currency
    logger.info(f"User selected 'to' currency: {to_currency}")
    try:
        current_text = query.message.text or ""
        new_text = "Enter the amount you want to convert:"
        logger.info(f"Selecting 'to' currency. Current text: {current_text}, New text: {new_text}")
        if current_text != new_text:
            await query.message.edit_text(new_text, parse_mode='HTML')
            logger.info("Updated to amount input successfully (edit).")
        else:
            logger.info("Skipping amount input edit: content unchanged.")
    except TelegramError as e:
        logger.error(f"Telegram error while selecting 'to' currency: {e}")
        await query.message.reply_text("❌ An error occurred while selecting the currency. Please try again.")
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
    try:
        await query.answer()
        callback_data = query.data
        logger.info(f"Callback received: {callback_data} from user {update.effective_user.id}")

        if callback_data == "about_bot":
            about_text = (
                "<b>ℹ About the Bot</b>\n\n"
                "This bot is a project by UDEA Finance Club, designed to help students and finance enthusiasts stay informed about market trends, "
                "currency rates, and financial news. 📊💰\n\n"
                "The project is led by Mirshod Yaxshiyev, who founded this club to promote financial literacy and provide practical experience to students.\n\n"
                "The bot delivers real-time data on stocks, cryptocurrencies, commodity markets, and currency rates. It also keeps you updated with the most important economic and business news.\n\n"
                "Explore the world of finance and make informed decisions! 🚀"
            )
            current_text = query.message.text or ""
            logger.info(f"About bot callback. Current text: {current_text}, New text: {about_text}")
            if current_text != about_text:
                await query.message.edit_text(about_text, parse_mode='HTML')
                logger.info("About bot message updated successfully (edit).")
            else:
                logger.info("Skipping about bot edit: content unchanged.")
            await show_main_menu(update, context)

        elif callback_data == "admin_contact":
            admin_text = (
                "<b>Admin Contact 👤</b>\n\n"
                "Hey there! This is the admin of UDEA Finance Club. If you have any questions about the bot, need assistance, "
                "or want to learn more about finance, feel free to reach out!\n\n"
                "📩 Contact: <a href='https://t.me/mirshodbek_yakhshiyev'>@mirshodbek_yakhshiyev</a>\n"
            )
            current_text = query.message.text or ""
            logger.info(f"Admin contact callback. Current text: {current_text}, New text: {admin_text}")
            if current_text != admin_text:
                await query.message.edit_text(admin_text, parse_mode='HTML')
                logger.info("Admin contact message updated successfully (edit).")
            else:
                logger.info("Skipping admin contact edit: content unchanged.")
            await show_main_menu(update, context)

        elif callback_data == "market_prices":
            await show_market_prices_menu(update, context)

        elif callback_data == "uzs_comparison":
            rates = await fetch_market_data("uzs_rates")
            if rates:
                message = "<b>🇺🇿 UZS Exchange Rates:</b>\n\n"
                for currency, rate in rates.items():
                    if rate != "N/A":
                        message += f"1 {escape_html(currency)} = {round(1 / rate, 2)} UZS\n"
                    else:
                        message += f"1 {escape_html(currency)} = N/A\n"
                current_text = query.message.text or ""
                logger.info(f"UZS comparison callback. Current text: {current_text}, New text: {message}")
                if current_text != message:
                    await query.message.edit_text(message, parse_mode="HTML")
                    logger.info("UZS exchange rates message updated successfully (edit).")
                else:
                    logger.info("Skipping UZS exchange rates edit: content unchanged.")
            else:
                await query.message.edit_text("❌ Error: Unable to fetch currency rates.", parse_mode='HTML')
            await show_main_menu(update, context)

        elif callback_data == "market_sp500":
            logger.info("Fetching S&P 500 stock prices...")
            data = await fetch_market_data("sp500")
            logger.info(f"S&P 500 data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            current_text = query.message.text or ""
            logger.info(f"S&P 500 callback. Current text: {current_text}, New text: {new_message}")
            if current_text != new_message:
                await query.message.edit_text(new_message, parse_mode='HTML')
                logger.info("S&P 500 message updated successfully (edit).")
            else:
                logger.info("Skipping S&P 500 edit: content unchanged.")
            await show_market_prices_menu(update, context)

        elif callback_data == "market_crypto":
            logger.info("Fetching Crypto Market prices...")
            data = await fetch_market_data("crypto")
            logger.info(f"Crypto Market data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            current_text = query.message.text or ""
            logger.info(f"Crypto Market callback. Current text: {current_text}, New text: {new_message}")
            if current_text != new_message:
                await query.message.edit_text(new_message, parse_mode='HTML')
                logger.info("Crypto Market message updated successfully (edit).")
            else:
                logger.info("Skipping Crypto Market edit: content unchanged.")
            await show_market_prices_menu(update, context)

        elif callback_data == "market_commodity":
            logger.info("Fetching Commodity Market prices...")
            try:
                data = await asyncio.wait_for(fetch_market_data("commodity"), timeout=30)
                logger.info(f"Commodity Market data fetched: {data}")
                new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
                current_text = query.message.text or ""
                logger.info(f"Commodity Market callback. Current text: {current_text}, New text: {new_message}")
                if current_text != new_message:
                    await query.message.edit_text(new_message, parse_mode='HTML')
                    logger.info("Commodity Market message updated successfully (edit).")
                else:
                    logger.info("Skipping Commodity Market edit: content unchanged.")
            except asyncio.TimeoutError:
                logger.error("Fetching commodity prices timed out after 30 seconds.")
                await query.message.edit_text("❌ Fetching commodity prices timed out. Please try again later.", parse_mode='HTML')
            await show_market_prices_menu(update, context)

        elif callback_data == "market_currency":
            logger.info("Fetching Currency Market prices...")
            data = await fetch_market_data("currency")
            logger.info(f"Currency Market data fetched: {data}")
            new_message = f"{data}\n⚡ Real-time data updates automatically using API!"
            current_text = query.message.text or ""
            logger.info(f"Currency Market callback. Current text: {current_text}, New text: {new_message}")
            if current_text != new_message:
                await query.message.edit_text(new_message, parse_mode='HTML')
                logger.info("Currency Market message updated successfully (edit).")
            else:
                logger.info("Skipping Currency Market edit: content unchanged.")
            await show_market_prices_menu(update, context)

        elif callback_data == "back_to_main":
            await show_main_menu(update, context)

        else:
            logger.warning(f"Unknown callback data received: {callback_data} from user {update.effective_user.id}")
            await query.message.edit_text("❌ Unknown command. Please try again.", parse_mode='HTML')

    except TelegramError as e:
        logger.error(f"Telegram error while handling callback: {e}")
        await query.message.reply_text("❌ An error occurred while handling the callback. Please try again.", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Unexpected error while handling callback: {e}")
        await query.message.reply_text("❌ An error occurred while handling the callback. Please try again.", parse_mode='HTML')

# Handler for unexpected text messages
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("Please select an option from the menu.", parse_mode='HTML')
        await show_main_menu(update, context)
        logger.info(f"User {update.effective_user.id} sent unexpected text: {update.message.text}")
    except TelegramError as e:
        logger.error(f"Telegram error while handling text message: {e}")
        await update.message.reply_text("❌ An error occurred while handling the text message. Please try again.", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Unexpected error while handling text message: {e}")
        await update.message.reply_text("❌ An error occurred while handling the text message. Please try again.", parse_mode='HTML')

# Error handler to catch and handle exceptions
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    
    # Handle specific errors
    if isinstance(context.error, Conflict):
        logger.error("Conflict error detected. This usually means multiple bot instances are running or a webhook is set.")
        if update and update.effective_message:
            await update.effective_message.reply_text("❌ A conflict occurred. The bot may be running elsewhere. Please try again later.", parse_mode='HTML')
        raise context.error  # Re-raise to stop the bot and allow a clean restart
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

    # Delete any existing webhook to ensure polling works
    try:
        application.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Deleted any existing webhook to ensure polling works.")
    except TelegramError as e:
        logger.error(f"Failed to delete webhook: {e}")
        exit(1)

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
