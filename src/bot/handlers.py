import os
import sys
import logging
import traceback
import asyncio
import json
import psutil
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import List
from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ChatMemberHandler,
    ContextTypes,
    CallbackQueryHandler,
    PicklePersistence
)
from telegram.constants import ParseMode
from telegram.error import Conflict, BadRequest
from src.core import config
from src.core.database import DatabaseManager
from src.bot.dev_commands import DeveloperCommands
from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

class TelegramQuizBot:
    def __init__(self, quiz_manager, db_manager: DatabaseManager | None = None):
        """Initialize the quiz bot with enhanced features - OPTIMIZED with caching"""
        self.quiz_manager = quiz_manager
        self.application = None
        self.user_command_cooldowns = defaultdict(dict)  # {user_id: {command: timestamp}}
        self.USER_COMMAND_COOLDOWN = 60  # 60 seconds cooldown for user commands in groups
        self.command_history = defaultdict(lambda: deque(maxlen=10))  # Store last 10 commands per chat
        self.cleanup_interval = 3600  # 1 hour in seconds
        self.bot_start_time = datetime.now()
        
        self._stats_cache = None
        self._stats_cache_time = None
        self._stats_cache_duration = timedelta(seconds=30)
        
        self._developer_cache = {}
        self._developer_cache_time = {}
        self._developer_cache_duration = timedelta(seconds=10)
        
        self._user_info_cache = {}
        self._user_info_cache_time = {}
        self._user_info_cache_duration = timedelta(seconds=300)
        
        self._leaderboard_cache = None
        self._leaderboard_cache_time = None
        self._leaderboard_cache_duration = timedelta(seconds=60)
        self._cache_lock = asyncio.Lock()  # Thread-safe cache access
        
        self.db = db_manager if db_manager else DatabaseManager()
        self.dev_commands = DeveloperCommands(self.db, quiz_manager)
        self.rate_limiter = RateLimiter()
        
        logger.info("TelegramQuizBot initialized with performance optimizations: user cache, leaderboard cache, rate limiting")

    def _add_or_update_user_cached(self, user_id: int, username: str | None = None, first_name: str | None = None, last_name: str | None = None):
        """OPTIMIZATION 1: Cached user info update - reduces redundant DB writes"""
        current_time = datetime.now()
        user_key = f"{user_id}_{username}_{first_name}_{last_name}"
        
        if user_id in self._user_info_cache:
            cached_key, cache_time = self._user_info_cache[user_id]
            if cached_key == user_key and current_time - cache_time < self._user_info_cache_duration:
                logger.debug(f"Using cached user info for {user_id} (optimization)")
                return
        
        self.db.add_or_update_user(user_id, username, first_name, last_name)
        self._user_info_cache[user_id] = (user_key, current_time)
        logger.debug(f"Updated and cached user info for {user_id}")
    
    def _track_pm_access(self, user_id: int, chat_type: str):
        """Universal PM access tracking - call from ALL command handlers in PM"""
        try:
            if chat_type == 'private':
                self.db.set_user_pm_access(user_id, True)
                logger.debug(f"✅ PM ACCESS TRACKED: User {user_id}")
        except Exception as e:
            logger.error(f"Error tracking PM access: {e}")
    
    def _queue_activity_log(self, activity_type: str, user_id: int | None = None, chat_id: int | None = None, 
                           username: str | None = None, chat_title: str | None = None, command: str | None = None, 
                           details: dict | None = None, success: bool = True, response_time_ms: int | None = None):
        """Log activity directly to database (synchronous - works in both polling and webhook modes)"""
        try:
            self.db.log_activity(
                activity_type=activity_type,
                user_id=user_id,
                chat_id=chat_id,
                username=username,
                chat_title=chat_title,
                command=command,
                details=details,
                success=success,
                response_time_ms=response_time_ms
            )
        except Exception as e:
            logger.error(f"Error logging activity: {e}")
    
    async def _get_leaderboard_cached(self, limit: int = 1000, offset: int = 0):
        """OPTIMIZATION 3: Get cached leaderboard data with thread-safe access"""
        async with self._cache_lock:
            current_time = datetime.now()
            cache_valid = (self._leaderboard_cache is not None and 
                          self._leaderboard_cache_time is not None and 
                          current_time - self._leaderboard_cache_time < self._leaderboard_cache_duration)
            
            if cache_valid:
                logger.debug("Using cached leaderboard (optimization)")
                return self._leaderboard_cache
            
            # Run blocking DB call in thread to avoid blocking event loop
            leaderboard, total = await asyncio.to_thread(
                self.db.get_leaderboard_realtime, limit=limit, offset=offset
            )
            self._leaderboard_cache = (leaderboard, total)
            self._leaderboard_cache_time = current_time
            logger.debug(f"Fetched and cached leaderboard with {len(leaderboard)} users")
            return leaderboard, total
    
    async def _preload_leaderboard(self):
        """OPTIMIZATION 3: Pre-load leaderboard on startup"""
        try:
            await self._get_leaderboard_cached(limit=1000, offset=0)
            logger.info("Leaderboard pre-loaded successfully")
        except Exception as e:
            logger.error(f"Error pre-loading leaderboard: {e}")

    def check_user_command_cooldown(self, user_id: int, command: str, chat_type: str) -> tuple[bool, int]:
        """Check if user command is on cooldown (only in groups)
        
        Args:
            user_id: User's Telegram ID
            command: Command name (without /)
            chat_type: Type of chat ('private', 'group', 'supergroup')
            
        Returns:
            tuple: (is_allowed, remaining_seconds)
        """
        # No cooldown in private chats
        if chat_type == "private":
            return True, 0
        
        # Check cooldown for groups
        current_time = time.time()
        last_used = self.user_command_cooldowns[user_id].get(command, 0)
        time_passed = current_time - last_used
        
        if time_passed < self.USER_COMMAND_COOLDOWN:
            remaining = int(self.USER_COMMAND_COOLDOWN - time_passed)
            return False, remaining
        
        # Update last used time
        self.user_command_cooldowns[user_id][command] = current_time
        return True, 0

    async def ensure_group_registered(self, chat, context: ContextTypes.DEFAULT_TYPE | None = None):
        """Register group in database for broadcasts - works regardless of admin status"""
        try:
            if chat.type in ["group", "supergroup"]:
                chat_title = chat.title or chat.username or "(No Title)"
                self.db.add_or_update_group(chat.id, chat_title, chat.type)
                logger.debug(f"Registered group {chat.id} ({chat_title}) in database")
        except Exception as e:
            logger.error(f"Failed to register group {chat.id}: {e}")

    async def backfill_groups_startup(self):
        """Migrate active_chats to database groups table on startup"""
        try:
            if not self.application:
                logger.error("Application not initialized in backfill_groups_startup")
                return
            
            active_chats = self.quiz_manager.get_active_chats()
            logger.info(f"Backfilling {len(active_chats)} groups from active_chats to database")
            
            registered_count = 0
            for chat_id in active_chats:
                try:
                    chat = await self.application.bot.get_chat(chat_id)
                    if chat.type in ["group", "supergroup"]:
                        chat_title = chat.title or chat.username or "(No Title)"
                        self.db.add_or_update_group(chat.id, chat_title, chat.type)
                        registered_count += 1
                        logger.debug(f"Backfilled group {chat.id} ({chat_title})")
                except Exception as e:
                    logger.warning(f"Failed to backfill group {chat_id}: {e}")
            
            logger.info(f"Successfully backfilled {registered_count}/{len(active_chats)} groups to database")
        except Exception as e:
            logger.error(f"Error in backfill_groups_startup: {e}")

    async def check_admin_status(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if bot is admin in the chat"""
        try:
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            return bot_member.status in ['administrator', 'creator']
        except Exception as e:
            # Handle gracefully when bot is kicked - this is expected behavior
            if "Forbidden" in str(e) or "kicked" in str(e).lower():
                logger.info(f"Bot no longer has access to chat {chat_id} (kicked or removed)")
                # Remove from active chats
                self.quiz_manager.remove_active_chat(chat_id)
            else:
                logger.error(f"Error checking admin status for chat {chat_id}: {e}")
            return False

    async def send_admin_reminder(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a professional reminder to make bot admin"""
        try:
            # First check if this is a group chat
            chat = await context.bot.get_chat(chat_id)
            if chat.type not in ["group", "supergroup"]:
                return  # Don't send reminder in private chats

            # Then check if bot is already admin
            is_admin = await self.check_admin_status(chat_id, context)
            if is_admin:
                return  # Don't send reminder if bot is already admin

            bot_name = context.bot.first_name or "Bot"
            reminder_message = f"""🔔 𝗔𝗱𝗺𝗶𝗻 𝗔𝗰𝗰𝗲𝘀𝘀 𝗡𝗲𝗲𝗱𝗲𝗱

✨ 𝗧𝗼 𝗨𝗻𝗹𝗼𝗰𝗸 𝗔𝗹𝗹 𝗙𝗲𝗮𝘁𝘂𝗿𝗲𝘀:
1️⃣ Open Group Settings
2️⃣ Select Administrators
3️⃣ Add "{bot_name}" as Admin

🎯 𝗬𝗼𝘂'𝗹𝗹 𝗚𝗲𝘁:
• Automatic Quiz Sessions 🤖
• Group Statistics & Analytics 📊
• Enhanced Group Features 🌟
• Smooth Quiz Experience ⚡

🎉 Let's make this group amazing together!"""

            keyboard = [[InlineKeyboardButton(
                "✨ Make Admin Now ✨",
                url=f"https://t.me/{chat.username}/administrators"
            )]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=chat_id,
                text=reminder_message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Sent enhanced admin reminder to group {chat_id}")

        except Exception as e:
            # Handle gracefully when bot is kicked
            if "Forbidden" in str(e) or "kicked" in str(e).lower():
                logger.info(f"Cannot send admin reminder to chat {chat_id} (bot removed or kicked)")
                self.quiz_manager.remove_active_chat(chat_id)
            else:
                logger.error(f"Failed to send admin reminder to chat {chat_id}: {e}")

    async def send_quiz(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, auto_sent: bool = False, scheduled: bool = False, category: str | None = None, chat_type: str | None = None) -> None:
        """Send a quiz to a specific chat using native Telegram quiz format"""
        try:
            # Get chat type to determine if deletion should be attempted
            # Only call get_chat() if chat_type is not provided (performance optimization)
            if chat_type is None:
                chat_type = 'private' if chat_id > 0 else 'group'
                try:
                    chat = await context.bot.get_chat(chat_id)
                    chat_type = chat.type
                except Exception:
                    pass
            
            # Delete last quiz message if it exists (using database tracking)
            # Skip deletion for private chats to avoid unnecessary API calls
            last_quiz_msg_id = self.db.get_last_quiz_message(chat_id)
            if last_quiz_msg_id and chat_type != 'private':
                try:
                    await context.bot.delete_message(chat_id, last_quiz_msg_id)
                    logger.info(f"Deleted old quiz message {last_quiz_msg_id} in chat {chat_id}")
                    
                    # Log auto-delete activity
                    self._queue_activity_log(
                        activity_type='quiz_deleted',
                        chat_id=chat_id,
                        details={
                            'auto_delete': True,
                            'old_message_id': last_quiz_msg_id
                        },
                        success=True
                    )
                except Exception as e:
                    # Catch and ignore "Message to delete not found" errors
                    if "message to delete not found" in str(e).lower() or "message can't be deleted" in str(e).lower():
                        logger.debug(f"Old quiz message not found or can't be deleted: {e}")
                    else:
                        logger.debug(f"Could not delete old quiz message: {e}")

            # Get a random question for this specific chat (with optional category filter)
            if category:
                logger.info(f"Requesting quiz from category '{category}' for chat {chat_id}")
            question = self.quiz_manager.get_random_question(chat_id, category=category)
            if not question:
                if category:
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=f"❌ No questions available in the '{category}' category.\n\n"
                             f"Please try another category or contact the administrator."
                    )
                    logger.warning(f"No questions available for category '{category}' in chat {chat_id}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text="No questions available.")
                    logger.warning(f"No questions available for chat {chat_id}")
                return

            # Ensure question text is clean
            question_text = question['question'].strip()
            if question_text.startswith('/addquiz'):
                question_text = question_text[len('/addquiz'):].strip()
                logger.info(f"Cleaned /addquiz prefix from question for chat {chat_id}")

            logger.info(f"Sending quiz to chat {chat_id}. Question: {question_text[:50]}...")

            # Get question ID for persistence (hidden from users with zero-width space)
            question_id = question.get('id')
            # Use zero-width space to hide ID from users: ​[ID: 123]​
            explanation_text = f"​[ID: {question_id}]​" if question_id else ""

            # Send the poll
            message = await context.bot.send_poll(
                chat_id=chat_id,
                question=question_text,
                options=question['options'],
                type=Poll.QUIZ,
                correct_option_id=question['correct_answer'],
                is_anonymous=False,
                explanation=explanation_text
            )

            if message and message.poll:
                
                poll_data = {
                    'chat_id': chat_id,
                    'correct_option_id': question['correct_answer'],
                    'user_answers': {},
                    'poll_id': message.poll.id,
                    'question': question_text,
                    'question_id': question_id,
                    'timestamp': datetime.now().isoformat()
                }
                # Store using proper poll ID key
                context.bot_data[f"poll_{message.poll.id}"] = poll_data
                logger.info(f"Stored quiz data: poll_id={message.poll.id}, chat_id={chat_id}")
                
                # Store new quiz message ID and increment quiz count
                # For private chats, use 0 instead of None (database expects int)
                if chat_type == 'private':
                    self.db.update_last_quiz_message(chat_id, 0)
                else:
                    self.db.update_last_quiz_message(chat_id, message.message_id)
                self.db.increment_quiz_count()
                
                self.command_history[chat_id].append(f"/quiz_{message.message_id}")
                
                # Get chat title for logging (reuse chat_type from parameter, no need to call get_chat again)
                chat_title = None
                if chat_type in ['group', 'supergroup']:
                    try:
                        chat = await context.bot.get_chat(chat_id)
                        chat_title = chat.title
                    except Exception:
                        pass
                
                # Log comprehensive quiz_sent activity
                self._queue_activity_log(
                    activity_type='quiz_sent',
                    user_id=None,  # No specific user for quiz sending
                    chat_id=chat_id,
                    chat_title=chat_title,
                    details={
                        'question_id': question_id,
                        'question_text': question_text[:100],
                        'chat_type': chat_type,
                        'auto_sent': auto_sent,
                        'scheduled': scheduled,
                        'category': category,
                        'poll_id': message.poll.id,
                        'message_id': message.message_id
                    },
                    success=True
                )
                if category:
                    logger.info(f"Sent quiz from category '{category}' to chat {chat_id}")
                logger.info(f"Logged quiz_sent activity for chat {chat_id} (auto_sent={auto_sent}, scheduled={scheduled})")

        except Exception as e:
            logger.error(f"Error sending quiz: {str(e)}\n{traceback.format_exc()}")
            await context.bot.send_message(chat_id=chat_id, text="Error sending quiz.")

    async def scheduled_cleanup(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Automatically clean old messages every hour"""
        try:
            # Note: Message cleanup is handled automatically via auto-delete mechanisms
            # This job is kept for future cleanup extensions if needed
            logger.debug("Message cleanup handled by auto-delete mechanisms")

        except Exception as e:
            logger.error(f"Error in scheduled cleanup: {e}")
    
    async def track_memory_usage(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Track memory usage every 5 minutes for performance monitoring"""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            self.db.log_performance_metric(
                metric_type='memory_usage',
                value=memory_mb,
                unit='MB',
                details={'pid': process.pid}
            )
            
            logger.debug(f"Memory usage tracked: {memory_mb:.2f} MB")
        except Exception as e:
            logger.debug(f"Error tracking memory usage (non-critical): {e}")
    
    async def cleanup_performance_metrics(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up performance metrics older than 7 days"""
        try:
            deleted_count = self.db.cleanup_old_performance_metrics(days=7)
            logger.info(f"Cleaned up {deleted_count} old performance metrics")
        except Exception as e:
            logger.error(f"Error cleaning up performance metrics: {e}")
    
    async def cleanup_old_activities(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up old activity logs (keep 30 days)"""
        try:
            deleted = self.db.cleanup_old_activities(days=30)
            logger.info(f"Cleaned up {deleted} old activity logs")
        except Exception as e:
            logger.error(f"Error cleaning up old activities: {e}")
    
    async def refresh_rank_cache(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Auto-refresh rank cache every 5 minutes to prevent desyncs and rehydrate eagerly"""
        try:
            # Invalidate and immediately rehydrate cache to prevent cold hits
            async with self._cache_lock:
                self._leaderboard_cache = None
                self._leaderboard_cache_time = None
            
            # Eagerly rehydrate cache so next user gets warm cache
            await self._get_leaderboard_cached(limit=1000, offset=0)
            logger.debug("Auto-refreshed and rehydrated leaderboard cache (5-min safety cycle)")
        except Exception as e:
            logger.error(f"Error refreshing rank cache: {e}")
    
    async def cleanup_rate_limits(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clean up old rate limit entries"""
        try:
            cleaned_count = self.rate_limiter.cleanup_old_entries()
            if cleaned_count > 0:
                logger.info(f"Rate limit cleanup: removed {cleaned_count} old entries")
        except Exception as e:
            logger.error(f"Error cleaning up rate limits: {e}")
    
    def track_api_call(self, api_name: str):
        """Track Telegram API call for performance monitoring"""
        try:
            self.db.log_performance_metric(
                metric_type='api_call',
                metric_name=api_name,
                value=1,
                unit='count'
            )
        except Exception as e:
            logger.debug(f"Error tracking API call (non-critical): {e}")
    
    def track_error(self, error_type: str):
        """Track error for performance monitoring"""
        try:
            self.db.log_performance_metric(
                metric_type='error',
                metric_name=error_type,
                value=1,
                unit='count'
            )
        except Exception as e:
            logger.debug(f"Error tracking error metric (non-critical): {e}")

    def _register_callback_handlers(self):
        """Register all callback query handlers"""
        if not self.application:
            return
        # Register callback for stats dashboard
        self.application.add_handler(CallbackQueryHandler(
            self.handle_stats_callback,
            pattern="^(refresh_stats|stats_)"
        ))
        
        logger.info("Registered all callback handlers")
            
    async def _post_init_setup(self, application: Application) -> None:
        """Post-initialization setup: preload caches and backfill data"""
        try:
            # OPTIMIZATION 3: Pre-load leaderboard cache on startup
            await self._preload_leaderboard()
            
            # Backfill groups from active_chats to database
            await self.backfill_groups_startup()
            
            logger.info("Post-init setup completed successfully")
        except Exception as e:
            logger.error(f"Error in post-init setup: {e}")
    
    async def conflict_error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle Conflict errors during polling by re-raising to trigger outer retry loop"""
        if isinstance(context.error, Conflict):
            logger.error(f"⚠️ Conflict detected: {context.error}")
            logger.info("🔄 Stopping updater and re-raising Conflict for retry with webhook cleanup...")
            
            # Track the error
            self.track_error('conflict')
            
            # Stop updater to cleanly exit from polling before re-raising
            try:
                if context.application.updater and context.application.updater.running:
                    await context.application.updater.stop()
                    logger.info("✅ Updater stopped")
            except Exception as e:
                logger.error(f"Error stopping updater: {e}")
            
            # Re-raise the Conflict exception so outer retry loop can catch it
            raise context.error
        
        # Log other errors normally
        logger.error(f"Error: {context.error}", exc_info=context.error)
    
    async def initialize(self, token: str):
        """Initialize bot with handlers and job queues (ready for run_polling)"""
        try:
            # Build application with network resilience settings
            from telegram.request import HTTPXRequest
            
            # Configure robust HTTP client with proper timeouts and retry logic
            request = HTTPXRequest(
                connect_timeout=10.0,
                read_timeout=20.0, 
                write_timeout=20.0,
                pool_timeout=10.0,
                connection_pool_size=8
            )
            
            # Configure persistence to save poll data across restarts
            persistence = PicklePersistence(filepath='data/bot_persistence')
            
            self.application = (
                Application.builder()
                .token(token)
                .request(request)
                .persistence(persistence)
                .post_init(self._post_init_setup)
                .build()
            )

            # Add handlers for all commands
            self.application.add_handler(CommandHandler("start", self.start))
            self.application.add_handler(CommandHandler("ping", self.ping))
            self.application.add_handler(CommandHandler("help", self.help))
            self.application.add_handler(CommandHandler("quiz", self.quiz_command))
            self.application.add_handler(CommandHandler("category", self.category))
            self.application.add_handler(CommandHandler("mystats", self.mystats))
            self.application.add_handler(CommandHandler("leaderboard", self.leaderboard_command))
            self.application.add_handler(CommandHandler("ranks", self.leaderboard_command))

            # Developer commands (legacy - keeping existing)
            self.application.add_handler(CommandHandler("addquiz", self.addquiz))
            self.application.add_handler(CommandHandler("totalquiz", self.totalquiz))
            
            # Enhanced developer commands (from dev_commands module)
            self.application.add_handler(CommandHandler("editquiz", self.dev_commands.editquiz))
            self.application.add_handler(CommandHandler("delquiz", self.dev_commands.delquiz))
            self.application.add_handler(CommandHandler("delquiz_confirm", self.dev_commands.delquiz_confirm))
            self.application.add_handler(CommandHandler("dev", self.dev_commands.dev))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("broadcast", self.dev_commands.broadcast))
            self.application.add_handler(CommandHandler("broadcast_confirm", self.dev_commands.broadcast_confirm))
            self.application.add_handler(CommandHandler("delbroadcast", self.dev_commands.delbroadcast))
            self.application.add_handler(CommandHandler("delbroadcast_confirm", self.dev_commands.delbroadcast_confirm))

            # Handle answers and chat member updates
            self.application.add_handler(PollAnswerHandler(self.handle_answer))
            self.application.add_handler(ChatMemberHandler(self.track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
            
            # Track ALL PM interactions (any message in private chat)
            from telegram.ext import MessageHandler, filters
            
            # Handle text input for quiz editing (must come before PM tracking)
            self.application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.dev_commands.handle_text_input)
            )
            
            self.application.add_handler(
                MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, self.track_pm_interaction)
            )

            # Add callback query handler for stats dashboard UI
            self.application.add_handler(CallbackQueryHandler(
                self.handle_stats_callback,
                pattern="^(refresh_stats|stats_)"
            ))
            
            # Add callback query handler for start command buttons
            self.application.add_handler(CallbackQueryHandler(
                self.handle_start_callback,
                pattern="^(start_quiz|my_stats|help)$"
            ))
            
            # Add quiz action callback handler
            self.application.add_handler(CallbackQueryHandler(
                self.handle_quiz_action_callback,
                pattern="^(quiz_play_again|quiz_my_stats|quiz_leaderboard|quiz_categories)$"
            ))
            
            # Add leaderboard pagination callback handler
            self.application.add_handler(CallbackQueryHandler(
                self.handle_leaderboard_callback,
                pattern="^leaderboard_page_"
            ))
            
            # Add edit quiz callback handler
            self.application.add_handler(CallbackQueryHandler(
                self.dev_commands.handle_edit_quiz_callback,
                pattern="^edit_quiz_"
            ))
            
            if not self.application or not self.application.job_queue:
                logger.error("Application or job queue not initialized")
                raise RuntimeError("Application or job queue not initialized")

            # Schedule automated quiz job - every 30 minutes
            self.application.job_queue.run_repeating(
                self.send_automated_quiz,
                interval=1800,  # 30 minutes
                first=10  # Start first quiz after 10 seconds
            )

            # Schedule cleanup jobs
            self.application.job_queue.run_repeating(
                self.scheduled_cleanup,
                interval=3600,  # Every hour
                first=300  # Start first cleanup after 5 minutes
            )
            self.application.job_queue.run_repeating(
                self.cleanup_old_polls,
                interval=3600, #Every Hour
                first=300
            )
            # Add question history cleanup job
            async def cleanup_questions_wrapper(context):
                """Async wrapper for cleanup_old_questions"""
                self.quiz_manager.cleanup_old_questions()
                
            self.application.job_queue.run_repeating(
                cleanup_questions_wrapper,
                interval=86400,  # Every 24 hours
                first=600  # Start after 10 minutes
            )
            
            # Add memory usage tracking job
            self.application.job_queue.run_repeating(
                self.track_memory_usage,
                interval=300,  # Every 5 minutes
                first=60  # Start after 1 minute
            )
            
            # Add rank cache auto-refresh job (every 5 minutes for real-time sync)
            self.application.job_queue.run_repeating(
                self.refresh_rank_cache,
                interval=300,  # Every 5 minutes
                first=120  # Start after 2 minutes
            )
            
            # Add performance metrics cleanup job
            self.application.job_queue.run_repeating(
                self.cleanup_performance_metrics,
                interval=86400,  # Every 24 hours
                first=3600  # Start after 1 hour
            )
            
            # Add rate limit cleanup job
            self.application.job_queue.run_repeating(
                self.cleanup_rate_limits,
                interval=900,  # Every 15 minutes
                first=900  # Start after 15 minutes
            )
            
            # Add activity logs cleanup job (run at 3 AM daily)
            self.application.job_queue.run_daily(
                self.cleanup_old_activities,
                time=__import__('datetime').time(hour=3, minute=0),
                name='cleanup_old_activities'
            )

            # Register error handler for Conflict errors and other exceptions
            self.application.add_error_handler(self.conflict_error_handler)
            logger.info("✅ Conflict error handler registered")

            logger.info("Bot configured and ready for run_polling() (post_init will run setup)")
            return self

        except Exception as e:
            logger.error(f"Failed to configure bot: {e}")
            raise

    async def initialize_webhook(self, token: str, webhook_url: str):
        """Initialize the bot in webhook mode with robust network configuration"""
        try:
            # Build application with network resilience settings
            from telegram.request import HTTPXRequest
            
            # Configure robust HTTP client with proper timeouts and retry logic
            request = HTTPXRequest(
                connect_timeout=10.0,
                read_timeout=20.0, 
                write_timeout=20.0,
                pool_timeout=10.0,
                connection_pool_size=8
            )
            
            # Configure persistence to save poll data across restarts
            persistence = PicklePersistence(filepath='data/bot_persistence')
            
            self.application = (
                Application.builder()
                .token(token)
                .updater(None)  # Disable polling/updater for webhook mode
                .request(request)
                .persistence(persistence)
                .build()
            )

            # Add handlers for all commands
            self.application.add_handler(CommandHandler("start", self.start))
            self.application.add_handler(CommandHandler("ping", self.ping))
            self.application.add_handler(CommandHandler("help", self.help))
            self.application.add_handler(CommandHandler("quiz", self.quiz_command))
            self.application.add_handler(CommandHandler("category", self.category))
            self.application.add_handler(CommandHandler("mystats", self.mystats))
            self.application.add_handler(CommandHandler("leaderboard", self.leaderboard_command))
            self.application.add_handler(CommandHandler("ranks", self.leaderboard_command))

            # Developer commands (legacy - keeping existing)
            self.application.add_handler(CommandHandler("addquiz", self.addquiz))
            self.application.add_handler(CommandHandler("totalquiz", self.totalquiz))
            
            # Enhanced developer commands (from dev_commands module)
            self.application.add_handler(CommandHandler("editquiz", self.dev_commands.editquiz))
            self.application.add_handler(CommandHandler("delquiz", self.dev_commands.delquiz))
            self.application.add_handler(CommandHandler("delquiz_confirm", self.dev_commands.delquiz_confirm))
            self.application.add_handler(CommandHandler("dev", self.dev_commands.dev))
            self.application.add_handler(CommandHandler("stats", self.stats_command))
            self.application.add_handler(CommandHandler("broadcast", self.dev_commands.broadcast))
            self.application.add_handler(CommandHandler("broadcast_confirm", self.dev_commands.broadcast_confirm))
            self.application.add_handler(CommandHandler("delbroadcast", self.dev_commands.delbroadcast))
            self.application.add_handler(CommandHandler("delbroadcast_confirm", self.dev_commands.delbroadcast_confirm))

            # Handle answers and chat member updates
            self.application.add_handler(PollAnswerHandler(self.handle_answer))
            self.application.add_handler(ChatMemberHandler(self.track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
            
            # Track ALL PM interactions (any message in private chat)
            from telegram.ext import MessageHandler, filters
            
            # Handle text input for quiz editing (must come before PM tracking)
            self.application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.dev_commands.handle_text_input)
            )
            
            self.application.add_handler(
                MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, self.track_pm_interaction)
            )

            # Add callback query handler for stats dashboard UI
            self.application.add_handler(CallbackQueryHandler(
                self.handle_stats_callback,
                pattern="^(refresh_stats|stats_)"
            ))
            
            # Add callback query handler for start command buttons
            self.application.add_handler(CallbackQueryHandler(
                self.handle_start_callback,
                pattern="^(start_quiz|my_stats|help)$"
            ))
            
            # Add quiz action callback handler
            self.application.add_handler(CallbackQueryHandler(
                self.handle_quiz_action_callback,
                pattern="^(quiz_play_again|quiz_my_stats|quiz_leaderboard|quiz_categories)$"
            ))
            
            # Add leaderboard pagination callback handler
            self.application.add_handler(CallbackQueryHandler(
                self.handle_leaderboard_callback,
                pattern="^leaderboard_page_"
            ))

            if not self.application or not self.application.job_queue:
                logger.error("Application or job queue not initialized for webhook mode")
                raise RuntimeError("Application or job queue not initialized for webhook mode")

            # Schedule automated quiz job - every 30 minutes
            self.application.job_queue.run_repeating(
                self.send_automated_quiz,
                interval=1800,  # 30 minutes
                first=10  # Start first quiz after 10 seconds
            )

            # Schedule cleanup jobs
            self.application.job_queue.run_repeating(
                self.scheduled_cleanup,
                interval=3600,  # Every hour
                first=300  # Start first cleanup after 5 minutes
            )
            self.application.job_queue.run_repeating(
                self.cleanup_old_polls,
                interval=3600, #Every Hour
                first=300
            )
            # Add question history cleanup job
            async def cleanup_questions_wrapper(context):
                """Async wrapper for cleanup_old_questions"""
                self.quiz_manager.cleanup_old_questions()
                
            self.application.job_queue.run_repeating(
                cleanup_questions_wrapper,
                interval=86400,  # Every 24 hours
                first=600  # Start after 10 minutes
            )
            
            # Add memory usage tracking job
            self.application.job_queue.run_repeating(
                self.track_memory_usage,
                interval=300,  # Every 5 minutes
                first=60  # Start after 1 minute
            )
            
            # Add rank cache auto-refresh job (every 5 minutes for real-time sync)
            self.application.job_queue.run_repeating(
                self.refresh_rank_cache,
                interval=300,  # Every 5 minutes
                first=120  # Start after 2 minutes
            )
            
            # Add performance metrics cleanup job
            self.application.job_queue.run_repeating(
                self.cleanup_performance_metrics,
                interval=86400,  # Every 24 hours
                first=3600  # Start after 1 hour
            )
            
            # Add rate limit cleanup job
            self.application.job_queue.run_repeating(
                self.cleanup_rate_limits,
                interval=900,  # Every 15 minutes
                first=900  # Start after 15 minutes
            )
            
            # Add activity logs cleanup job (run at 3 AM daily)
            self.application.job_queue.run_daily(
                self.cleanup_old_activities,
                time=__import__('datetime').time(hour=3, minute=0),
                name='cleanup_old_activities'
            )

            # Initialize but DON'T start the application
            # (starting creates event loop that conflicts with Flask sync context)
            await self.application.initialize()
            
            # Manually start job queue for scheduled tasks
            if self.application.job_queue:
                await self.application.job_queue.start()
            
            # Backfill groups from active_chats to database
            await self.backfill_groups_startup()
            
            # Set webhook instead of polling
            await self.application.bot.set_webhook(
                url=webhook_url,
                allowed_updates=Update.ALL_TYPES
            )
            
            logger.info(f"Webhook set successfully: {webhook_url}")
            
            return self

        except Exception as e:
            logger.error(f"Failed to initialize bot in webhook mode: {e}")
            raise

    def extract_status_change(self, chat_member_update):
        """Extract whether bot was added or removed from chat"""
        try:
            if not chat_member_update or not hasattr(chat_member_update, 'difference'):
                return None

            status_change = chat_member_update.difference().get("status")
            if status_change is None:
                return None

            old_status = chat_member_update.old_chat_member.status
            new_status = chat_member_update.new_chat_member.status

            was_member = old_status in ["member", "administrator", "creator"]
            is_member = new_status in ["member", "administrator", "creator"]

            return was_member, is_member
        except Exception as e:
            logger.error(f"Error in extract_status_change: {e}")
            return None

    async def track_chats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Enhanced tracking when bot is added to or removed from chats"""
        try:
            chat = update.effective_chat
            if not chat:
                return

            result = self.extract_status_change(update.my_chat_member)
            if result is None:
                return

            was_member, is_member = result

            if chat.type in ["group", "supergroup"]:
                if not was_member and is_member:
                    # Bot was added to a group
                    self.quiz_manager.add_active_chat(chat.id)
                    await self.ensure_group_registered(chat, context)
                    await self.send_welcome_message(chat.id, context)

                    # Auto-send quiz after 5 seconds when added to group
                    await asyncio.sleep(5)
                    
                    last_quiz_msg_id = self.db.get_last_quiz_message(chat.id)
                    if last_quiz_msg_id:
                        try:
                            await context.bot.delete_message(chat.id, last_quiz_msg_id)
                            logger.info(f"Deleted old quiz message {last_quiz_msg_id} in group {chat.id}")
                        except Exception as e:
                            logger.debug(f"Could not delete old quiz message: {e}")
                    
                    question = self.quiz_manager.get_random_question(chat.id)
                    if question:
                        question_text = question['question'].strip()
                        if question_text.startswith('/addquiz'):
                            question_text = question_text[len('/addquiz'):].strip()
                        
                        # Get question ID for persistence (hidden from users with zero-width space)
                        question_id = question.get('id')
                        # Use zero-width space to hide ID from users: ​[ID: 123]​
                        explanation_text = f"​[ID: {question_id}]​" if question_id else ""
                        
                        message = await context.bot.send_poll(
                            chat_id=chat.id,
                            question=question_text,
                            options=question['options'],
                            type=Poll.QUIZ,
                            correct_option_id=question['correct_answer'],
                            is_anonymous=False,
                            explanation=explanation_text
                        )
                        
                        if message and message.poll:
                            poll_data = {
                                'chat_id': chat.id,
                                'correct_option_id': question['correct_answer'],
                                'user_answers': {},
                                'poll_id': message.poll.id,
                                'question': question_text,
                                'question_id': question_id,
                                'timestamp': datetime.now().isoformat()
                            }
                            context.bot_data[f"poll_{message.poll.id}"] = poll_data
                            
                            self.db.update_last_quiz_message(chat.id, message.message_id)
                            self.db.increment_quiz_count()
                            
                            logger.info(f"Auto-sent quiz to group {chat.id} after bot added")

                    logger.info(f"Bot added to group {chat.title} ({chat.id})")

                elif was_member and not is_member:
                    # Bot was removed from a group
                    self.quiz_manager.remove_active_chat(chat.id)
                    logger.info(f"Bot removed from group {chat.title} ({chat.id})")

        except Exception as e:
            logger.error(f"Error in track_chats: {e}")

    async def _delete_messages_after_delay(self, chat_id: int, message_ids: List[int], delay: int = 5) -> None:
        """Delete messages after specified delay in seconds - requires admin permissions in groups"""
        try:
            if not self.application:
                logger.error("Application not initialized in _delete_messages_after_delay")
                return
            
            await asyncio.sleep(delay)
            
            # Check if bot has admin permissions to delete messages
            try:
                bot_member = await self.application.bot.get_chat_member(chat_id, self.application.bot.id)
                is_admin = bot_member.status in ['administrator', 'creator']
                
                if not is_admin:
                    logger.info(f"Bot is not admin in chat {chat_id}, skipping auto-delete (need 'Delete messages' permission)")
                    return
            except Exception as e:
                logger.debug(f"Could not check admin status for auto-delete in chat {chat_id}: {e}")
                return
            
            # Attempt to delete messages
            deleted_count = 0
            for message_id in message_ids:
                try:
                    await self.application.bot.delete_message(
                        chat_id=chat_id,
                        message_id=message_id
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.debug(f"Could not delete message {message_id} in chat {chat_id}: {e}")
                    continue
            
            if deleted_count > 0:
                logger.info(f"Auto-cleaned {deleted_count} messages in chat {chat_id}")
        except Exception as e:
            logger.error(f"Error in _delete_messages_after_delay: {e}")

    async def send_welcome_message(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, user=None):
        """Send unified welcome message when bot joins a group or starts in private chat
        
        Returns:
            Message: The sent message object, or None if an error occurred
        """
        try:
            keyboard = [
                [InlineKeyboardButton(
                    "➕ Add to Your Group",
                    url=f"https://t.me/{context.bot.username}?startgroup=true"
                )]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Create bot link and personalized greeting with clickable user name
            bot_link = f"[Miss Quiz 𓂀 Bot](https://t.me/{context.bot.username})"
            user_greeting = ""
            if user:
                user_name_link = f"[{user.first_name}](tg://user?id={user.id})"
                user_greeting = f"Hello {user_name_link}! 👋\n\n"

            welcome_message = f"""╔════════════════════════════════╗
║ 🎯 𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 {bot_link} 🇮🇳 ║
╚════════════════════════════════╝

{user_greeting}📌 𝐅𝐞𝐚𝐭𝐮𝐫𝐞𝐬 𝐘𝐨𝐮'𝐥𝐥 𝐋𝐨𝐯𝐞:
➤ 🕒 Auto Quizzes – Fresh quizzes every 30 mins
➤ 📊 Group Stats – Track performance & compete
➤ 📚 Categories – GK, CA, History & more! /category
➤ ⚡ Instant Results – Answers in real-time
➤ 🤫 PM Mode – Clean, clutter-free experience
➤ 🧹 Group Mode – Auto-deletes quiz messages for cleaner chat

──────────────────────────────
📝 𝐂𝐨𝐦𝐦𝐚𝐧𝐝𝐬:
/start — Begin your quiz journey 🚀
/help — View all commands 🛠️
/category — Explore quiz topics 📖
/mystats — Check your performance 📊

──────────────────────────────
🔥 Add me to your groups & let the quiz fun begin! 🎯"""

            sent_message = await context.bot.send_message(
                chat_id=chat_id,
                text=welcome_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

            # Get chat type and handle accordingly
            chat = await context.bot.get_chat(chat_id)
            if chat.type in ["group", "supergroup"]:
                is_admin = await self.check_admin_status(chat_id, context)
                if is_admin:
                    await self.send_quiz(chat_id, context, auto_sent=True, scheduled=False, chat_type=chat.type)
                else:
                    await self.send_admin_reminder(chat_id, context)

            logger.info(f"Sent premium welcome message to chat {chat_id}")
            return sent_message
        except Exception as e:
            logger.error(f"Error sending welcome message: {e}")
            return None

    async def handle_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle quiz answers"""
        try:
            answer = update.poll_answer
            if not answer or not answer.poll_id or not answer.user:
                logger.warning("Received invalid poll answer")
                return

            logger.info(f"Received answer from user {answer.user.id} for poll {answer.poll_id}")

            # Get quiz data from context using proper key
            poll_data = context.bot_data.get(f"poll_{answer.poll_id}")
            if not poll_data:
                logger.warning(f"No poll data found for poll_id {answer.poll_id}")
                return

            # IDEMPOTENCY PROTECTION: Check if this user already answered this poll
            user_answer_key = f'answered_by_user_{answer.user.id}'
            if poll_data.get(user_answer_key):
                logger.warning(f"Poll {answer.poll_id} already answered by user {answer.user.id}, skipping duplicate")
                return
            
            # Mark as processed to prevent duplicate recording
            poll_data[user_answer_key] = True

            # Check if this is a correct answer
            is_correct = poll_data['correct_option_id'] in answer.option_ids
            chat_id = poll_data['chat_id']
            question_id = poll_data.get('question_id')
            selected_answer = answer.option_ids[0] if answer.option_ids else None
            
            # Get user info for logging
            username = answer.user.username if answer.user.username else None
            
            # Update user information in database with current username
            self.db.add_or_update_user(
                user_id=answer.user.id,
                username=answer.user.username,
                first_name=answer.user.first_name,
                last_name=answer.user.last_name
            )
            
            # Calculate response time if timestamp is available
            response_time_ms = None
            if 'timestamp' in poll_data:
                try:
                    quiz_sent_time = datetime.fromisoformat(poll_data['timestamp'])
                    response_time_ms = int((datetime.now() - quiz_sent_time).total_seconds() * 1000)
                except Exception as e:
                    logger.debug(f"Could not calculate response time: {e}")
            
            # Log comprehensive quiz answer activity
            self._queue_activity_log(
                activity_type='quiz_answered',
                user_id=answer.user.id,
                chat_id=chat_id,
                username=username,
                details={
                    'poll_id': answer.poll_id,
                    'question_id': question_id,
                    'correct': is_correct,
                    'selected_answer': selected_answer,
                    'correct_answer': poll_data['correct_option_id'],
                    'question_text': poll_data.get('question', '')[:100]
                },
                success=True,
                response_time_ms=response_time_ms
            )

            # Record the answer in poll_data
            poll_data['user_answers'][answer.user.id] = {
                'option_ids': answer.option_ids,
                'is_correct': is_correct,
                'timestamp': datetime.now().isoformat()
            }

            # Update stats IMMEDIATELY in database (async-safe to avoid blocking event loop)
            activity_date = datetime.now().strftime('%Y-%m-%d')
            await asyncio.to_thread(self.db.update_user_score, answer.user.id, is_correct, activity_date)
            logger.info(f"Updated stats in database for user {answer.user.id}: correct={is_correct}")
            
            # CRITICAL: Invalidate all caches immediately for real-time updates (thread-safe)
            async with self._cache_lock:
                self._stats_cache = None
                self._stats_cache_time = None
                self._leaderboard_cache = None
                self._leaderboard_cache_time = None
            logger.debug(f"Invalidated stats and leaderboard caches for real-time rank update")
            
            # Also record in quiz_history for tracking purposes
            if question_id and selected_answer is not None:
                self.db.record_quiz_answer(
                    user_id=answer.user.id,
                    chat_id=chat_id,
                    question_id=question_id,
                    question_text=poll_data.get('question', ''),
                    user_answer=selected_answer,
                    correct_answer=poll_data['correct_option_id']
                )
            
            # Keep quiz_manager in sync for compatibility (but DB is source of truth)
            if is_correct:
                self.quiz_manager.increment_score(answer.user.id)
            self.quiz_manager.record_group_attempt(
                user_id=answer.user.id,
                chat_id=chat_id,
                is_correct=is_correct
            )
            logger.info(f"Recorded quiz attempt for user {answer.user.id} in chat {chat_id} (correct: {is_correct})")
            
            # Send inline keyboard with action buttons after quiz completion (in PM only)
            try:
                chat = await context.bot.get_chat(chat_id)
                if chat.type == 'private':
                    result_emoji = "✅" if is_correct else "❌"
                    result_text = "Correct!" if is_correct else "Wrong!"
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("🎯 Play Again", callback_data="quiz_play_again"),
                            InlineKeyboardButton("📊 My Stats", callback_data="quiz_my_stats")
                        ],
                        [
                            InlineKeyboardButton("🏆 Leaderboard", callback_data="quiz_leaderboard"),
                            InlineKeyboardButton("📚 Categories", callback_data="quiz_categories")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=answer.user.id,
                        text=f"{result_emoji} **{result_text}**\n\nWhat would you like to do next?",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"Sent quiz completion buttons to user {answer.user.id}")
            except Exception as btn_error:
                logger.debug(f"Could not send quiz completion buttons: {btn_error}")

        except Exception as e:
            logger.error(f"Error handling answer: {str(e)}\n{traceback.format_exc()}")

    async def track_pm_interaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Track user interactions in private chats for activity logging"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        username = update.effective_user.username or ""

        try:
            self._add_or_update_user_cached(
                user_id,
                username,
                update.effective_user.first_name,
                update.effective_user.last_name
            )
            
            self._queue_activity_log(
                activity_type='pm_interaction',
                user_id=user_id,
                chat_id=chat_id,
                username=username,
                details={'message_length': len(update.message.text or "")},
                success=True
            )
            logger.debug(f"PM interaction tracked for user {user_id}")

        except Exception as e:
            logger.error(f"Error tracking PM interaction for user {user_id}: {e}")

    async def send_friendly_error_message(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a user-friendly error message with helpful suggestions"""
        error_message = """😅 Oops! Something went a bit wrong.

💡 **Here's what you can try:**
• Try the command again
• Use /help to see all available commands
• Start a quiz with /quiz
• Browse topics with /category

Need more help? We're here for you! 🌟"""
        
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending friendly error message: {e}")

    async def quiz_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /quiz command with loading indicator"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            user = update.effective_user
            chat = update.effective_chat
            
            # Track PM access
            self._track_pm_access(user.id, chat.type)
            
            logger.info(f"📥 /quiz command received from user {user.id} in chat {chat.id}")
            
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'quiz'):
                return
            
            # Log command immediately
            self._queue_activity_log(
                activity_type='command',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                username=update.effective_user.username or "",
                chat_title=getattr(update.effective_chat, 'title', None),
                command='/quiz',
                success=True
            )
            
            await self.ensure_group_registered(update.effective_chat, context)
            
            # No cooldown for /quiz command - users can request quizzes anytime
            loading_message = await update.message.reply_text("🎯 Preparing your quiz...")
            
            try:
                await self.send_quiz(update.effective_chat.id, context, chat_type=chat.type)
                await loading_message.delete()
                
                # Auto-delete command message in groups (keep quiz visible)
                if chat.type != "private":
                    asyncio.create_task(self._delete_messages_after_delay(
                        chat_id=chat.id,
                        message_ids=[update.message.message_id],
                        delay=1
                    ))
                
                response_time = int((time.time() - start_time) * 1000)
                logger.info(f"/quiz completed in {response_time}ms")
                
                self.db.log_performance_metric(
                    metric_type='response_time',
                    metric_name='/quiz',
                    value=response_time,
                    unit='ms'
                )
                
            except Exception as e:
                logger.error(f"Error in quiz command: {e}")
                await loading_message.edit_text("❌ Oops! Something went wrong. Try /quiz again!")
                
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self.track_error('/quiz_error')
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/quiz',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in quiz command: {e}")
            await self.send_friendly_error_message(update.effective_chat.id, context)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command - Track PM and Group live"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            chat = update.effective_chat
            user = update.effective_user
            
            logger.info(f"📥 /start command received from user {user.id} in chat {chat.id} (type: {chat.type})")
            
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'start'):
                return
            
            # OPTIMIZATION 1: Use cached user info update
            self._add_or_update_user_cached(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "Unknown",
                last_name=user.last_name or ""
            )
            
            # OPTIMIZATION 2: Queue activity log for batch write
            self._queue_activity_log(
                activity_type='user_join' if chat.type == 'private' else 'group_join',
                user_id=user.id,
                chat_id=chat.id,
                username=user.username or "",
                chat_title=getattr(chat, 'title', None),
                command='/start',
                details={'chat_type': chat.type},
                success=True
            )
            
            # Universal PM tracking - track all PM interactions
            self._track_pm_access(user.id, chat.type)
            
            # Live tracking: Mark PM access immediately when user starts bot in private chat
            if chat.type == 'private':
                logger.info(f"✅ PM TRACKED: User {user.id} ({user.first_name}) granted PM access")
            else:
                # Track group interaction
                logger.info(f"✅ GROUP TRACKED: Group {chat.id} ({chat.title})")
            
            self.quiz_manager.add_active_chat(chat.id)
            logger.info(f"✅ Chat {chat.id} added to active chats")
            await self.ensure_group_registered(chat, context)
            welcome_msg = await self.send_welcome_message(chat.id, context, user)
            
            # Auto-delete command and reply in groups after 60 seconds
            if chat.type != "private" and welcome_msg:
                asyncio.create_task(self._delete_messages_after_delay(
                    chat_id=chat.id,
                    message_ids=[update.message.message_id, welcome_msg.message_id],
                    delay=60
                ))
            
            # Auto-send quiz after 5 seconds in DM
            if chat.type == 'private':
                await asyncio.sleep(5)
                
                last_quiz_msg_id = self.db.get_last_quiz_message(chat.id)
                if last_quiz_msg_id:
                    try:
                        await context.bot.delete_message(chat.id, last_quiz_msg_id)
                        logger.info(f"Deleted old quiz message {last_quiz_msg_id} in DM {chat.id}")
                    except Exception as e:
                        logger.debug(f"Could not delete old quiz message: {e}")
                
                question = self.quiz_manager.get_random_question(chat.id)
                if question:
                    question_text = question['question'].strip()
                    if question_text.startswith('/addquiz'):
                        question_text = question_text[len('/addquiz'):].strip()
                    
                    # Get question ID for persistence (hidden from users with zero-width space)
                    question_id = question.get('id')
                    # Use zero-width space to hide ID from users: ​[ID: 123]​
                    explanation_text = f"​[ID: {question_id}]​" if question_id else ""
                    
                    message = await context.bot.send_poll(
                        chat_id=chat.id,
                        question=question_text,
                        options=question['options'],
                        type=Poll.QUIZ,
                        correct_option_id=question['correct_answer'],
                        is_anonymous=False,
                        explanation=explanation_text
                    )
                    
                    if message and message.poll:
                        poll_data = {
                            'chat_id': chat.id,
                            'correct_option_id': question['correct_answer'],
                            'user_answers': {},
                            'poll_id': message.poll.id,
                            'question': question_text,
                            'question_id': question_id,
                            'timestamp': datetime.now().isoformat()
                        }
                        context.bot_data[f"poll_{message.poll.id}"] = poll_data
                        
                        self.db.update_last_quiz_message(chat.id, message.message_id)
                        self.db.increment_quiz_count()
                        
                        logger.info(f"Auto-sent quiz to DM {chat.id} after /start")
            
            # Log successful completion with response time
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"/start completed in {response_time}ms for user {user.id}")
            
            self.db.log_performance_metric(
                metric_type='response_time',
                metric_name='/start',
                value=response_time,
                unit='ms'
            )
            
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id if update.effective_user else None,
                chat_id=update.effective_chat.id if update.effective_chat else None,
                command='/start',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text("Error starting the bot. Please try again.")
    
    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        try:
            user = update.effective_user
            if user:
                self.db.set_user_pm_access(user.id, True)
                logger.debug(f"✅ PM INTERACTION: User {user.id} ({user.first_name}) tracked for broadcasts")
        except Exception as e:
            logger.error(f"Error tracking PM interaction: {e}")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            user = update.effective_user
            chat = update.effective_chat
            
            logger.info(f"📥 /help command received from user {user.id} in chat {chat.id}")
            
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'help'):
                return
            
            # Universal PM tracking - track all PM interactions
            self._track_pm_access(user.id, chat.type)
            
            # Log command synchronously (works in both polling and webhook modes)
            self.db.log_activity(
                activity_type='command',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                username=update.effective_user.username or "",
                chat_title=getattr(update.effective_chat, 'title', None),
                command='/help',
                success=True
            )
            
            # Register group asynchronously (non-blocking)
            asyncio.create_task(self.ensure_group_registered(update.effective_chat, context))
            
            # Check if user is developer
            is_dev = await self.is_developer(update.effective_user.id)
            
            # Get user and bot info for personalization
            user = update.effective_user
            user_first = user.first_name or 'User'
            bot_username = context.bot.username or "MissQuiz_Bot"
            
            help_text = f"""╔════════════════════════════════════════╗
║  ✨ 𝐌𝐈𝐒𝐒 𝐐𝐔𝐈𝐙 𓂀 𝐁𝐎𝐓 — 𝐇𝐄𝐋𝐏 𝐂𝐄𝐍𝐓𝐄𝐑  ║
╚════════════════════════════════════════╝

👋 𝐖𝐞𝐥𝐜𝐨𝐦𝐞, {user_first}!  
𝐇𝐞𝐫𝐞'𝐬 𝐲𝐨𝐮𝐫 𝐪𝐮𝐢𝐜𝐤 𝐜𝐨𝐦𝐦𝐚𝐧𝐝 𝐠𝐮𝐢𝐝𝐞 👇
━━━━━━━━━━━━━━━━━━━━━━━━━━━
➤ 𝐔𝐒𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒

/start — 🚀 Begin your quiz journey  
/help — 📖 Show help menu  
/quiz — 🎲 Random quiz  
/category — 📚 Browse categories  
/mystats — 📈 Your stats  
/ranks — 🏆 View leaderboard    
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

            # Add developer commands only for developers
            if is_dev:
                help_text += """
➤ 𝐃𝐄𝐕𝐄𝐋𝐎𝐏𝐄𝐑 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒

/dev — 🔐 Manage developer access  
/stats — 📊 Bot analytics  
/broadcast — 📣 Announce globally  
/addquiz — ➕ Add quiz  
/editquiz — ✏️ Edit quiz  
/delquiz — 🗑️ Delete quiz  
/totalquiz — 🔢 Total quizzes
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

            help_text += f"""
➤ 𝐅𝐄𝐀𝐓𝐔𝐑𝐄𝐒

✨ Auto quizzes in groups  
✨ Live leaderboard & stats  
✨ Clean private mode  
✨ Multi-category quizzes  
━━━━━━━━━━━━━━━━━━━━━━━━━━━
💫 Conquer the Quiz World with  
[✨ 𝐌𝐈𝐒𝐒 𝐐𝐔𝐈𝐙 𓂀 𝐁𝐎𝐓 ✨](https://t.me/{bot_username})"""

            # Send help message with markdown for clickable links
            reply_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=help_text,
                parse_mode=ParseMode.MARKDOWN
            )
            
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"Help message sent to user {update.effective_user.id} in {response_time}ms")
            
            # Log performance metric asynchronously (non-blocking)
            asyncio.create_task(self.db.log_performance_metric_async(
                metric_type='response_time',
                metric_name='/help',
                value=response_time,
                unit='ms'
            ))
            
            # Auto-delete command and reply in groups after 60 seconds
            if update.message.chat.type != "private":
                asyncio.create_task(self._delete_messages_after_delay(
                    chat_id=update.message.chat_id,
                    message_ids=[update.message.message_id, reply_message.message_id],
                    delay=60
                ))

        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            # Log error synchronously (works in both polling and webhook modes)
            self.db.log_activity(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/help',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in help command: {e}")
            await update.message.reply_text("Error showing help. Please try again later.")

    async def category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /category command - Text-only list (no buttons)"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            user = update.effective_user
            chat = update.effective_chat
            
            # Track PM access
            self._track_pm_access(user.id, chat.type)
            
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'category'):
                return
            
            # Log command immediately
            self._queue_activity_log(
                activity_type='command',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                username=update.effective_user.username or "",
                chat_title=getattr(update.effective_chat, 'title', None),
                command='/category',
                success=True
            )
            
            # Text-only category list
            category_text = """━━━━━━━━━━━━━━━━━━━━━━━
📚 𝗤𝗨𝗜𝗭 𝗖𝗔𝗧𝗘𝗚𝗢𝗥𝗜𝗘𝗦
━━━━━━━━━━━━━━━━━━━━━━━

📑 Choose a Category to Begin:

🌍  General Knowledge
📰  Current Affairs
📚  Static GK
🔬  Science & Technology
📜  History
🗺  Geography
💰  Economics
🏛  Political Science
📖  Constitution
⚖️  Constitution & Law
🎭  Arts & Literature
🎮  Sports & Games

──────────────────────────────
🎯 More quizzes coming soon!
🛠 Use /help for commands"""

            reply_message = await update.message.reply_text(
                category_text,
                parse_mode=ParseMode.MARKDOWN
            )
            
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"/category completed in {response_time}ms")
            
            self.db.log_performance_metric(
                metric_type='response_time',
                metric_name='/category',
                value=response_time,
                unit='ms'
            )
            
            # Auto-delete command and reply in groups after 60 seconds
            if update.message.chat.type != "private":
                asyncio.create_task(self._delete_messages_after_delay(
                    chat_id=update.message.chat_id,
                    message_ids=[update.message.message_id, reply_message.message_id],
                    delay=60
                ))
            
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/category',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error showing categories: {e}")
            await update.message.reply_text("Error showing categories.")


    async def mystats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show personal statistics with premium formatted dashboard"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            user = update.effective_user
            chat = update.effective_chat
            
            # Track PM access
            self._track_pm_access(user.id, chat.type)

            # Check rate limit
            if not await self.check_rate_limit(update, context, 'mystats'):
                return

            # Use cached user info update
            self._add_or_update_user_cached(
                user_id=user.id,
                username=user.username or "",
                first_name=user.first_name or "Unknown",
                last_name=user.last_name or ""
            )

            # Queue activity log for batch write
            self._queue_activity_log(
                activity_type='command',
                user_id=user.id,
                chat_id=update.effective_chat.id,
                username=user.username or "",
                chat_title=getattr(update.effective_chat, 'title', None),
                command='/mystats',
                success=True
            )

            # Send loading message
            loading_msg = await update.message.reply_text("📊 Loading your stats...")

            try:
                # Get user stats from database in real-time
                stats = self.db.get_user_quiz_stats_realtime(user.id)
                
                # Handle case where user has no stats
                if not stats or not stats.get('total_quizzes', 0):
                    welcome_text = """👋 Welcome to QuizImpact!

🎯 You haven't taken any quizzes yet.
Let's get started:
• Use /quiz to try your first quiz
• Join a group to compete with others
• Track your progress here

Ready to begin? Try /quiz now! 🚀"""
                    await loading_msg.edit_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
                    return

                # Get user rank efficiently without fetching all users
                user_rank = self.db.get_user_rank(user.id)
                if user_rank == 0:
                    user_rank = 'N/A'
                
                # Get stats data
                total_quizzes = stats.get('total_quizzes', 0)
                correct_answers = stats.get('correct_answers', 0)
                wrong_answers = stats.get('wrong_answers', 0)

                # Premium formatted stats message with Unicode box drawing
                stats_message = f"""╔═════════════════════════╗
║ 📊  𝐁𝐎𝐓 & 𝐔𝐒𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 
╚═════════════════════════╝

👤 𝐔𝐬𝐞𝐫: {user.first_name}
🏆 𝐑𝐚𝐧𝐤: #{user_rank}
🎮 𝐓𝐨𝐭𝐚𝐥 𝐐𝐮𝐢𝐳𝐳𝐞𝐬 𝐀𝐭𝐭𝐞𝐦𝐩𝐭𝐞𝐝: {total_quizzes}

━━━━━━━━━━━━━━━━━━
🎯 𝐏𝐄𝐑𝐅𝐎𝐑𝐌𝐀𝐍𝐂𝐄 𝐒𝐓𝐀𝐓𝐒
━━━━━━━━━━━━━━━━━━
✅ 𝐂𝐨𝐫𝐫𝐞𝐜𝐭 𝐀𝐧𝐬𝐰𝐞𝐫𝐬: {correct_answers}
❌ 𝐖𝐫𝐨𝐧𝐠 𝐀𝐧𝐬𝐰𝐞𝐫𝐬: {wrong_answers}"""

                await loading_msg.edit_text(stats_message)
                response_time = int((time.time() - start_time) * 1000)
                logger.info(f"Showed stats to user {user.id} in {response_time}ms")
                
                self.db.log_performance_metric(
                    metric_type='response_time',
                    metric_name='/mystats',
                    value=response_time,
                    unit='ms'
                )
                
                # Auto-delete command and reply in groups after 30 seconds
                if update.message.chat.type != "private":
                    asyncio.create_task(self._delete_messages_after_delay(
                        chat_id=update.message.chat_id,
                        message_ids=[update.message.message_id, loading_msg.message_id],
                        delay=30
                    ))

            except Exception as e:
                logger.error(f"Error displaying stats: {e}")
                await loading_msg.edit_text("❌ Error displaying stats. Please try again.")

        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id if update.effective_user else None,
                chat_id=update.effective_chat.id,
                command='/mystats',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in mystats: {str(e)}\n{traceback.format_exc()}")
            await update.message.reply_text("❌ Error retrieving stats. Please try again.")
    
    def _build_leaderboard_page(self, leaderboard: list, page: int, total_pages: int) -> tuple:
        """Build clean leaderboard page with top 100 players (10 per page)"""
        USERS_PER_PAGE = 10
        start_idx = page * USERS_PER_PAGE
        end_idx = start_idx + USERS_PER_PAGE
        page_users = leaderboard[start_idx:end_idx]
        
        # Build clean leaderboard text
        leaderboard_text = f"**Top Quiz Players — Page {page + 1}/{total_pages}**\n"
        leaderboard_text += "─────────────────────────────\n"
        
        for idx, player in enumerate(page_users, start=start_idx + 1):
            # Get user info
            first_name = player.get('first_name', '')
            username = player.get('username', '')
            user_id = player.get('user_id')
            total_quizzes = player.get('total_quizzes', 0)
            correct = player.get('correct_answers', 0)
            wrong = total_quizzes - correct
            
            # Create clickable username link
            if user_id:
                display_name = first_name.strip() if first_name and first_name.strip() else username if username else f"User {user_id}"
                user_link = f"[{display_name}](tg://user?id={user_id})"
            else:
                user_link = first_name or username or "Unknown"
            
            # Format: Name on top, stats below
            leaderboard_text += f"{idx}. {user_link}\n"
            leaderboard_text += f"   Total: {total_quizzes} | Correct: {correct} | Wrong: {wrong}\n\n"
        
        leaderboard_text += "─────────────────────────────"
        
        # Build page navigation buttons: Back | Page 1 | Page 2 | ... | Page 10 | Next
        keyboard = []
        
        # Page number buttons (show all 10 pages)
        page_buttons = []
        
        for i in range(total_pages):
            # Current page shows with bullet points, others plain
            if i == page:
                page_buttons.append(InlineKeyboardButton(f"• {i+1} •", callback_data=f"leaderboard_page_{i}"))
            else:
                page_buttons.append(InlineKeyboardButton(f"Page {i+1}", callback_data=f"leaderboard_page_{i}"))
        
        # Split page buttons into rows of 5 for clean layout
        for i in range(0, len(page_buttons), 5):
            keyboard.append(page_buttons[i:i+5])
        
        # Navigation buttons: Back and Next
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("Back", callback_data=f"leaderboard_page_{page-1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next", callback_data=f"leaderboard_page_{page+1}"))
        
        if nav_row:
            keyboard.append(nav_row)
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        return leaderboard_text, reply_markup
    
    async def leaderboard_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show top 100 quiz champions with pagination (10 per page)"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            user = update.effective_user
            chat = update.effective_chat
            
            # Track PM access
            self._track_pm_access(user.id, chat.type)
            
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'leaderboard'):
                return
            
            # Log command
            self._queue_activity_log(
                activity_type='command',
                user_id=user.id,
                chat_id=chat.id,
                username=user.username or "",
                chat_title=getattr(chat, 'title', None),
                command='/leaderboard',
                success=True
            )
            
            # Send loading message
            loading_msg = await update.message.reply_text("🏆 Loading leaderboard...")
            
            # Get top 100 from cached leaderboard
            result = await self._get_leaderboard_cached(limit=100, offset=0)
            if not result:
                await loading_msg.edit_text(
                    "🏆 **Leaderboard**\n\n"
                    "No quiz champions yet! 🎯\n\n"
                    "Be the first to take a quiz and claim the top spot!\n\n"
                    "💡 Use /quiz to get started",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            leaderboard, total_count = result
            
            if not leaderboard:
                await loading_msg.edit_text(
                    "🏆 **Leaderboard**\n\n"
                    "No quiz champions yet! 🎯\n\n"
                    "Be the first to take a quiz and claim the top spot!\n\n"
                    "💡 Use /quiz to get started",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            # Limit to top 100 users for display
            leaderboard = leaderboard[:100]
            
            # Calculate total pages (10 users per page)
            USERS_PER_PAGE = 10
            total_pages = (len(leaderboard) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            # Build page 1
            leaderboard_text, reply_markup = self._build_leaderboard_page(leaderboard, 0, total_pages)
            
            # Send leaderboard
            await loading_msg.edit_text(
                leaderboard_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"Showed leaderboard page 1 to user {user.id} in {response_time}ms")
            
            # Log performance
            self.db.log_performance_metric(
                metric_type='response_time',
                metric_name='/leaderboard',
                value=response_time,
                unit='ms'
            )
            
            # Auto-delete command and reply in groups after 60 seconds
            if chat.type != "private":
                asyncio.create_task(self._delete_messages_after_delay(
                    chat_id=chat.id,
                    message_ids=[update.message.message_id, loading_msg.message_id],
                    delay=60
                ))
        
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id if update.effective_user else None,
                chat_id=update.effective_chat.id,
                command='/leaderboard',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in leaderboard: {str(e)}\n{traceback.format_exc()}")
            await update.message.reply_text(
                "❌ Oops! Couldn't load the leaderboard.\n\n"
                "💡 **Try this:**\n"
                "• Use /help to see other commands\n"
                "• Try /mystats to see your personal stats\n"
                "• Contact support if the issue persists"
            )

    async def _process_quizzes_background(self, message_text: str, allow_duplicates: bool, 
                                           message_to_edit, start_time: float, user_id: int, chat_id: int) -> None:
        """Background task to process quiz additions without blocking the bot"""
        try:
            # Offload ALL expensive work to thread executor to keep event loop responsive
            def heavy_work():
                """All parsing, validation, and DB operations in one blocking function"""
                questions_data = []
                
                # Parse lines and build questions_data
                lines = message_text.split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or not '|' in line:
                        continue

                    parts = line.split("|")
                    if len(parts) != 6:
                        continue

                    try:
                        correct_answer = int(parts[5].strip()) - 1
                        if not (0 <= correct_answer < 4):
                            continue

                        questions_data.append({
                            'question': parts[0].strip(),
                            'options': [p.strip() for p in parts[1:5]],
                            'correct_answer': correct_answer
                        })
                    except (ValueError, IndexError):
                        continue
                
                # If no valid questions after parsing, return error
                if not questions_data:
                    return None, None, 0
                
                # Add questions to database
                stats = self.quiz_manager.add_questions(questions_data, allow_duplicates)
                
                # Get updated quiz stats
                quiz_stats = self.quiz_manager.get_quiz_stats()
                total_quiz_count = quiz_stats['total_quizzes']
                
                return stats, total_quiz_count, len(questions_data)
            
            # Run all heavy work in thread
            stats, total_quiz_count, parsed_count = await asyncio.to_thread(heavy_work)
            
            # Check if parsing failed
            if stats is None:
                await message_to_edit.edit_text(
                    "❌ Please provide questions in the correct format.\n\n"
                    "For single question:\n"
                    "/addquiz question | option1 | option2 | option3 | option4 | correct_number\n\n"
                    "For multiple questions (using the | format):\n"
                    "/addquiz question1 | option1 | option2 | option3 | option4 | correct_number\n"
                    "/addquiz question2 | option1 | option2 | option3 | option4 | correct_number\n\n"
                    "To allow duplicate questions:\n"
                    "/addquiz --allow-duplicates question | options...\n\n"
                    "Add more Quiz /addquiz !"
                )
                return
            
            # Build formatted Quiz Addition Report
            added_count = stats['added']
            duplicate_count = stats['rejected']['duplicates']
            invalid_format = stats['rejected']['invalid_format']
            invalid_options = stats['rejected']['invalid_options']
            
            response = f"""╔══════════════════════════════════╗
║ 📝 𝗤𝘂𝗶𝘇 𝗔𝗱𝗱𝗶𝘁𝗶𝗼𝗻 𝗥𝗲𝗽𝗼𝗿𝘁 ║
╚══════════════════════════════════╝

✅ Successfully Added: {added_count} Questions  
📊 Total Quizzes: {total_quiz_count}  

❌ Rejected:  
• Duplicates: {duplicate_count}  
• Invalid Format: {invalid_format}  
• Invalid Options: {invalid_options}  

══════════════════════════════════"""

            # Edit the original message with the final report
            await message_to_edit.edit_text(response)
            
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"/addquiz: Added {stats['added']} quizzes in {response_time}ms (background)")
            
        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=user_id,
                chat_id=chat_id,
                command='/addquiz',
                details={'error': str(e), 'background_task': True},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in addquiz background task: {e}")
            try:
                await message_to_edit.edit_text("❌ Error processing quizzes in background.")
            except Exception as edit_error:
                logger.error(f"Failed to edit error message: {edit_error}")

    async def addquiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        if not update.message.from_user:
            return
        
        start_time = time.time()
        try:
            if not await self.is_developer(update.message.from_user.id):
                await self._handle_dev_command_unauthorized(update)
                return

            # Check rate limit (developers will bypass this automatically)
            if not await self.check_rate_limit(update, context, 'addquiz'):
                return

            # Log command immediately
            self._queue_activity_log(
                activity_type='command',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                username=update.effective_user.username or "",
                chat_title=getattr(update.effective_chat, 'title', None),
                command='/addquiz',
                success=True
            )

            # Extract message content and check for allow_duplicates flag
            message_text = update.message.text or ""
            allow_duplicates = '--allow-duplicates' in message_text or '-d' in message_text
            
            # Remove the command and flags
            message_text = message_text.replace('/addquiz', '').replace('--allow-duplicates', '').replace('-d', '').strip()
            
            if not message_text:
                await update.message.reply_text(
                    "❌ Please provide questions in the correct format.\n\n"
                    "For single question:\n"
                    "/addquiz question | option1 | option2 | option3 | option4 | correct_number\n\n"
                    "For multiple questions (using the | format):\n"
                    "/addquiz question1 | option1 | option2 | option3 | option4 | correct_number\n"
                    "/addquiz question2 | option1 | option2 | option3 | option4 | correct_number\n\n"
                    "To allow duplicate questions:\n"
                    "/addquiz --allow-duplicates question | options...\n\n"
                    "Add more Quiz /addquiz !"
                )
                return

            # Send immediate response without parsing (non-blocking)
            processing_msg = await update.message.reply_text(
                "⏳ Processing quiz questions in background..."
            )
            
            # Process quizzes in background - ALL parsing happens in the background thread
            asyncio.create_task(
                self._process_quizzes_background(
                    message_text=message_text,
                    allow_duplicates=allow_duplicates,
                    message_to_edit=processing_msg,
                    start_time=start_time,
                    user_id=update.effective_user.id,
                    chat_id=update.effective_chat.id
                )
            )
            
            logger.info("/addquiz: Started background processing (parsing will occur in thread)")

        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/addquiz',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in addquiz: {e}")
            await update.message.reply_text("❌ Error adding quiz.")


    async def editquiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        start_time = time.time()
        try:
            questions = self.quiz_manager.get_all_questions()
            
            if not questions:
                await update.message.reply_text(f"""════════════════
Add new quizzes using /addquiz command
════════════════""",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Handle reply to quiz case
            if update.message.reply_to_message and update.message.reply_to_message.poll:
                poll_id = update.message.reply_to_message.poll.id
                poll_data = context.bot_data.get(f"poll_{poll_id}")

                if not poll_data:
                    await self._handle_quiz_not_found(update, context)
                    return

                # Find the quiz in questions list
                found_idx = -1
                for idx, q in enumerate(questions):
                    if q['question'] == poll_data['question']:
                        found_idx = idx
                        break

                if found_idx == -1:
                    await self._handle_quiz_not_found(update, context)
                    return

                # Show the quiz details
                quiz = questions[found_idx]
                quiz_text = f"""📝 𝗤𝘂𝗶𝘇 𝗗𝗲𝘁𝗮𝗶𝗹𝘀 (#{found_idx + 1})
════════════════

❓ Question: {quiz['question']}
📍 Options:"""
                for i, opt in enumerate(quiz['options'], 1):
                    marker = "✅" if i-1 == quiz['correct_answer'] else "⭕"
                    quiz_text += f"\n{marker} {i}. {opt}"

                quiz_text += f"""
════════════════

To edit this quiz:
/editquiz {quiz['id']}
To delete this quiz:
/delquiz {quiz['id']}"""

                await update.message.reply_text(
                    quiz_text,
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Handle direct command case
            # Parse arguments for pagination
            args = context.args
            page = 1
            per_page = 5

            if args and args[0].isdigit():
                page = max(1, int(args[0]))

            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            total_pages = (len(questions) + per_page - 1) // per_page

            # Adjust page if out of bounds
            if page > total_pages:
                page = total_pages
                start_idx = (page - 1) * per_page
                end_idx = start_idx + per_page

            # Format questions for display
            questions_text = f"""📝 𝗤𝘂𝗶𝘇 𝗘𝗱𝗶𝘁𝗼𝗿 (Page {page}/{total_pages})
════════════════

📌 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:
• View quizzes: /editquiz [page_number]
• Delete quiz: /delquiz [quiz_number]
• Add new quiz: /addquiz

📊 𝗦𝘁𝗮𝘁𝘀:
• Total Quizzes: {len(questions)}
• Showing: #{start_idx + 1} to #{min(end_idx, len(questions))}

🎯 𝗤𝘂𝗶𝘇 𝗟𝗶𝘀𝘁:"""
            for i, q in enumerate(questions[start_idx:end_idx], start=start_idx + 1):
                questions_text += f"""

📌 𝗤𝘂𝗶𝘇 #{i}
❓ Question: {q['question']}
📍 Options:"""
                for j, opt in enumerate(q['options'], 1):
                    marker = "✅" if j-1 == q['correct_answer'] else "⭕"
                    questions_text += f"\n{marker} {j}. {opt}"
                questions_text += "\n════════════════"

            # Add navigation help
            if total_pages > 1:
                questions_text += f"""

📖 𝗡𝗮𝘃𝗶𝗴𝗮𝘁𝗶𝗼𝗻:"""
                if page > 1:
                    questions_text += f"\n⬅️ Previous: /editquiz {page-1}"
                if page < total_pages:
                    questions_text += f"\n➡️ Next: /editquiz {page+1}"

            # Send the formatted message
            await update.message.reply_text(
                questions_text,
                parse_mode=ParseMode.MARKDOWN
            )
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"Sent quiz list page {page}/{total_pages} to user {update.effective_user.id} in {response_time}ms")

        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/editquiz',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            error_msg = f"Error in editquiz command: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_msg)
            await update.message.reply_text(
                """❌ 𝗘𝗿𝗿𝗼𝗿
════════════════
Failed to display quizzes. Please try again later.
════════════════""",
                parse_mode=ParseMode.MARKDOWN
            )

    async def _handle_dev_command_unauthorized(self, update: Update) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        await update.message.reply_text(
            """╔═══🌸 𝐎𝐧𝐥𝐲 𝐑𝐞𝐬𝐩𝐞𝐜𝐭𝐞𝐝 𝐃𝐞𝐯𝐞𝐥𝐨𝐩𝐞𝐫 ═══════╗  

👑 𝐓𝐡𝐞 𝐎𝐖𝐍𝐄𝐑 & 𝐇𝐢𝐬 𝐁𝐞𝐥𝐨𝐯𝐞𝐝 𝐎𝐖𝐍𝐄𝐑 💞🤌  

╚════════════════════════════╝""",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def is_developer(self, user_id: int) -> bool:
        """Check if user is a developer with caching"""
        try:
            # First check if user is OWNER or WIFU (from environment)
            from src.core import config
            if user_id in config.AUTHORIZED_USERS:
                return True
            
            current_time = datetime.now()
            
            if user_id in self._developer_cache:
                cache_time = self._developer_cache_time.get(user_id)
                if cache_time and (current_time - cache_time) < self._developer_cache_duration:
                    return self._developer_cache[user_id]
            
            result = await self.db.is_developer_async(user_id)
            
            self._developer_cache[user_id] = result
            self._developer_cache_time[user_id] = current_time
            
            return result
        except Exception as e:
            logger.error(f"Error checking developer status: {e}")
            return False
    
    async def check_rate_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE, command_name: str) -> bool:
        """Check rate limit and return True if allowed"""
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return True
        
        is_developer = await self.is_developer(user_id)
        
        allowed, wait_seconds, limit_type = self.rate_limiter.check_limit(user_id, command_name, is_developer)
        
        if not allowed:
            self._queue_activity_log(
                activity_type='rate_limit',
                user_id=user_id,
                command=command_name,
                details={'wait_seconds': wait_seconds, 'limit_type': limit_type},
                success=False
            )
            
            if update.message:
                await update.message.reply_text(
                    f"⏱️ Slow down! You're using /{command_name} too quickly.\n\n"
                    f"⏰ Please wait {wait_seconds} seconds before trying again.\n\n"
                    f"💡 Tip: This prevents spam and keeps the bot fast for everyone!"
                )
            return False
        
        self.rate_limiter.record_command(user_id, command_name)
        return True
            
    async def get_developers(self) -> list:
        """Get list of all developers"""
        try:
            # Load developers from the developers.json file
            import json
            dev_file_path = os.path.join(os.path.dirname(__file__), "data", "developers.json")
            if os.path.exists(dev_file_path):
                with open(dev_file_path, 'r') as f:
                    dev_data = json.load(f)
                    return dev_data.get('developers', [])
            else:
                # Fallback to default developer IDs if file doesn't exist
                return [7653153066]
        except Exception as e:
            logger.error(f"Error getting developers: {e}")
            # Fallback to default developer IDs in case of error
            return [7653153066]
            
    async def save_developers(self, dev_list: list) -> bool:
        """Save the list of developers"""
        try:
            # Create data directory if it doesn't exist
            import json
            data_dir = os.path.join(os.path.dirname(__file__), "data")
            os.makedirs(data_dir, exist_ok=True)
            
            # Save developers to the developers.json file
            dev_file_path = os.path.join(data_dir, "developers.json")
            
            dev_data = {
                "developers": dev_list,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(dev_file_path, 'w') as f:
                json.dump(dev_data, f, indent=2)
            
            return True
        except Exception as e:
            logger.error(f"Error saving developers: {e}")
            return False

    async def broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        if not await self.is_developer(update.effective_user.id):
            await self._handle_dev_command_unauthorized(update)
            return
        
        try:
            message_text = (update.message.text or "").replace('/broadcast', '').strip()
            
            if not message_text:
                await update.message.reply_text("Usage: /broadcast <message>")
                return
            
            broadcast_message = f"""📢 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁 𝗠𝗲𝘀𝘀𝗮𝗴𝗲
════════════════

{message_text}"""

            # Get all active chats
            active_chats = self.quiz_manager.get_active_chats()
            success_count = 0
            failed_count = 0
            
            # OPTIMIZATION: Send messages in batches concurrently with controlled rate limiting
            batch_size = 5
            delay_between_batches = 0.5
            
            for i in range(0, len(active_chats), batch_size):
                batch = active_chats[i:i + batch_size]
                tasks = []
                
                for chat_id in batch:
                    task = context.bot.send_message(
                        chat_id=chat_id,
                        text=broadcast_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    tasks.append(task)
                
                # Wait for all tasks in batch to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for idx, result in enumerate(results):
                    if isinstance(result, Exception):
                        failed_count += 1
                        logger.error(f"Failed to send broadcast to {batch[idx]}: {result}")
                    else:
                        success_count += 1
                
                # Rate limiting between batches
                if i + batch_size < len(active_chats):
                    await asyncio.sleep(delay_between_batches)

            # Send results
            results = f"""📢 Broadcast Results:
✅ Successfully sent to: {success_count} chats
❌ Failed to send to: {failed_count} chats"""

            await update.message.reply_text(results)

            logger.info(f"Broadcast completed (optimized batching): {success_count} successful, {failed_count} failed")

        except Exception as e:
            logger.error(f"Error in broadcast: {e}")
            await update.message.reply_text("❌ Error sending broadcast. Please try again.")


    async def check_cooldown(self, user_id: int, command: str) -> bool:
        """Check if command is on cooldown for user"""
        current_time = datetime.now().timestamp()
        last_used = self.user_command_cooldowns[user_id].get(command, 0)
        if current_time - last_used < self.USER_COMMAND_COOLDOWN:
            return False
        self.user_command_cooldowns[user_id][command] = current_time
        return True

    async def cleanup_old_polls(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Remove old poll data to prevent memory leaks"""
        try:
            current_time = datetime.now()
            keys_to_remove = []

            for key, poll_data in context.bot_data.items():
                if not key.startswith('poll_'):
                    continue

                # Remove polls older than 1 hour
                if 'timestamp' in poll_data:
                    poll_time = datetime.fromisoformat(poll_data['timestamp'])
                    if (current_time - poll_time) > timedelta(hours=1):
                        keys_to_remove.append(key)

            for key in keys_to_remove:
                del context.bot_data[key]

            logger.info(f"Cleaned up {len(keys_to_remove)} old poll entries")

        except Exception as e:
            logger.error(f"Error cleaning up old polls: {e}")

    async def totalquiz(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Premium formatted /totalquiz command showing quiz library stats"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        if not update.message.from_user:
            return
        
        start_time = time.time()
        try:
            # Developer-only command
            if not await self.is_developer(update.message.from_user.id):
                await self._handle_dev_command_unauthorized(update)
                return
            
            # Get comprehensive quiz statistics
            quiz_stats = self.quiz_manager.get_quiz_stats()
            total_quizzes = quiz_stats['total_quizzes']
            
            # Premium formatted quiz library stats with Unicode box drawing
            response = f"""╔═══════════════════════╗
║ 📚  𝗤𝗨𝗜𝗭 𝗟𝗜𝗕𝗥𝗔𝗥𝗬 𝗦𝗧𝗔𝗧𝗦  ║
╚═══════════════════════╝

✨ Total Quizzes Available: {total_quizzes}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
➕ Use /addquiz to contribute new quizzes  
💡 Use /help to explore all commands"""

            await update.message.reply_text(response)
            response_time = int((time.time() - start_time) * 1000)
            logger.info(f"/totalquiz: {total_quizzes} quizzes ({response_time}ms)")

        except Exception as e:
            response_time = int((time.time() - start_time) * 1000)
            self._queue_activity_log(
                activity_type='error',
                user_id=update.effective_user.id,
                chat_id=update.effective_chat.id,
                command='/totalquiz',
                details={'error': str(e)},
                success=False,
                response_time_ms=response_time
            )
            logger.error(f"Error in totalquiz command: {e}")
            await update.message.reply_text("❌ Error getting total quiz count. Please try again.")

    async def send_automated_quiz(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send automated quiz to all active group chats"""
        try:
            # Send to groups
            active_chats = self.quiz_manager.get_active_chats()
            logger.info(f"Starting automated quiz broadcast to {len(active_chats)} active chats")

            for chat_id in active_chats:
                try:
                    # Check if chat is a group and bot is admin
                    try:
                        chat = await context.bot.get_chat(chat_id)
                    except Exception as e:
                        # Handle kicked/removed bot gracefully
                        if "Forbidden" in str(e) or "kicked" in str(e).lower() or "not found" in str(e).lower():
                            logger.info(f"Bot no longer has access to chat {chat_id} (kicked/removed), removing from active chats")
                            self.quiz_manager.remove_active_chat(chat_id)
                            continue
                        raise  # Re-raise if it's a different error
                    
                    if chat.type not in ["group", "supergroup"]:
                        logger.info(f"Skipping non-group chat {chat_id}")
                        continue

                    await self.ensure_group_registered(chat, context)

                    is_admin = await self.check_admin_status(chat_id, context)
                    if not is_admin:
                        logger.warning(f"Bot is not admin in chat {chat_id}, sending reminder")
                        await self.send_admin_reminder(chat_id, context)
                        continue

                    # Send automated quiz with tracking parameters
                    await self.send_quiz(chat_id, context, auto_sent=True, scheduled=True, chat_type=chat.type)
                    logger.info(f"Successfully sent automated quiz to chat {chat_id}")

                except Exception as e:
                    logger.error(f"Failed to send automated quiz to chat {chat_id}: {str(e)}\n{traceback.format_exc()}")
                    continue

            logger.info("Completed automated quiz broadcast cycle")

        except Exception as e:
            logger.error(f"Error in automated quiz broadcast: {str(e)}\n{traceback.format_exc()}")

    async def _handle_quiz_not_found(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        await update.message.reply_text(f"""════════════════
This quiz message is too old or no longer exists.
Please use /editquiz to view all available quizzes.
════════════════""",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.warning(f"Quiz not found in reply-to message from user {update.effective_user.id}")

    async def _handle_invalid_quiz_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE, command: str) -> None:
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        await update.message.reply_text(f"""════════════════
Please reply to a quiz message or use:
/{command} [quiz_number]

ℹ️ Use /editquiz to view all quizzes
════════════════""",
            parse_mode=ParseMode.MARKDOWN
        )
        logger.warning(f"Invalid quiz reply for {command} from user {update.effective_user.id}")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show comprehensive real-time bot statistics and monitoring dashboard - OPTIMIZED with caching"""
        if not update.message:
            return
        if not update.effective_user:
            return
        if not update.effective_chat:
            return
        
        # Check if user is developer
        if not await self.is_developer(update.effective_user.id):
            await self._handle_dev_command_unauthorized(update)
            return
        
        start_time = time.time()
        
        try:
            # Check rate limit
            if not await self.check_rate_limit(update, context, 'stats'):
                return
            
            loading_msg = await update.message.reply_text("📊 Loading dashboard...")
            
            # OPTIMIZATION 4: Use cached stats if available and recent (cache duration increased to 30s)
            current_time = datetime.now()
            cache_valid = (self._stats_cache is not None and 
                          self._stats_cache_time is not None and 
                          current_time - self._stats_cache_time < self._stats_cache_duration)
            
            if cache_valid:
                stats_data = self._stats_cache
                logger.debug("Using cached stats data (30s cache - performance optimization)")
            else:
                # OPTIMIZATION 4: Use combined query to fetch all quiz stats at once (reduces 4 queries to 1)
                combined_quiz_stats = self.db.get_all_quiz_stats_combined()
                
                # Fetch fresh data from database
                all_users = self.db.get_all_users_stats()
                pm_users = sum(1 for user in all_users if user.get('has_pm_access') == 1)
                group_only_users = sum(1 for user in all_users if user.get('has_pm_access') == 0 or user.get('has_pm_access') is None)
                
                stats_data = {
                    'total_users': len(all_users),
                    'pm_users': pm_users,
                    'group_only_users': group_only_users,
                    'total_groups': len(self.db.get_all_groups()),
                    'active_today': self.db.get_active_users_count('today'),
                    'active_week': self.db.get_active_users_count('week'),
                    'quiz_today': combined_quiz_stats['quiz_today'],
                    'quiz_week': combined_quiz_stats['quiz_week'],
                    'quiz_month': combined_quiz_stats['quiz_month'],
                    'quiz_all': combined_quiz_stats['quiz_all'],
                    'perf_metrics': self.db.get_performance_summary(24),
                    'trending': self.db.get_trending_commands(7, 5),
                    'recent_activities': self.db.get_recent_activities(10)
                }
                # Cache the results
                self._stats_cache = stats_data
                self._stats_cache_time = current_time
                logger.debug("Stats data fetched with combined query and cached (30s)")
            
            # Extract data from cache with None guard
            if not stats_data:
                logger.error("Stats data is None")
                return
            
            total_users = stats_data['total_users']
            pm_users = stats_data['pm_users']
            group_only_users = stats_data['group_only_users']
            total_groups = stats_data['total_groups']
            active_today = stats_data['active_today']
            active_week = stats_data['active_week']
            quiz_today = stats_data['quiz_today']
            quiz_week = stats_data['quiz_week']
            quiz_month = stats_data['quiz_month']
            quiz_all = stats_data['quiz_all']
            perf_metrics = stats_data['perf_metrics']
            trending = stats_data['trending']
            recent_activities = stats_data['recent_activities']
            
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            uptime_seconds = (datetime.now() - self.bot_start_time).total_seconds()
            if uptime_seconds >= 86400:
                uptime_str = f"{uptime_seconds/86400:.1f}d"
            elif uptime_seconds >= 3600:
                uptime_str = f"{uptime_seconds/3600:.1f}h"
            else:
                uptime_str = f"{uptime_seconds/60:.1f}m"
            
            activity_feed = ""
            for activity in recent_activities[:10]:
                time_ago = self.db.format_relative_time(activity['timestamp'])
                activity_type = activity['activity_type']
                username = activity.get('username', 'Unknown')
                
                if activity_type == 'command':
                    details = activity.get('details', {})
                    cmd = details.get('command', 'unknown') if isinstance(details, dict) else 'unknown'
                    activity_feed += f"• {time_ago}: @{username} used /{cmd}\n"
                elif activity_type == 'quiz_sent':
                    activity_feed += f"• {time_ago}: Quiz sent to group\n"
                elif activity_type == 'quiz_answered':
                    activity_feed += f"• {time_ago}: @{username} answered quiz\n"
                else:
                    activity_feed += f"• {time_ago}: {activity_type}\n"
            
            if not activity_feed:
                activity_feed = "• No recent activity\n"
            
            trending_text = ""
            for i, cmd in enumerate(trending[:5], 1):
                trending_text += f"{i}. /{cmd['command']}: {cmd['count']}x\n"
            if not trending_text:
                trending_text = "No commands used yet\n"
            
            stats_message = f"""📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝘀
━━━━━━━━━━━━━━━━━━━━
• 🌐 Total Groups: {total_groups} groups
• 👤 PM Users: {pm_users} users
• 👥 Group-only Users: {group_only_users} users
• 👥 Total Users: {total_users} users

════════════════════
🤖 𝗢𝘃𝗲𝗿𝗮𝗹𝗹 𝗣𝗲𝗿𝗳𝗼𝗿𝗺𝗮𝗻𝗰𝗲
────────────────────
• Today: {quiz_today.get('quizzes_answered', 0)}
• This Week: {quiz_week.get('quizzes_answered', 0)}
• This Month: {quiz_month.get('quizzes_answered', 0)}
• Total: {quiz_all.get('quizzes_answered', 0)}

━━━━━━━━━━━━━━━━━━━━
✨ Keep quizzing & growing! 🚀"""
            
            await loading_msg.edit_text(stats_message)
            
            logger.info(f"Showed stats to user {update.effective_user.id} in {(time.time() - start_time)*1000:.0f}ms")
            
        except Exception as e:
            logger.error(f"Error in stats_command: {e}", exc_info=True)
            await update.message.reply_text("❌ Error loading dashboard. Please try again.")
            
    async def handle_start_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        
        await query.answer()
        
        try:
            # Track PM access for callback handlers
            if update.effective_user and update.effective_chat:
                self._track_pm_access(update.effective_user.id, update.effective_chat.type)
            
            if query.data == "start_quiz":
                # Send quiz to user
                if not update.effective_chat:
                    return
                await self.send_quiz(update.effective_chat.id, context, chat_type=update.effective_chat.type)
                
            elif query.data == "my_stats":
                if not update.effective_user:
                    return
                stats = self.quiz_manager.get_user_stats(update.effective_user.id)
                if stats and stats.get('total_attempts', 0) > 0:
                    stats_message = f"""📊 𝗬𝗼𝘂𝗿 𝗣𝗲𝗿𝗳𝗼𝗿𝗺𝗮𝗻𝗰𝗲 𝗦𝘁𝗮𝘁𝘀
━━━━━━━━━━━━━━━━━━━━━

💯 Total Score: {stats['score']} points
✅ Total Quizzes: {stats['total_attempts']}
🎯 Correct Answers: {stats['correct_answers']}
📊 Accuracy: {stats['accuracy']}%
🔥 Current Streak: {stats['current_streak']}
👑 Best Streak: {stats['longest_streak']}

━━━━━━━━━━━━━━━━━━━━━
💡 Keep going to improve your rank!"""
                else:
                    stats_message = """📊 𝗬𝗼𝘂𝗿 𝗣𝗲𝗿𝗳𝗼𝗿𝗺𝗮𝗻𝗰𝗲 𝗦𝘁𝗮𝘁𝘀
━━━━━━━━━━━━━━━━━━━━━

🎯 No stats yet!
Start playing quizzes to track your progress.

━━━━━━━━━━━━━━━━━━━━━
💡 Use the button below to start!"""
                
                keyboard = [[InlineKeyboardButton("🎯 Start Quiz Now", callback_data="start_quiz")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if not update.effective_message:
                    return
                await update.effective_message.reply_text(stats_message, reply_markup=reply_markup)
                
            elif query.data == "leaderboard":
                # Show leaderboard
                leaderboard = self.quiz_manager.get_leaderboard()
                
                leaderboard_text = """╔═══════════════════════╗
║  🏆 𝗚𝗹𝗼𝗯𝗮𝗹 𝗟𝗲𝗮𝗱𝗲𝗿𝗯𝗼𝗮𝗿𝗱  ║
╚═══════════════════════╝

✨ 𝗧𝗼𝗽 𝟱 𝗤𝘂𝗶𝘇 𝗖𝗵𝗮𝗺𝗽𝗶𝗼𝗻𝘀 ✨
━━━━━━━━━━━━━━━━━━━━━━━"""
                
                if not leaderboard:
                    leaderboard_text += "\n\n🎯 No champions yet!\n💡 Be the first to claim the throne!"
                else:
                    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                    for rank, entry in enumerate(leaderboard[:5], 1):
                        try:
                            user = await context.bot.get_chat(entry['user_id'])
                            username = user.first_name or user.username or "Anonymous"
                            if len(username) > 15:
                                username = username[:12] + "..."
                            
                            score_display = f"{entry['score']/1000:.1f}K" if entry['score'] >= 1000 else str(entry['score'])
                            leaderboard_text += f"\n\n{medals[rank-1]} {username}\n💯 {score_display} pts • 🎯 {entry['accuracy']}%"
                        except Exception as e:
                            logger.debug(f"Could not fetch user info for leaderboard: {e}")
                            continue
                    
                    leaderboard_text += "\n\n━━━━━━━━━━━━━━━━━━━━━━━"
                
                keyboard = [[InlineKeyboardButton("🎯 Start Quiz", callback_data="start_quiz")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if not update.effective_message:
                    return
                await update.effective_message.reply_text(leaderboard_text, reply_markup=reply_markup)
                
            elif query.data == "help":
                # Show help
                help_message = """❓ 𝗛𝗲𝗹𝗽 & 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀
━━━━━━━━━━━━━━━━━━━━━━

📌 𝗕𝗮𝘀𝗶𝗰 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀:
/start - Start the bot
/quiz - Get a new quiz
/mystats - View your stats
/help - Show this help

🎯 𝗛𝗼𝘄 𝘁𝗼 𝗣𝗹𝗮𝘆:
1. Click "Start Quiz" or use /quiz
2. Answer the question
3. Earn points for correct answers
4. Build your streak for bonus points
5. Climb the leaderboard!

💡 𝗧𝗶𝗽𝘀:
• Maintain streaks for extra points
• Add bot to groups for auto-quizzes
• Answer quickly for the best experience

━━━━━━━━━━━━━━━━━━━━━━
🚀 Ready to play? Start now!"""
                
                keyboard = [[InlineKeyboardButton("🎯 Start Quiz", callback_data="start_quiz")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                if not update.effective_message:
                    return
                await update.effective_message.reply_text(help_message, reply_markup=reply_markup)
                
        except Exception as e:
            logger.error(f"Error in start callback handler: {e}")
            if query:
                await query.answer("❌ Error processing request", show_alert=True)
    
    async def handle_stats_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callbacks from the stats dashboard"""
        query = update.callback_query
        if not query:
            return
        
        await query.answer()
        
        try:
            # Track PM access for callback handlers
            if update.effective_user and update.effective_chat:
                self._track_pm_access(update.effective_user.id, update.effective_chat.type)
            
            start_time = time.time()
            
            if query.data == "stats_refresh":
                await query.edit_message_text("🔄 Refreshing dashboard...")
                
                total_users = len(self.db.get_all_users_stats())
                total_groups = len(self.db.get_all_groups())
                active_today = self.db.get_active_users_count('today')
                active_week = self.db.get_active_users_count('week')
                
                quiz_today = self.db.get_quiz_stats_by_period('today')
                quiz_week = self.db.get_quiz_stats_by_period('week')
                quiz_month = self.db.get_quiz_stats_by_period('month')
                quiz_all = self.db.get_quiz_stats_by_period('all')
                
                perf_metrics = self.db.get_performance_summary(24)
                trending = self.db.get_trending_commands(7, 5)
                recent_activities = self.db.get_recent_activities(10)
                
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                uptime_seconds = (datetime.now() - self.bot_start_time).total_seconds()
                if uptime_seconds >= 86400:
                    uptime_str = f"{uptime_seconds/86400:.1f}d"
                elif uptime_seconds >= 3600:
                    uptime_str = f"{uptime_seconds/3600:.1f}h"
                else:
                    uptime_str = f"{uptime_seconds/60:.1f}m"
                
                activity_feed = ""
                for activity in recent_activities[:10]:
                    time_ago = self.db.format_relative_time(activity['timestamp'])
                    activity_type = activity['activity_type']
                    username = activity.get('username', 'Unknown')
                    
                    if activity_type == 'command':
                        details = activity.get('details', {})
                        cmd = details.get('command', 'unknown') if isinstance(details, dict) else 'unknown'
                        activity_feed += f"• {time_ago}: @{username} used /{cmd}\n"
                    elif activity_type == 'quiz_sent':
                        activity_feed += f"• {time_ago}: Quiz sent to group\n"
                    elif activity_type == 'quiz_answered':
                        activity_feed += f"• {time_ago}: @{username} answered quiz\n"
                    else:
                        activity_feed += f"• {time_ago}: {activity_type}\n"
                
                if not activity_feed:
                    activity_feed = "• No recent activity\n"
                
                trending_text = ""
                for i, cmd in enumerate(trending[:5], 1):
                    trending_text += f"{i}. /{cmd['command']}: {cmd['count']}x\n"
                if not trending_text:
                    trending_text = "No commands used yet\n"
                
                stats_message = f"""📊 Real-Time Dashboard
━━━━━━━━━━━━━━━━━━━

👥 User Engagement
• Total Users: {total_users:,}
• Active Today: {active_today}
• Active This Week: {active_week}

📝 Quiz Activity (Today/Week/Month/All)
• Quizzes Sent: {quiz_today['quizzes_sent']}/{quiz_week['quizzes_sent']}/{quiz_month['quizzes_sent']}/{quiz_all['quizzes_sent']}
• Success Rate: {quiz_all['success_rate']}%

📊 Groups
• Total Groups: {total_groups:,}

⚡ Performance (24h)
• Avg Response Time: {perf_metrics['avg_response_time']:.0f}ms
• Commands Executed: {perf_metrics['total_api_calls']:,}
• Error Rate: {perf_metrics['error_rate']:.1f}%
• Memory Usage: {memory_mb:.1f}MB

🔥 Trending Commands (7d)
{trending_text}
📜 Recent Activity
{activity_feed}
━━━━━━━━━━━━━━━━━━━
⚙️ Uptime: {uptime_str} | 🕐 Load: {(time.time() - start_time)*1000:.0f}ms"""
                
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Refresh", callback_data="stats_refresh"),
                        InlineKeyboardButton("📊 Activity", callback_data="stats_activity")
                    ],
                    [
                        InlineKeyboardButton("⚡ Performance", callback_data="stats_performance"),
                        InlineKeyboardButton("📈 Trends", callback_data="stats_trends")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    stats_message,
                    reply_markup=reply_markup
                )
                
            elif query.data == "stats_activity":
                recent_activities = self.db.get_recent_activities(25)
                activity_text = "📊 Recent Activity Feed\n━━━━━━━━━━━━━━━━━━━\n\n"
                
                for activity in recent_activities:
                    time_ago = self.db.format_relative_time(activity['timestamp'])
                    activity_type = activity['activity_type']
                    username = activity.get('username', 'Unknown')
                    
                    if activity_type == 'command':
                        details = activity.get('details', {})
                        cmd = details.get('command', 'unknown') if isinstance(details, dict) else 'unknown'
                        activity_text += f"[{time_ago}] @{username}: /{cmd}\n"
                    elif activity_type == 'quiz_sent':
                        activity_text += f"[{time_ago}] Quiz sent\n"
                    elif activity_type == 'quiz_answered':
                        details = activity.get('details', {})
                        correct = details.get('is_correct', False) if isinstance(details, dict) else False
                        emoji = "✅" if correct else "❌"
                        activity_text += f"[{time_ago}] {emoji} @{username} answered\n"
                    else:
                        activity_text += f"[{time_ago}] {activity_type}\n"
                
                activity_text += "\n━━━━━━━━━━━━━━━━━━━"
                
                keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="stats_refresh")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    activity_text,
                    reply_markup=reply_markup
                )
                
            elif query.data == "stats_performance":
                perf_metrics = self.db.get_performance_summary(24)
                
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                perf_text = f"""⚡ Performance Metrics (24h)
━━━━━━━━━━━━━━━━━━━

📈 Response Times
• Average: {perf_metrics['avg_response_time']:.2f}ms
• Total API Calls: {perf_metrics['total_api_calls']:,}

💾 Memory Usage
• Current: {memory_mb:.2f} MB
• Average: {perf_metrics['avg_memory_mb']:.2f} MB

❌ Error Rate
• Rate: {perf_metrics['error_rate']:.2f}%

🟢 Uptime
• Status: {perf_metrics['uptime_percent']:.1f}%

━━━━━━━━━━━━━━━━━━━"""
                
                keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="stats_refresh")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    perf_text,
                    reply_markup=reply_markup
                )
                
            elif query.data == "stats_trends":
                trending = self.db.get_trending_commands(7, 10)
                activity_stats = self.db.get_activity_stats(7)
                
                trends_text = "📈 Trends & Analytics (7d)\n━━━━━━━━━━━━━━━━━━━\n\n"
                trends_text += "🔥 Trending Commands\n"
                for i, cmd in enumerate(trending, 1):
                    trends_text += f"{i}. /{cmd['command']}: {cmd['count']}x\n"
                
                trends_text += f"\n📊 Activity Breakdown\n"
                for activity_type, count in activity_stats['activities_by_type'].items():
                    trends_text += f"• {activity_type}: {count:,}\n"
                
                trends_text += f"\n✅ Success Rate: {activity_stats['success_rate']:.1f}%\n"
                trends_text += f"⚡ Avg Response: {activity_stats['avg_response_time_ms']:.0f}ms\n"
                trends_text += "\n━━━━━━━━━━━━━━━━━━━"
                
                keyboard = [[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="stats_refresh")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    trends_text,
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Error in handle_stats_callback: {e}", exc_info=True)
            await query.edit_message_text("❌ Error processing stats. Please try again.")
    
    async def handle_quiz_action_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callbacks from quiz action buttons (Play Again, My Stats, Leaderboard, Categories)"""
        query = update.callback_query
        if not query:
            return
        
        await query.answer()
        
        try:
            # Track PM access for callback handlers
            if update.effective_user and update.effective_chat:
                self._track_pm_access(update.effective_user.id, update.effective_chat.type)
            
            if query.data == "quiz_play_again":
                # Send a new quiz to the user
                if not update.effective_chat:
                    return
                await self.send_quiz(update.effective_chat.id, context, chat_type=update.effective_chat.type)
                await query.edit_message_text("🎯 New quiz sent! Good luck! 🚀")
                user_id = update.effective_user.id if update.effective_user else None
                logger.info(f"Sent new quiz from callback for user {user_id}")
                
            elif query.data == "quiz_my_stats":
                # Show user stats
                if not update.effective_user:
                    return
                    
                stats = self.db.get_user_quiz_stats_realtime(update.effective_user.id)
                
                if not stats or not stats.get('total_quizzes', 0):
                    no_stats_text = """╔═════════════════════════╗
║ 📊  𝐁𝐎𝐓 & 𝐔𝐒𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 
╚═════════════════════════╝

👤 𝐔𝐬𝐞𝐫: {update.effective_user.first_name}
🎯 No quizzes yet!

━━━━━━━━━━━━━━━━━━
💡 Get started:
• Use /quiz to try your first quiz
• Track your progress here
• Compete with others

Ready to begin? 🚀"""
                    await query.edit_message_text(no_stats_text)
                    return
                
                # Get user rank
                user_rank = self.db.get_user_rank(update.effective_user.id)
                if user_rank == 0:
                    user_rank = 'N/A'
                
                # Format stats
                user = update.effective_user
                quiz_attempts = stats.get('total_quizzes', 0)
                correct_answers = stats.get('correct_answers', 0)
                wrong_answers = stats.get('wrong_answers', 0)
                
                stats_message = f"""╔═════════════════════════╗
║ 📊  𝐁𝐎𝐓 & 𝐔𝐒𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃 
╚═════════════════════════╝

👤 𝐔𝐬𝐞𝐫: {user.first_name}
🏆 𝐑𝐚𝐧𝐤: #{user_rank}
🎮 𝐓𝐨𝐭𝐚𝐥 𝐐𝐮𝐢𝐳𝐳𝐞𝐬 𝐀𝐭𝐭𝐞𝐦𝐩𝐭𝐞𝐝: {quiz_attempts}

━━━━━━━━━━━━━━━━━━
🎯 𝐏𝐄𝐑𝐅𝐎𝐑𝐌𝐀𝐍𝐂𝐄 𝐒𝐓𝐀𝐓𝐒
━━━━━━━━━━━━━━━━━━
✅ 𝐂𝐨𝐫𝐫𝐞𝐜𝐭 𝐀𝐧𝐬𝐰𝐞𝐫𝐬: {correct_answers}
❌ 𝐖𝐫𝐨𝐧𝐠 𝐀𝐧𝐬𝐰𝐞𝐫𝐬: {wrong_answers}"""
                
                # Add keyboard
                keyboard = [
                    [
                        InlineKeyboardButton("🎯 Play Again", callback_data="quiz_play_again"),
                        InlineKeyboardButton("🏆 Leaderboard", callback_data="quiz_leaderboard")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    stats_message,
                    reply_markup=reply_markup
                )
                logger.info(f"Showed stats from callback for user {update.effective_user.id}")
                
            elif query.data == "quiz_leaderboard":
                # Show leaderboard
                result = await self._get_leaderboard_cached(limit=10, offset=0)
                if not result:
                    await query.edit_message_text(
                        "🏆 **Leaderboard**\n\n"
                        "No quiz champions yet! 🎯\n\n"
                        "Be the first to take a quiz and claim the top spot!\n\n"
                        "💡 Use /quiz to get started",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                leaderboard, total_count = result
                
                if not leaderboard:
                    await query.edit_message_text(
                        "🏆 **Leaderboard**\n\n"
                        "No quiz champions yet! 🎯\n\n"
                        "Be the first to take a quiz and claim the top spot!\n\n"
                        "💡 Use /quiz to get started",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                # Build leaderboard message
                medals = ["🥇", "🥈", "🥉"]
                leaderboard_text = "🏆 **TOP QUIZ CHAMPIONS** 🏆\n"
                leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                for idx, player in enumerate(leaderboard, 1):
                    if idx <= 3:
                        rank_display = medals[idx - 1]
                    else:
                        rank_display = f"{idx}."
                    
                    username = player.get('username', 'Unknown')
                    first_name = player.get('first_name')
                    user_id = player.get('user_id')
                    
                    if first_name and user_id:
                        user_display = f"[{first_name}](tg://user?id={user_id})"
                    else:
                        user_display = username
                    
                    score = player.get('score', 0)
                    correct = player.get('correct_answers', 0)
                    total_quizzes = player.get('total_quizzes', 0)
                    accuracy = player.get('accuracy', 0.0)
                    
                    leaderboard_text += f"{rank_display} **{user_display}**\n"
                    leaderboard_text += f"    💯 {score} | ✅ {correct}/{total_quizzes} | 🎯 {accuracy}%\n\n"
                
                leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                leaderboard_text += f"📊 Total Players: {total_count:,}\n\n"
                leaderboard_text += "💡 Keep playing to climb the ranks!"
                
                # Add keyboard
                keyboard = [
                    [
                        InlineKeyboardButton("🎯 Take Quiz", callback_data="quiz_play_again"),
                        InlineKeyboardButton("📊 My Stats", callback_data="quiz_my_stats")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    leaderboard_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                user_id = update.effective_user.id if update.effective_user else None
                logger.info(f"Showed leaderboard from callback for user {user_id}")
                
            elif query.data == "quiz_categories":
                # Show categories
                category_text = """📚 **QUIZ CATEGORIES**
━━━━━━━━━━━━━━━━━━━━━━━

Choose a category to explore:

🌍 General Knowledge
📰 Current Affairs
📚 Static GK
🔬 Science & Technology
📜 History
🗺 Geography
💰 Economics
🏛 Political Science
📖 Constitution
⚖️ Constitution & Law
🎭 Arts & Literature
🎮 Sports & Games

──────────────────────────────
💡 Use /category in the main chat for more info!"""
                
                # Add keyboard
                keyboard = [
                    [
                        InlineKeyboardButton("🎯 Take Quiz", callback_data="quiz_play_again"),
                        InlineKeyboardButton("📊 My Stats", callback_data="quiz_my_stats")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    category_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                user_id = update.effective_user.id if update.effective_user else None
                logger.info(f"Showed categories from callback for user {user_id}")
                
        except Exception as e:
            logger.error(f"Error in handle_quiz_action_callback: {e}", exc_info=True)
            if query:
                await query.answer("❌ Error processing request. Please try again!", show_alert=True)
    
    async def handle_leaderboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callbacks from leaderboard pagination buttons"""
        query = update.callback_query
        if not query or not query.data:
            return
        
        await query.answer()
        
        try:
            # Extract page number from callback data (e.g., "leaderboard_page_1")
            page = int(query.data.split('_')[-1])
            
            # Get top 100 from cached leaderboard
            result = await self._get_leaderboard_cached(limit=100, offset=0)
            if not result:
                await query.edit_message_text("❌ No leaderboard data available.")
                return
            
            leaderboard, total_count = result
            
            if not leaderboard:
                await query.edit_message_text("❌ No leaderboard data available.")
                return
            
            # Limit to top 100 users for display
            leaderboard = leaderboard[:100]
            
            # Calculate total pages (10 users per page)
            USERS_PER_PAGE = 10
            total_pages = (len(leaderboard) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
            
            # Validate page number
            if page < 0 or page >= total_pages:
                await query.answer("❌ Invalid page number", show_alert=True)
                return
            
            # Build the requested page
            leaderboard_text, reply_markup = self._build_leaderboard_page(leaderboard, page, total_pages)
            
            # Update the message
            try:
                await query.edit_message_text(
                    leaderboard_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info(f"Showed leaderboard page {page + 1} via callback")
            except BadRequest as e:
                # Ignore "message is not modified" error (happens when clicking same button twice)
                if "message is not modified" in str(e).lower():
                    logger.debug(f"Leaderboard page {page + 1} already displayed (duplicate click)")
                else:
                    raise
            
        except Exception as e:
            logger.error(f"Error in handle_leaderboard_callback: {e}", exc_info=True)
            if query:
                await query.answer("❌ Error loading page. Please try again!", show_alert=True)
    
    async def _show_detailed_user_stats(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show detailed user statistics"""
        try:
            # Get user stats
            if not hasattr(self.quiz_manager, 'stats') or not self.quiz_manager.stats:
                await query.edit_message_text(
                    "❌ No user statistics available.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
                )
                return
                
            valid_stats = {k: v for k, v in self.quiz_manager.stats.items() 
                         if isinstance(v, dict) and 'total_quizzes' in v}
                
            if not valid_stats:
                await query.edit_message_text(
                    "❌ No valid user statistics available.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
                )
                return
                
            # Sort users by score
            sorted_users = sorted(
                valid_stats.items(), 
                key=lambda x: x[1].get('current_score', 0), 
                reverse=True
            )
            
            # Format detailed user stats
            stats_message = """👥 Detailed User Statistics
━━━━━━━━━━━━━━━━━━━━━━━

🏆 Top Users by Score:
"""
            
            # Add top 10 users (or all if less than 10)
            for i, (user_id, stats) in enumerate(sorted_users[:10], 1):
                score = stats.get('current_score', 0)
                success_rate = stats.get('success_rate', 0)
                total_quizzes = stats.get('total_quizzes', 0)
                
                stats_message += f"{i}. User {user_id}: {score} pts ({success_rate}% success, {total_quizzes} quizzes)\n"
                
            stats_message += "\n📊 𝐔𝐬𝐞𝐫 𝐒𝐭𝐚𝐭𝐢𝐬𝐭𝐢𝐜𝐬 𝐒𝐮𝐦𝐦𝐚𝐫𝐲:\n"
            
            # Count users by activity
            current_date = datetime.now().strftime('%Y-%m-%d')
            week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
            month_start = (datetime.now().replace(day=1)).strftime('%Y-%m-%d')
            
            active_today = sum(1 for stats in valid_stats.values() if stats.get('last_activity_date') == current_date)
            active_week = sum(1 for stats in valid_stats.values() if stats.get('last_activity_date', '') >= week_start)
            active_month = sum(1 for stats in valid_stats.values() if stats.get('last_activity_date', '') >= month_start)
            
            stats_message += f"• Total Users: {len(valid_stats)}\n"
            stats_message += f"• Active Today: {active_today}\n"
            stats_message += f"• Active This Week: {active_week}\n"
            stats_message += f"• Active This Month: {active_month}\n"
            
            # Add navigation button
            back_button = InlineKeyboardButton("« Back to Main Stats", callback_data="refresh_stats")
            reply_markup = InlineKeyboardMarkup([[back_button]])
            
            await query.edit_message_text(
                stats_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in _show_detailed_user_stats: {e}")
            await query.edit_message_text(
                "❌ Error processing user statistics.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
            )
            
    async def _show_detailed_group_stats(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show detailed group statistics"""
        try:
            # Get active groups
            active_chats = self.quiz_manager.get_active_chats() if hasattr(self.quiz_manager, 'get_active_chats') else []
            
            if not active_chats:
                await query.edit_message_text(
                    "❌ No group statistics available.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
                )
                return
                
            # Format detailed group stats
            stats_message = """👥 Detailed Group Statistics
━━━━━━━━━━━━━━━━━━━━━━━

📊 Active Groups:
"""
            
            # Get activity dates for each group
            group_data = []
            current_date = datetime.now().strftime('%Y-%m-%d')
            
            for chat_id in active_chats:
                try:
                    # Get last activity
                    last_activity = "Unknown"
                    if hasattr(self.quiz_manager, 'get_group_last_activity'):
                        last_activity = self.quiz_manager.get_group_last_activity(chat_id) or "Never"
                        
                    # Get group members count if available
                    members_count = 0
                    if hasattr(self.quiz_manager, 'get_group_members'):
                        members = self.quiz_manager.get_group_members(chat_id)
                        if members:
                            members_count = len(members)
                            
                    # Determine activity status
                    status = "🔴 Inactive"
                    if last_activity == current_date:
                        status = "🟢 Active Today"
                    elif last_activity != "Never":
                        status = "🟠 Recent Activity"
                        
                    group_data.append((chat_id, last_activity, members_count, status))
                except Exception:
                    continue
                    
            # Sort groups by activity (most recent first)
            group_data.sort(key=lambda x: x[1] == current_date, reverse=True)
            
            # Add group listings
            for chat_id, last_activity, members_count, status in group_data:
                stats_message += f"• Group {chat_id}: {status}\n"
                stats_message += f"  └ Members: {members_count}, Last Activity: {last_activity}\n"
                
            # Add summary
            active_today = sum(1 for _, last_activity, _, _ in group_data if last_activity == current_date)
            
            stats_message += f"\n📊 𝐒𝐮𝐦𝐦𝐚𝐫𝐲:\n"
            stats_message += f"• Total Groups: {len(active_chats)}\n"
            stats_message += f"• Active Today: {active_today}\n"
            
            # Add navigation button
            back_button = InlineKeyboardButton("« Back to Main Stats", callback_data="refresh_stats")
            reply_markup = InlineKeyboardMarkup([[back_button]])
            
            await query.edit_message_text(
                stats_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in _show_detailed_group_stats: {e}")
            await query.edit_message_text(
                "❌ Error processing group statistics.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
            )
            
    async def _show_detailed_system_stats(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show detailed system statistics"""
        try:
            # Get system metrics
            process = psutil.Process()
            
            # CPU usage (overall system and this process)
            cpu_percent = process.cpu_percent(interval=0.1)
            system_cpu = psutil.cpu_percent(interval=0.1)
            
            # Memory usage
            memory_info = process.memory_info()
            memory_usage_mb = memory_info.rss / 1024 / 1024  # MB
            virtual_memory = psutil.virtual_memory()
            system_memory_usage = virtual_memory.percent
            
            # Disk usage
            disk_usage = psutil.disk_usage('/')
            disk_percent = disk_usage.percent
            disk_free_gb = disk_usage.free / (1024 ** 3)  # GB
            
            # Network stats - can be complex, simplified here
            net_io = psutil.net_io_counters()
            if net_io and hasattr(net_io, 'bytes_sent') and hasattr(net_io, 'bytes_recv'):
                bytes_sent_mb = net_io.bytes_sent / (1024 ** 2)  # type: ignore[union-attr]
                bytes_recv_mb = net_io.bytes_recv / (1024 ** 2)  # type: ignore[union-attr]
            else:
                bytes_sent_mb = 0.0
                bytes_recv_mb = 0.0
            
            # Bot uptime
            uptime_seconds = (datetime.now() - datetime.fromtimestamp(process.create_time())).total_seconds()
            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            uptime_str = ""
            if days > 0:
                uptime_str += f"{int(days)}d "
            if hours > 0 or days > 0:
                uptime_str += f"{int(hours)}h "
            if minutes > 0 or hours > 0 or days > 0:
                uptime_str += f"{int(minutes)}m "
            uptime_str += f"{int(seconds)}s"
            
            # Questions database info
            total_questions = 0
            if hasattr(self.quiz_manager, 'questions'):
                if isinstance(self.quiz_manager.questions, list):
                    total_questions = len(self.quiz_manager.questions)
                    
            # Create detailed system stats message piece by piece
            divider = "━━━━━━━━━━━━━━━━━━━━━━━"
            
            # Start with header
            stats_message = f"⚙️ Detailed System Statistics\n{divider}\n\n"
            
            # System resources section
            stats_message += "🖥️ System Resources:\n"
            stats_message += f"• CPU Usage (Bot): {cpu_percent:.1f}%\n"
            stats_message += f"• CPU Usage (System): {system_cpu:.1f}%\n"
            stats_message += f"• Memory Usage (Bot): {memory_usage_mb:.1f}MB\n"
            stats_message += f"• Memory Usage (System): {system_memory_usage:.1f}%\n"
            stats_message += f"• Disk Usage: {disk_percent:.1f}% (Free: {disk_free_gb:.1f}GB)\n"
            stats_message += f"• Network I/O: {bytes_sent_mb:.1f}MB sent, {bytes_recv_mb:.1f}MB received\n\n"
            
            # Uptime & availability section
            stats_message += "⏱️ Uptime & Availability:\n"
            stats_message += f"• Bot Uptime: {uptime_str}\n"
            stats_message += f"• Start Time: {datetime.fromtimestamp(process.create_time()).strftime('%Y-%m-%d %H:%M:%S')}\n"
            stats_message += f"• Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            
            # Database status section
            stats_message += "📊 Database Status:\n"
            stats_message += f"• Questions: {total_questions} entries\n"
            stats_message += "• Database Health: ✅ Operational\n\n"
            
            # System environment section
            stats_message += "🔄 System Environment:\n"
            stats_message += f"• Python Version: {sys.version.split()[0]}\n"
            stats_message += f"• Platform: {sys.platform}\n"
            stats_message += f"• Process PID: {process.pid}"
            
            # Add navigation button
            back_button = InlineKeyboardButton("« Back to Main Stats", callback_data="refresh_stats")
            reply_markup = InlineKeyboardMarkup([[back_button]])
            
            await query.edit_message_text(
                stats_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Error in _show_detailed_system_stats: {e}")
            await query.edit_message_text(
                "❌ Error processing system statistics.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="refresh_stats")]])
            )

