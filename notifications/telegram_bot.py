"""
notifications/telegram_bot.py
─────────────────────────────
Simple Telegram bot integration for sending trade alerts.
"""

import httpx
from config.settings import settings
from utils.logger import logger

def send_telegram_message(message: str):
    """
    Send a message to the configured Telegram chat.
    
    Args:
        message: The text message to send. Supports Markdown.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        # Silent return if not configured, to avoid spamming logs
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        # Use a short timeout so we don't block the trading loop
        response = httpx.post(url, json=payload, timeout=5.0)
        
        if response.status_code != 200:
            logger.error(f"Failed to send Telegram message: {response.text}")
        else:
            logger.info("Telegram notification sent successfully.")
            
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
