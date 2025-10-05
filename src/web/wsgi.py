"""
WSGI Entry Point for Production Deployment

This module is used by gunicorn and other WSGI servers to run the Flask application.
It handles webhook mode initialization when deployed to platforms like Railway, Render, or Heroku.

Usage:
    gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT
"""

import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def create_application():
    """Create and configure the Flask application for WSGI deployment"""
    from src.web.app import get_app, init_bot_webhook
    from src.core.config import Config
    
    logger.info("Initializing application for WSGI server...")
    
    config = Config.load(validate=True)
    
    mode = config.get_mode()
    logger.info(f"Detected mode: {mode}")
    
    if mode == "webhook":
        webhook_url = config.get_webhook_url()
        if webhook_url:
            logger.info(f"Initializing webhook bot with URL: {webhook_url}")
            try:
                init_bot_webhook(webhook_url)
                logger.info("✅ Webhook bot initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize webhook bot: {e}")
                raise
        else:
            logger.warning("⚠️ Webhook mode detected but WEBHOOK_URL not set")
    
    app = get_app()
    logger.info(f"✅ Flask application created and ready on port {config.port}")
    
    return app

app = create_application()
