import os
import logging
import asyncio
import threading
from concurrent.futures import Future
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response
from telegram import Update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

quiz_manager = None
telegram_bot = None
event_loop = None
loop_thread = None
app_start_time = datetime.now()

def start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run event loop in background thread"""
    asyncio.set_event_loop(loop)
    loop.run_forever()

def run_coroutine_threadsafe(coro, loop):
    """Submit coroutine to background event loop with done callback for logging"""
    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        
        def done_callback(fut):
            try:
                result = fut.result()
                logger.info(f"Update processed successfully: {result}")
            except Exception as e:
                logger.error(f"Update processing failed with exception: {e}", exc_info=True)
        
        future.add_done_callback(done_callback)
        logger.info("Update submitted to event loop successfully")
    else:
        logger.error("Event loop not running, cannot process update")

def create_app():
    """Flask app factory - creates and initializes app"""
    global quiz_manager
    
    session_secret = os.environ.get("SESSION_SECRET")
    if not session_secret:
        raise ValueError("SESSION_SECRET environment variable is required")
    
    flask_app = Flask(__name__, 
                template_folder=os.path.join(root_dir, 'templates'),
                static_folder=os.path.join(root_dir, 'static'))
    flask_app.secret_key = session_secret
    
    if quiz_manager is None:
        try:
            from src.core.quiz import QuizManager
            quiz_manager = QuizManager()
            logger.info("Quiz Manager initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Quiz Manager: {e}")
            raise
    
    return flask_app

class _AppProxy:
    """Proxy that defers Flask app creation until first use"""
    def __init__(self):
        self._real_app = None
        self._deferred_registrations = []
    
    def _get_real_app(self):
        """Get or create the real Flask app"""
        if self._real_app is None:
            self._real_app = create_app()
            # Apply all deferred route registrations
            for method_name, args, kwargs, func in self._deferred_registrations:
                getattr(self._real_app, method_name)(*args, **kwargs)(func)
            self._deferred_registrations.clear()
            logger.info("Flask app created and routes registered")
        return self._real_app
    
    def route(self, *args, **kwargs):
        """Defer route registration until app is created"""
        def decorator(func):
            self._deferred_registrations.append(('route', args, kwargs, func))
            return func
        return decorator
    
    def __call__(self, environ, start_response):
        """WSGI callable"""
        return self._get_real_app()(environ, start_response)
    
    def __getattr__(self, name):
        """Proxy all other attributes to real app"""
        return getattr(self._get_real_app(), name)

app = _AppProxy()

def get_app():
    """Get or create Flask app instance"""
    return app._get_real_app()

async def init_bot():
    """Initialize and start the Telegram bot in polling mode"""
    global telegram_bot, quiz_manager
    try:
        from src.bot.handlers import TelegramQuizBot
        from src.core.quiz import QuizManager
        from src.core.database import DatabaseManager

        token = os.environ.get("TELEGRAM_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_TOKEN environment variable is required")

        # Create shared DatabaseManager instance
        db_manager = DatabaseManager()
        logger.info("Created shared DatabaseManager instance for polling mode")
        
        # Initialize QuizManager with shared DatabaseManager
        if quiz_manager is None:
            quiz_manager = QuizManager(db_manager=db_manager)
            logger.info("Quiz Manager initialized with shared DatabaseManager")

        telegram_bot = TelegramQuizBot(quiz_manager, db_manager=db_manager)
        await telegram_bot.initialize(token)

        logger.info("Telegram bot initialized successfully in polling mode")
        return telegram_bot
    except Exception as e:
        logger.error(f"Failed to initialize Telegram bot: {e}")
        raise

def init_bot_webhook(webhook_url: str):
    """Initialize bot in webhook mode with persistent event loop"""
    global telegram_bot, quiz_manager, event_loop, loop_thread
    try:
        from src.bot.handlers import TelegramQuizBot
        from src.core.quiz import QuizManager
        from src.core.database import DatabaseManager
        
        token = os.environ.get("TELEGRAM_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_TOKEN environment variable is required")
        
        # Create shared DatabaseManager instance (same pattern as polling mode)
        db_manager = DatabaseManager()
        logger.info("Created shared DatabaseManager instance for webhook mode")
        
        # Initialize QuizManager with shared DatabaseManager
        if quiz_manager is None:
            quiz_manager = QuizManager(db_manager=db_manager)
            logger.info("Quiz Manager initialized with shared DatabaseManager")
        
        # Create persistent event loop in background thread
        event_loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=start_background_loop, args=(event_loop,), daemon=True)
        loop_thread.start()
        logger.info("Started persistent event loop in background thread")
        
        # Initialize bot with shared DatabaseManager (same pattern as polling mode)
        telegram_bot = TelegramQuizBot(quiz_manager, db_manager=db_manager)
        future = asyncio.run_coroutine_threadsafe(
            telegram_bot.initialize_webhook(token, webhook_url),
            event_loop
        )
        future.result(timeout=30)  # Wait for initialization to complete
        
        logger.info(f"Webhook bot initialized with URL: {webhook_url}")
        return telegram_bot
    except Exception as e:
        logger.error(f"Failed to initialize webhook bot: {e}")
        raise

@app.route('/')
def index():
    """Simple health check endpoint for deployment platforms"""
    return jsonify({'status': 'ok'})

@app.route('/health')
def health():
    """Health check endpoint for monitoring services"""
    return jsonify({'status': 'ok'})

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint to receive and process Telegram updates"""
    global telegram_bot, event_loop
    
    try:
        logger.info("Webhook received POST request")
        
        if not telegram_bot or not telegram_bot.application:
            logger.error("Bot not initialized for webhook")
            return jsonify({'status': 'error', 'message': 'Bot not initialized'}), 500
        
        update_data = request.get_json(force=True)
        logger.debug(f"Received update with {len(update_data)} fields")
        
        if not update_data:
            logger.warning("Empty update data received")
            return jsonify({'status': 'ok'}), 200
        
        try:
            update = Update.de_json(update_data, telegram_bot.application.bot)
            logger.info(f"Parsed update object: update_id={update.update_id}")
        except Exception as e:
            logger.error(f"Failed to parse update from JSON: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': 'Invalid update format'}), 400
        
        # Submit update to persistent event loop (non-blocking)
        try:
            run_coroutine_threadsafe(
                telegram_bot.application.process_update(update),
                event_loop
            )
            logger.info(f"Successfully queued update {update.update_id} for processing")
        except Exception as e:
            logger.error(f"Failed to submit update to event loop: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': 'Failed to queue update'}), 500
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/questions', methods=['GET'])
def get_questions():
    if not quiz_manager:
        return jsonify({"status": "error", "message": "Quiz manager not initialized"}), 500
    return jsonify(quiz_manager.get_all_questions())

@app.route('/api/questions', methods=['POST'])
def add_question():
    try:
        if not quiz_manager:
            return jsonify({"status": "error", "message": "Quiz manager not initialized"}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        question_data = [{
            'question': data['question'],
            'options': data['options'],
            'correct_answer': data['correct_answer']
        }]
        result = quiz_manager.add_questions(question_data)
        return jsonify(result)
    except KeyError as e:
        return jsonify({"status": "error", "message": f"Missing required field: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error adding question: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/api/questions/<int:question_id>', methods=['PUT'])
def edit_question(question_id):
    try:
        if not quiz_manager:
            return jsonify({"status": "error", "message": "Quiz manager not initialized"}), 500
        
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        if quiz_manager.edit_question_by_db_id(question_id, data):
            return jsonify({"status": "success", "message": "Question updated successfully"})
        else:
            return jsonify({"status": "error", "message": "Question not found"}), 404
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except KeyError as e:
        return jsonify({"status": "error", "message": f"Missing field: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"Error editing question {question_id}: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/api/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    try:
        if not quiz_manager:
            return jsonify({"status": "error", "message": "Quiz manager not initialized"}), 500
        
        if quiz_manager.delete_question_by_db_id(question_id):
            return jsonify({"status": "success", "message": "Question deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Question not found"}), 404
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error deleting question {question_id}: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/metrics')
def metrics():
    """Prometheus metrics endpoint"""
    try:
        uptime = (datetime.now() - app_start_time).total_seconds()
        
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent(interval=0.1)
        
        if not quiz_manager:
            logger.error("Quiz manager not initialized for metrics")
            return Response("# Error: Quiz manager not initialized\n", mimetype='text/plain'), 500
        
        metrics_data = quiz_manager.db.get_metrics_summary()
        
        lines = []
        
        lines.append(f"missquiz_bot_uptime_seconds {uptime:.0f}")
        lines.append(f"missquiz_bot_memory_usage_mb {memory_mb:.2f}")
        lines.append(f"missquiz_bot_cpu_percent {cpu_percent:.2f}")
        
        lines.append(f"missquiz_users_total {metrics_data['total_users']}")
        lines.append(f"missquiz_users_active_24h {metrics_data['active_users_24h']}")
        lines.append(f"missquiz_users_active_7d {metrics_data['active_users_7d']}")
        lines.append(f"missquiz_groups_total {metrics_data['total_groups']}")
        lines.append(f"missquiz_groups_active {metrics_data['active_groups']}")
        lines.append(f"missquiz_quiz_questions_total {metrics_data['total_questions']}")
        
        lines.append(f"missquiz_quiz_attempts_24h {metrics_data['quiz_attempts_24h']}")
        lines.append(f"missquiz_quiz_accuracy_percent_24h {metrics_data['quiz_accuracy_24h']:.2f}")
        lines.append(f"missquiz_response_time_avg_ms_24h {metrics_data['avg_response_time_24h']:.2f}")
        lines.append(f"missquiz_commands_executed_24h {metrics_data['commands_24h']}")
        lines.append(f"missquiz_error_rate_percent_24h {metrics_data['error_rate_24h']:.2f}")
        lines.append(f"missquiz_rate_limit_violations_24h {metrics_data['rate_limit_violations_24h']}")
        
        lines.append(f"missquiz_broadcasts_total {metrics_data['total_broadcasts']}")
        lines.append(f"missquiz_broadcast_success_rate_percent {metrics_data['broadcast_success_rate']:.2f}")
        
        response = Response('\n'.join(lines) + '\n', mimetype='text/plain')
        response.headers['Cache-Control'] = 'max-age=30'
        return response
        
    except Exception as e:
        logger.error(f"Error generating metrics: {e}")
        return Response("# Error generating metrics\n", mimetype='text/plain'), 500
