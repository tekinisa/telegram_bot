import logging
import os
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from binance.client import Client
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
from keep_alive import keep_alive  # keep_alive.py dosyasından fonksiyonu içe aktarıyoruz

# ---------------------------
# .env dosyasını yükle
# ---------------------------
load_dotenv()

# ---------------------------
# Binance API Ayarlarınız
# ---------------------------
BINANCE_API_KEY = "YOUR_BINANCE_API_KEY"         # Binance API anahtarınızı girin.
BINANCE_API_SECRET = "YOUR_BINANCE_API_SECRET"   # Binance API secret'ınızı girin.
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# ---------------------------
# Telegram Bot Ayarları (.env'den okunuyor)
# ---------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

# ---------------------------
# Logging Ayarları
# ---------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------
# Binance Tarama Fonksiyonları
# ---------------------------
def get_klines(symbol, interval, limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception as e:
        logger.error(f"Veri çekme hatası ({symbol}): {e}")
        return pd.DataFrame()
    
    df = pd.DataFrame(klines, columns=[
        'time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume',
        'trades', 'taker_base_volume', 'taker_quote_volume', 'ignore'])
    
    df = df.astype(float, errors='ignore')
    return df

def calculate_indicators(df):
    if df.empty:
        return df
    
    # EMA hesaplamaları
    df['EMA10'] = df['close'].ewm(span=10, adjust=False).mean()
    df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # RSI hesaplaması
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50)
    
    # Hacim SMA hesaplaması
    df['Volume_SMA20'] = df['volume'].rolling(window=20).mean()
    
    # ADX hesaplaması
    df['TR'] = np.maximum(df['high'] - df['low'],
                          np.maximum(abs(df['high'] - df['close'].shift()),
                                     abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['TR'].rolling(window=14).mean()
    df['DI_plus'] = 100 * ((df['high'] - df['high'].shift()).where(df['high'] - df['high'].shift() > 0, 0)).rolling(window=14).mean() / df['ATR']
    df['DI_minus'] = 100 * ((df['low'].shift() - df['low']).where(df['low'].shift() - df['low'] > 0, 0)).rolling(window=14).mean() / df['ATR']
    df['DX'] = abs(df['DI_plus'] - df['DI_minus']) / (df['DI_plus'] + df['DI_minus']) * 100
    df['ADX'] = df['DX'].rolling(window=14).mean()
    
    return df

def scan_market(interval):
    try:
        exchange_info = client.get_exchange_info()
        symbols = [s['symbol'] for s in exchange_info['symbols']
                   if s['symbol'].endswith('USDT') and s['status'] == 'TRADING' and s['isSpotTradingAllowed']]
    except Exception as e:
        logger.error(f"API erişim hatası: {e}")
        return []
    
    matching_coins = []
    for symbol in symbols:
        try:
            df = get_klines(symbol, interval)
            df = calculate_indicators(df)
            if df.empty or len(df) < 50:
                continue
            last_row = df.iloc[-1]
            if (last_row['EMA10'] > last_row['EMA20'] and
                last_row['EMA20'] > last_row['EMA50'] and
                last_row['RSI'] > 45 and
                last_row['RSI'] > df.iloc[-2]['RSI'] and
                last_row['volume'] > last_row['Volume_SMA20'] and
                last_row['ADX'] > 20):
                matching_coins.append(symbol)
        except Exception as e:
            logger.error(f"{symbol} için tarama sırasında hata: {e}")
            continue
            
    return matching_coins

# ---------------------------
# Telegram Bot Komut İşleyicileri
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Merhaba, ben Kripto Tarayıcı Bot!\n\n"
        "Grubumuza eklediğinizde, saat başı otomatik sinyal gönderiyorum.\n"
        "Ayrıca /scan komutunu kullanarak manuel tarama da yapabilirsiniz."
    )

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Tarama başlatılıyor, lütfen bekleyin...")
    coins_15m = scan_market('15m')
    coins_1h = scan_market('1h')
    coins_4h = scan_market('4h')
    
    msg = "<b>🔍 Tarama Sonuçları:</b>\n\n"
    msg += "<b>15 Dakikalık:</b> {}\n".format(', '.join(coins_15m) if coins_15m else "Yok")
    msg += "<b>1 Saatlik:</b> {}\n".format(', '.join(coins_1h) if coins_1h else "Yok")
    msg += "<b>4 Saatlik:</b> {}\n".format(', '.join(coins_4h) if coins_4h else "Yok")
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    coins_15m = scan_market('15m')
    coins_1h = scan_market('1h')
    coins_4h = scan_market('4h')
    
    msg = "<b>⏰ Otomatik Tarama Sonuçları:</b>\n\n"
    msg += "<b>15 Dakikalık:</b> {}\n".format(', '.join(coins_15m) if coins_15m else "Yok")
    msg += "<b>1 Saatlik:</b> {}\n".format(', '.join(coins_1h) if coins_1h else "Yok")
    msg += "<b>4 Saatlik:</b> {}\n".format(', '.join(coins_4h) if coins_4h else "Yok")
    
    await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode=ParseMode.HTML)

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan))
    
    # Her saat otomatik tarama için job queue'ya görev ekleniyor.
    application.job_queue.run_repeating(scheduled_scan, interval=3600, first=10, chat_id=CHAT_ID)
    
    application.run_polling()

if __name__ == '__main__':
    keep_alive()  # Flask keep-alive servisini başlatıyoruz.
    main()
