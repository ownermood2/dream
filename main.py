import os
import sys
import logging
import asyncio
import threading
from datetime import datetime
from waitress import serve
from src.core.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.INFO)

async def send_restart_confirmation(config: Config):
    """Send restart confirmation to owner if restart flag exists"""
    restart_flag_path = "data/.restart_flag"
    if os.path.exists(restart_flag_path):
        try:
            from telegram import Bot
            
            telegram_bot = Bot(token=config.telegram_token)
            confirmation_message = (
                "✅ Bot restarted successfully and is now online!\n\n"
                f"🕒 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "⚡ All systems operational"
            )
            
            await telegram_bot.send_message(
                chat_id=config.owner_id,
                text=confirmation_message
            )
            
            os.remove(restart_flag_path)
            logger.info(f"Restart confirmation sent to OWNER ({config.owner_id}) and flag removed")
            
        except Exception as e:
            logger.error(f"Failed to send restart confirmation: {e}")

async def run_polling_mode(config: Config):
    """Run bot in polling mode"""
    from telegram import Bot
    from src.core.quiz import QuizManager
    from src.core.database import DatabaseManager
    from src.bot.handlers import TelegramQuizBot
    from src.web.app import app
    
    logger.info("Starting in POLLING mode")
    
    # CRITICAL: Delete any existing webhook to prevent conflicts
    try:
        temp_bot = Bot(token=config.telegram_token)
        await temp_bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Deleted webhook - polling mode ready")
    except Exception as e:
        logger.warning(f"Could not delete webhook: {e}")
    
    flask_thread = threading.Thread(
        target=lambda: serve(app, host='0.0.0.0', port=config.port, threads=4),
        daemon=True
    )
    flask_thread.start()
    logger.info(f"✅ Production Flask server (Waitress) started on port {config.port}")
    
    # Create single DatabaseManager instance for all components
    db_manager = DatabaseManager()
    logger.info("Created shared DatabaseManager instance")
    
    # Inject DatabaseManager into QuizManager and TelegramQuizBot
    quiz_manager = QuizManager(db_manager=db_manager)
    bot = TelegramQuizBot(quiz_manager, db_manager=db_manager)
    await bot.initialize(config.telegram_token)
    
    await send_restart_confirmation(config)
    
    logger.info("Bot is running. Press Ctrl+C to stop.")
    
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received")
        if bot.application:
            await bot.application.stop()

# Initialize config at module level - NO validation at import time
config = Config.load(validate=False)

if __name__ == "__main__":
    try:
        # Validate config before running
        config.validate()
        
        mode = config.get_mode()
        
        if mode == "webhook":
            # Webhook mode - warn user to use gunicorn
            logger.warning("⚠️ WEBHOOK MODE DETECTED")
            logger.warning("⚠️ For production, use: gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT")
            logger.warning("⚠️ For development, set MODE=polling or remove WEBHOOK_URL")
            logger.info("Starting Flask dev server for testing...")
            
            # Import app only when needed
            from src.web.app import get_app, init_bot_webhook
            webhook_url = config.get_webhook_url()
            if webhook_url:
                init_bot_webhook(webhook_url)
            
            app = get_app()
            app.run(host="0.0.0.0", port=config.port, debug=False)
        else:
            # Polling mode - recommended
            logger.info("🚀 POLLING MODE - Starting bot...")
            asyncio.run(run_polling_mode(config))
            
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)
