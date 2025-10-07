# Overview

This project is a production-ready Telegram Quiz Bot application designed for interactive quiz functionality in Telegram chats and groups. It includes a Flask web interface for administration, supports both webhook and polling deployment modes, and manages quiz questions, tracks user scores, and provides analytics. The primary goal is to deliver a robust, scalable, and user-friendly quiz experience with advanced administrative capabilities and seamless deployment across various platforms.

## Recent Changes (Oct 7, 2025)
- **Fixed /delquiz reply functionality**: Quiz polls now include quiz ID in explanation field `[ID: 123]` for reliable extraction when replying with /delquiz command. This ensures developers can delete quizzes by replying to poll messages, even after bot restarts.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Application Structure
The application employs a modular, production-ready architecture with a clear package structure:
```
src/
├── core/          # Core business logic (config, database, quiz)
├── bot/           # Telegram bot components (handlers, dev_commands)
└── web/           # Flask web application (app.py)
main.py            # Entry point
```

**Key Components:**
- **Flask Web Application**: Provides an admin interface, health checks, and a webhook endpoint. Uses an `_AppProxy` pattern for deferred initialization.
- **Telegram Bot Handler**: Manages all Telegram bot interactions, commands, and schedulers, including developer-specific commands with access control.
- **Database Manager**: Handles database operations with dual-backend support (PostgreSQL for production, SQLite for development).
- **Quiz Manager**: Contains the core business logic for quiz operations and scoring.
- **Configuration**: Centralized management of environment variables with lazy validation.
- **Dual-Mode Support**: Automatically detects and operates in either polling (for VPS/local) or webhook (for Render/Heroku/Railway) modes.

## Data Storage
The system supports dual database backends with automatic detection:
-   **PostgreSQL (Production - Recommended)**: Used when `DATABASE_URL` is set, offering persistent storage and scalability. All Telegram ID columns use `BIGINT` to support large user/group IDs.
    - **Cloud PostgreSQL (Neon/Supabase)**: Free cloud PostgreSQL databases supported for cross-platform deployment. Set same `DATABASE_URL` on all platforms (Replit, Pella, Render, etc.) for shared data across instances.
-   **SQLite (Development/Local)**: Used by default, file-based (`data/quiz_bot.db`), suitable for local development. Includes intelligent fallback system for read-only filesystems.

The database schema includes tables for `questions`, `users`, `developers`, `groups`, `user_daily_activity`, `quiz_history`, `activity_logs`, `performance_metrics`, `quiz_stats`, and `broadcast_logs`.

**Automatic PostgreSQL Migration**: On PostgreSQL startup, the system automatically detects and converts any INTEGER Telegram ID columns to BIGINT across all 10 tables (users.user_id, developers.user_id, user_daily_activity.user_id, quiz_history.user_id/chat_id, activity_logs.user_id/chat_id, broadcast_logs.admin_id, broadcasts.sender_id, groups.chat_id). This prevents "integer out of range" errors for large Telegram IDs.

**SQLite Fallback System**: For read-only filesystems (Pella, Render free tier, Railway, etc.), the system automatically:
1. **Auto-creates directories**: Uses `os.makedirs()` to create the `data/` folder before connecting
2. **Smart fallback**: If `data/quiz_bot.db` fails (read-only, permissions), automatically falls back to `/tmp/quiz_bot.db`
3. **Data preservation**: When falling back, checks if original database exists and has data (via file size), then copies it to `/tmp/` to preserve existing quiz questions, users, and statistics
4. **Crystal-clear logging**: Shows exactly where the database is stored (primary or fallback path) with emoji indicators (📁✅⚠️💾)
5. **Zero data loss**: Ensures smooth operation across all hosting platforms without manual intervention

**PostgreSQL-Only Storage**: Questions and all quiz data are stored exclusively in PostgreSQL database for production-grade reliability. The system uses intelligent in-memory caching for optimal performance, eliminating file I/O dependencies and ensuring data consistency.

## Frontend Architecture
-   **Health Check Endpoint**: `/` returns `{"status":"ok"}`.
-   **Admin Panel**: `/admin` provides a Bootstrap-based web interface for question management.
-   **Metrics Endpoint**: `/metrics` provides Prometheus-style monitoring with 17 metrics (system, database, performance, broadcast) for Grafana/Prometheus integration. Includes 30-second caching.
-   **Templating**: Flask's Jinja2 for server-side rendering.
-   **API Endpoints**: RESTful API for quiz data management.

## Bot Architecture
-   **Command Handlers**: Structured command processing with advanced rate limiting system.
-   **Access Control**: Role-based access for admin and developer commands.
-   **Persistence System**: PicklePersistence enabled to save poll data (`context.bot_data`) across restarts. Ensures quiz answers are recorded even if users answer after bot restart. Persistence file: `data/bot_persistence`.
-   **Optimized Auto-Clean System**: Smart message deletion in groups for cleaner chats with command-specific timing:
    - `/start`, `/help`, `/category`: Auto-delete command and bot reply after 60 seconds
    - `/mystats`: Auto-delete command and bot reply after 30 seconds (optimized for faster cleanup)
    - `/quiz`: Delete only command message (1 second delay), keep quiz visible
    - `/leaderboard`: Auto-delete after 60 seconds (allows time for page navigation)
    - Uses async deletion (`asyncio.create_task`) for non-blocking operation
    - Requires bot admin permissions for deletion
    - Only active in groups, preserves all messages in private chats
-   **Statistics Tracking**: Comprehensive user and group activity monitoring with universal PM access tracking.
-   **Broadcast System**: Supports various broadcast types (text, media, buttons) with placeholders, live tracking, and auto-cleanup.
-   **Auto Quiz System**: Sends automated quizzes to groups every 30 minutes. Users can manually request quizzes in PM using /quiz command.
-   **Universal PM Tracking**: All user interactions in private messages are tracked for better targeting and analytics.
-   **Rate Limiting System**: Three-tier rate limiting (Heavy/Medium/Light commands) with sliding window algorithm, developer bypass, automatic cleanup, and violation logging. Prevents command spam while maintaining smooth UX.
-   **Quiz Management**: Complete quiz lifecycle management including /addquiz for creation and /editquiz for interactive editing with pagination, field-by-field updates, and audit logging.
    - **Fully Asynchronous /addquiz**: Non-blocking quiz import system using `asyncio.to_thread()` to offload ALL expensive operations (parsing, validation, database writes) to background thread pool. Bot remains fully responsive during large quiz imports of any size.
-   **Reply-Based Command UX**: Developer commands support context-aware replies for intuitive workflows. Reply to quiz messages with /delquiz or /editquiz for instant actions (quiz ID embedded in poll explanation for persistence across restarts). Reply to any message with /broadcast to rebroadcast it, or /dev for contextual diagnostics.
-   **Interactive UX Features**:
    - **Paginated Leaderboard**: `/leaderboard` displays top 10 quiz champions with smooth pagination (5 users per page). Features clickable user names (Telegram profile links), total attempts, correct/wrong breakdown, and Next/Back navigation buttons. Auto-cleanup in groups (60-second delay for navigation). Cached for performance.
    - **Post-Quiz Action Buttons**: After answering quizzes in private chats, users see 4 action buttons: Play Again, My Stats, Leaderboard, and Categories for seamless navigation.
    - **Enhanced Help with Unicode UI**: Beautiful `/help` command with Unicode box-drawing characters (╔═╗║╚╝), bold Unicode text (𝐌𝐈𝐒𝐒 𝐐𝐔𝐈𝐙 𓂀 𝐁𝐎𝐓), personalized user display, and organized sections (User/Developer Commands, Features).
    - **Premium Stats Dashboard**: Unified clean stats format across all commands (/mystats, /addquiz, callbacks) with compact box-drawing characters, bold Unicode labels (𝐁𝐎𝐓 & 𝐔𝐒𝐄𝐑 𝐒𝐓𝐀𝐓𝐒 𝐃𝐀𝐒𝐇𝐁𝐎𝐀𝐑𝐃, 𝐏𝐄𝐑𝐅𝐎𝐑𝐌𝐀𝐍𝐂𝐄 𝐒𝐓𝐀𝐓𝐒), and consistent spacing for professional presentation.
    - **Status Monitoring**: `/status` command (developer-only) shows bot health, uptime, database stats, performance metrics, and scheduler status.
    - **Friendly Error Messages**: All errors include actionable guidance and helpful suggestions (e.g., "Try /help for available commands").

## System Design Choices
-   **Production-Ready Deployment**: Supports both webhook and polling modes.
-   **No Import-Time Side Effects**: Lazy initialization prevents gunicorn crashes.
-   **Dual-Mode Architecture**: Auto-detects mode based on environment variables.
-   **Bulletproof Conflict Recovery**: Three-tier automatic conflict resolution system eliminates "Conflict: terminated by other getUpdates request" errors:
    - **Startup Webhook Cleanup**: 3-retry loop with exponential backoff to delete any existing webhooks before polling. Aborts startup if cleanup fails to prevent conflicted state.
    - **Initialization-Level Recovery**: 3-retry loop around bot initialization catches Conflict errors, triggers webhook cleanup, and retries. Aborts on non-Conflict exceptions or cleanup failures with clear logging.
    - **Runtime Conflict Recovery**: Error handler catches Conflict errors during ongoing polling, stops updater, re-raises exception to trigger outer retry loop with webhook cleanup and automatic restart. Prevents bot from going offline due to transient conflicts.
    - **Graceful Degradation**: All failure paths log critical errors with actionable messages and abort cleanly after max retries to prevent infinite loops or zombie processes.
-   **Docker Support**: Complete Docker deployment with multi-stage Dockerfile and docker-compose.yml (bot + PostgreSQL + Redis). Production-optimized with health checks, volume persistence, and security best practices.
-   **Comprehensive Test Suite**: 118 pytest tests covering database, quiz logic, rate limiting, handlers, and developer commands. 70%+ coverage with fast execution, strong assertions, and CI-ready configuration.
-   **Advanced Broadcasts**: Versatile broadcast system.
-   **Automated Scheduling**: Persistent quiz scheduling to active groups.
-   **Robust Error Handling & Logging**: Comprehensive logging and error recovery.
-   **Real-time Tracking System**: Activity logging and analytics.
-   **Performance Optimizations**: 
    - Database query optimization with efficient rank calculation (O(1) vs O(n) for /mystats)
    - Command caching and concurrent broadcast processing
    - User info caching and batch activity logging
    - Optimized leaderboard caching with 5-minute TTL
    - Instant /help and /start commands (no cooldowns)
    - Chat type parameter passing to avoid redundant get_chat API calls
    - PM quiz message cleanup to prevent database bloat
-   **Data Integrity & Reliability**:
    - **PostgreSQL-Only Storage**: Single source of truth eliminates sync issues and data inconsistencies
    - **In-Memory Caching**: Intelligent caching layer for fast quiz delivery without file I/O
    - **Database ID-Based Operations**: All quiz operations use database IDs for reliable CRUD operations. PostgreSQL uses `RETURNING id` clause for insertions (not `cursor.lastrowid` which is SQLite-only)
    - **Transaction Safety**: Database transactions ensure atomic operations and data consistency
    - **Enhanced /totalquiz**: Shows comprehensive stats with category breakdown and quiz counts
    - **Quiz Validation**: All 641 questions validated for correctness with automated validation script (validate_and_fix_quizzes.py)
-   **Network Resilience**: Configured HTTPXRequest with balanced timeouts.
-   **Single Instance Enforcement**: PID lockfile prevents multiple bot instances.
-   **Platform-Agnostic**: Compatible with Pella, Render, VPS, Replit, Railway, Heroku, and other hosting platforms with read-only filesystems.
-   **Health Check Compliance**: Simple GET `/` endpoint.

# External Dependencies

-   **python-telegram-bot**: Telegram Bot API wrapper, including job queue support.
-   **Flask**: Web framework for the administrative panel and health checks.
-   **apscheduler**: Task scheduling (integrated with `python-telegram-bot`).
-   **psutil**: System monitoring and memory tracking.
-   **httpx**: Async HTTP client used by `python-telegram-bot`.
-   **gunicorn**: Production WSGI server.

## External Services
-   **Telegram Bot API**: Primary external service for bot operations.
-   **Replit Environment**: Hosting platform.

## Environment Variables
-   **Required**: `TELEGRAM_TOKEN`, `SESSION_SECRET`.
-   **Database**: `DATABASE_URL` (for PostgreSQL).
-   **Deployment**: `RENDER_URL` (for Render/webhook auto-detection), or manual `MODE` (`polling`/`webhook`) and `WEBHOOK_URL`.
-   **Server**: `HOST` (default: `0.0.0.0`), `PORT` (default: `5000`).
-   **Optional**: `OWNER_ID`, `WIFU_ID`.