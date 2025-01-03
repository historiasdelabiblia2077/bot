import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

# Token del bot (Asegúrate de usar el token correcto)
TOKEN = '7759749712:AAE3RlSXQ4b09hUAFxleSINWcvKvLeHLM6A'

# Configuración de logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Variables globales para manejar la frecuencia de las alertas
alert_frequency = 180  # En segundos (por defecto, cada 2 minutos)

# Función para obtener las criptomonedas más relevantes de CoinGecko
def get_top_crypto_data():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "percent_change_24h",  # Ordenar por el cambio en 24 horas
        "per_page": 10,  # Top 10
        "page": 1,
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        top_cryptos = []
        for coin in data:
            # Filtrar monedas no deseadas (BNB, USDT, USDC)
            if coin['symbol'].lower() in ['bnb', 'usdt', 'usdc']:
                continue

            price_change_1h = coin.get('price_change_percentage_1h', 0)
            price_change_24h = coin.get('price_change_percentage_24h', 0)
            
            top_cryptos.append({
                'id': coin['id'],
                'name': coin['name'],
                'symbol': coin['symbol'],
                'current_price': coin['current_price'],
                'price_change_1h': price_change_1h,
                'price_change_24h': price_change_24h,
                'market_cap': coin['market_cap'],
                'total_volume': coin['total_volume'],
                'all_time_high': coin.get('ath', 0)  # Precio más alto histórico
            })

        return top_cryptos
    except Exception as e:
        logger.error(f"Error al obtener los datos de las criptomonedas: {e}")
        return None

# Función para obtener el precio de una criptomoneda en Bitget
def get_price_from_bitget(crypto_symbol):
    url = f"https://api.bitget.com/api/spot/v1/market/ticker?symbol={crypto_symbol}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data and 'data' in data:
            return float(data['data']['last'])  # El precio de la criptomoneda
        return None
    except Exception as e:
        logger.error(f"Error al obtener el precio de {crypto_symbol} en Bitget: {e}")
        return None

# Función para obtener el precio de una criptomoneda en Binance
def get_price_from_binance(crypto_symbol):
    symbol = crypto_symbol.upper() + "USDT"  # Binance requiere que se pase el símbolo junto con USDT (como BTCUSDT)
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"

    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if 'price' in data:
            return float(data['price'])  # El precio de la criptomoneda
        return None
    except Exception as e:
        logger.error(f"Error al obtener el precio de {crypto_symbol} en Binance: {e}")
        return None

# Función para obtener el precio de una criptomoneda en Kraken
def get_price_from_kraken(crypto_symbol):
    url = f"https://api.kraken.com/0/public/Ticker?pair={crypto_symbol}USD"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if 'result' in data and data['result']:
            return float(data['result'][list(data['result'].keys())[0]]['c'][0])  # Precio
        return None
    except Exception as e:
        logger.error(f"Error al obtener el precio de {crypto_symbol} en Kraken: {e}")
        return None

# Función para obtener el precio de una criptomoneda en KuCoin
def get_price_from_kucoin(crypto_symbol):
    url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={crypto_symbol}-USDT"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if 'data' in data:
            return float(data['data']['price'])  # Precio
        return None
    except Exception as e:
        logger.error(f"Error al obtener el precio de {crypto_symbol} en KuCoin: {e}")
        return None

# Función para generar alertas especiales para DOGE, HBAR, SEI
def generate_special_alert(crypto):
    shock_price = crypto['current_price']
    price_change_1h = crypto['price_change_1h']
    price_change_24h = crypto['price_change_24h']

    # Condición para generar alerta especial (si el cambio es superior al 10%)
    if abs(price_change_1h) > 10 or abs(price_change_24h) > 10:
        signal = (f"🚨🚨 **ALERTA EXTREMA: {crypto['name']} ({crypto['symbol']})** 🚨🚨\n\n"
                  f"🔥 **CAMBIO BRUSCO DETECTADO** 🔥\n"
                  f"**PRECIO ACTUAL**: ${shock_price:.2f}\n"
                  f"**CAMBIO EN 1H**: {price_change_1h:.2f}%\n"
                  f"**CAMBIO EN 24H**: {price_change_24h:.2f}%\n\n"
                  f"🔴 **SE RECOMIENDA ESTAR ATENTO** 🔴\n"
                  f"**CAMBIOS ABRUPTOS DETECTADOS**: El mercado está reaccionando rápidamente. "
                  f"Esté preparado para tomar decisiones de compra o venta.\n\n"
                  f"⚠️ **IMPORTANTE**: Este comportamiento podría continuar o revertirse rápidamente. "
                  f"Recuerde tomar decisiones informadas y no basarse solo en señales automáticas.")
        return signal
    return None

# Función para generar señales de trading con alertas automáticas
def generate_trade_signal(crypto, bitget_price, binance_price, kraken_price, kucoin_price):
    shock_price = crypto['current_price']
    dist_percentage = (shock_price / crypto['all_time_high'] - 1) * 100 if crypto['all_time_high'] > 0 else 0
    
    objetivo_compra = shock_price * 0.95  # 5% por debajo del precio actual
    objetivo_venta = shock_price * 1.05  # 5% por encima del precio actual
    
    prob_1h = max(crypto['price_change_1h'], 0)  # Asegurarse que la probabilidad no sea negativa
    prob_24h = max(crypto['price_change_24h'], 0)  # Asegurarse que la probabilidad no sea negativa

    prob_1h = min(prob_1h, 100)
    prob_24h = min(prob_24h, 100)

    # Calcular la probabilidad combinada de 5 fuentes (Bitget, Binance, Kraken, KuCoin, CoinGecko)
    prob_kraken = max(kraken_price / shock_price - 1, 0) * 100
    prob_kucoin = max(kucoin_price / shock_price - 1, 0) * 100

    combined_prob = 1 - (1 - prob_1h / 100) * (1 - prob_24h / 100) * (1 - prob_kraken / 100) * (1 - prob_kucoin / 100)
    combined_prob_percent = combined_prob * 100  # Convertir a porcentaje

    # Resumen de probabilidades y alertas
    prob_summary = (
        f"**Probabilidades**:\n"
        f"   * **Escenario 1 (1h)** 🔼 Probabilidad: {prob_1h:.2f}%\n"
        f"   * **Escenario 2 (24h)** 🔼 Probabilidad: {prob_24h:.2f}%\n"
        f"   * **Probabilidad combinada**: {combined_prob_percent:.2f}%\n\n"
    )
    
    signal = (f"📕 **ALERTA: {crypto['name']} ({crypto['symbol']})**\n\n"
              f"**PRECIO ACTUAL**: ${shock_price:.2f}\n"
              f"**DISTANCIA AL PRECIO MÁS ALTO HISTÓRICO**: {dist_percentage:.2f}%\n"
              f"**OBJETIVO DE COMPRA**: ${objetivo_compra:.5f}\n"
              f"**OBJETIVO DE VENTA**: ${objetivo_venta:.5f}\n\n"
              f"{prob_summary}")

    return signal

# Comando para detener las alertas
async def stop_alerts(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    logger.info(f"Usuario con chat_id {chat_id} ha detenido las alertas.")
    context.job_queue.stop()
    await update.message.reply_text("Las alertas han sido detenidas. Si deseas recibir alertas nuevamente, escribe /start.")

# Comando de ayuda
async def help_command(update: Update, context: CallbackContext):
    help_text = (
        "🆘 **AYUDA** 🆘\n\n"
        "¡Hola! Soy el Oráculo CryptoCookie, tu asistente de alertas de criptomonedas. Aquí tienes algunos comandos que puedes usar:\n\n"
        "/start - Inicia las alertas de criptomonedas y recibe actualizaciones cada 2 minutos.\n"
        "/stop - Detén las alertas de criptomonedas (puedes activarlas nuevamente con /start).\n"
        "/help - Muestra este mensaje de ayuda.\n\n"
        "Recibirás alertas sobre los movimientos de criptomonedas, especialmente Dogecoin (DOGE), Hedera (HBAR), y Sei (SEI)."
        " Estas alertas incluyen cambios en el precio y señales de compra/venta.\n\n"
        "¡Espero que te guste y si tienes alguna duda, no dudes en preguntarme!"
    )
    await update.message.reply_text(help_text)

# Comando de bienvenida
async def start(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    logger.info(f"Usuario con chat_id {chat_id} ha iniciado el bot.")
    
    context.job_queue.run_repeating(send_crypto_prices, interval=alert_frequency, first=0, chat_id=chat_id)
    
    welcome_text = (
        "¡Hola! Soy el Oráculo CryptoCookie. Te enviaré alertas con señales de compra y venta basadas en el análisis del mercado.\n\n"
        "Para obtener ayuda, usa /help.\n"
        "Si deseas detener las alertas, usa /stop.\n\n"
        "Recibirás actualizaciones cada 2 minutos sobre las principales criptomonedas."
    )
    await update.message.reply_text(welcome_text)

# Función que se ejecuta cada 2 minutos para enviar alertas
async def send_crypto_prices(context: CallbackContext):
    top_cryptos = get_top_crypto_data()

    if top_cryptos:
        for crypto in top_cryptos:
            # Obtener los precios de las plataformas
            bitget_price = get_price_from_bitget(crypto['symbol'].upper())
            binance_price = get_price_from_binance(crypto['symbol'])
            kraken_price = get_price_from_kraken(crypto['symbol'].upper())
            kucoin_price = get_price_from_kucoin(crypto['symbol'].upper())

            # Verificar alertas especiales para Dogecoin, HBAR y SEI
            if crypto['symbol'].lower() == 'doge':
                special_alert = generate_special_alert(crypto)
                if special_alert:
                    chat_id = context.job.chat_id
                    await context.bot.send_message(chat_id=chat_id, text=special_alert)
            
            elif crypto['symbol'].lower() == 'hbar':
                special_alert = generate_special_alert(crypto)
                if special_alert:
                    chat_id = context.job.chat_id
                    await context.bot.send_message(chat_id=chat_id, text=special_alert)
            
            elif crypto['symbol'].lower() == 'sei':
                special_alert = generate_special_alert(crypto)
                if special_alert:
                    chat_id = context.job.chat_id
                    await context.bot.send_message(chat_id=chat_id, text=special_alert)

            # Generar la señal de trading regular para todas las criptos
            trade_signal = generate_trade_signal(crypto, bitget_price, binance_price, kraken_price, kucoin_price)
            crypto_message = trade_signal
            
            chat_id = context.job.chat_id  # Obtener el chat_id desde el job context
            await context.bot.send_message(chat_id=chat_id, text=crypto_message)

        logger.info(f"Mensajes enviados a {context.job.chat_id}")
    else:
        await context.bot.send_message(chat_id=context.job.chat_id, text="Hubo un error al obtener los datos. Intenta nuevamente más tarde.")

# Función principal
def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_alerts))
    application.add_handler(CommandHandler("help", help_command))

    application.run_polling()

if __name__ == '__main__':
    main()
