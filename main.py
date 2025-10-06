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

def send_restart_confirmation_sync(config: Config):
    """Send restart confirmation to owner if restart flag exists"""
    restart_flag_path = "data/.restart_flag"
    if os.path.exists(restart_flag_path):
        try:
            async def send_message():
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
            
            asyncio.run(send_message())
            os.remove(restart_flag_path)
            logger.info(f"Restart confirmation sent to OWNER ({config.owner_id}) and flag removed")
            
        except Exception as e:
            logger.error(f"Failed to send restart confirmation: {e}")

def run_polling_mode(config: Config):
    """Run bot in polling mode with automatic conflict recovery"""
    from telegram import Bot
    from telegram.error import Conflict, NetworkError, TimedOut
    from src.core.quiz import QuizManager
    from src.core.database import DatabaseManager
    from src.bot.handlers import TelegramQuizBot
    from src.web.app import app
    import time
    
    logger.info("🚀 Starting in POLLING mode")
    
    # CRITICAL: Delete any existing webhook to prevent conflicts (async operation)
    async def cleanup_webhook():
        max_webhook_retry = 3
        for attempt in range(max_webhook_retry):
            try:
                temp_bot = Bot(token=config.telegram_token)
                webhook_info = await temp_bot.get_webhook_info()
                
                if webhook_info.url:
                    logger.info(f"⚠️ Found existing webhook: {webhook_info.url}")
                    await temp_bot.delete_webhook(drop_pending_updates=True)
                    logger.info("✅ Deleted webhook - polling mode ready")
                    await asyncio.sleep(2)
                else:
                    logger.info("✅ No webhook found - polling mode ready")
                return True
            except (NetworkError, TimedOut) as e:
                if attempt < max_webhook_retry - 1:
                    logger.warning(f"Network error deleting webhook (attempt {attempt + 1}/{max_webhook_retry}): {e}")
                    await asyncio.sleep(3)
                else:
                    logger.critical(f"❌ Failed to delete webhook after {max_webhook_retry} attempts: {e}")
                    raise RuntimeError(f"Webhook cleanup failed after {max_webhook_retry} attempts")
            except Exception as e:
                logger.critical(f"❌ Fatal error checking/deleting webhook: {e}")
                raise
        return False
    
    # Run initial webhook cleanup
    if not asyncio.run(cleanup_webhook()):
        logger.critical("❌ Webhook cleanup failed. Aborting.")
        raise RuntimeError("Webhook cleanup failed - cannot start polling")
    
    # Start Flask server in background
    flask_thread = threading.Thread(
        target=lambda: serve(app, host=config.host, port=config.port, threads=4),
        daemon=True
    )
    flask_thread.start()
    logger.info(f"✅ Production Flask server (Waitress) started on {config.host}:{config.port}")
    logger.info(f"📁 Database path: {config.database_path}")
    logger.info(f"🔧 Mode: POLLING (automatic conflict recovery enabled)")
    
    # Create single DatabaseManager instance for all components
    db_manager = DatabaseManager()
    logger.info("Created shared DatabaseManager instance")
    
    # Inject DatabaseManager into QuizManager and TelegramQuizBot
    quiz_manager = QuizManager(db_manager=db_manager)
    bot = TelegramQuizBot(quiz_manager, db_manager=db_manager)
    
    # Configure bot (add handlers and job queues, but don't start yet)
    async def configure_bot():
        await bot.initialize(config.telegram_token)
        logger.info("✅ Bot configured successfully")
    
    asyncio.run(configure_bot())
    
    # Send restart confirmation
    send_restart_confirmation_sync(config)
    
    logger.info("✅ Bot is running. Press Ctrl+C to stop.")
    
    # Runtime conflict recovery loop for run_polling()
    max_runtime_conflict_retry = 3
    for runtime_attempt in range(max_runtime_conflict_retry):
        try:
            bot.application.run_polling()
            break  # Normal exit (e.g., shutdown)
        except Conflict as e:
            if runtime_attempt < max_runtime_conflict_retry - 1:
                logger.error(f"⚠️ Runtime conflict detected (attempt {runtime_attempt + 1}/{max_runtime_conflict_retry}): {e}")
                logger.info("🔄 Auto-recovery: Cleaning webhook and restarting polling...")
                asyncio.run(cleanup_webhook())
                time.sleep(2)
            else:
                logger.critical(f"❌ Runtime conflict persists after {max_runtime_conflict_retry} attempts. Aborting.")
                raise
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received")
            break
        except Exception as e:
            logger.critical(f"❌ Fatal error during polling: {e}")
            raise

# Initialize config at module level - NO validation at import time
config = Config.load(validate=False)

if __name__ == "__main__":
    try:
        # Validate config before running
        config.validate()
        
        mode = config.get_mode()
        
        if mode == "webhook":
            # Webhook mode
            logger.info("🌐 WEBHOOK MODE DETECTED")
            logger.info(f"📁 Database path: {config.database_path}")
            logger.info(f"🔧 Mode: WEBHOOK (use gunicorn for production)")
            logger.warning("⚠️ For production, use: gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT")
            logger.info(f"🚀 Starting Flask server on {config.host}:{config.port}...")
            
            # Import app only when needed
            from src.web.app import get_app, init_bot_webhook
            webhook_url = config.get_webhook_url()
            if webhook_url:
                logger.info(f"✅ Setting webhook: {webhook_url}")
                init_bot_webhook(webhook_url)
            else:
                logger.error("❌ WEBHOOK_URL not set! Bot will not receive updates.")
            
            app = get_app()
            app.run(host=config.host, port=config.port, debug=False)
        else:
            # Polling mode - recommended
            logger.info("🚀 POLLING MODE - Starting bot...")
            run_polling_mode(config)
            
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)
