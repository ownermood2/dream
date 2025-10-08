# Overview

This project is a production-ready Telegram Quiz Bot application designed for interactive quiz functionality in Telegram chats and groups. It features a Flask web interface for administration, supports both webhook and polling deployment modes, and manages quiz questions, tracks user scores, and provides analytics. The primary goal is to deliver a robust, scalable, and user-friendly quiz experience with advanced administrative capabilities and seamless deployment across various platforms.

## Recent Changes (Oct 8, 2025)
- **Fixed automated quiz delivery bug**: Bot now correctly loads all active groups from database on startup. Previously, the `active_chats` list started empty after restarts, causing zero quiz broadcasts. Now loads groups from database into memory, ensuring automated quizzes are sent to all registered groups every 30 minutes.
- **Fixed closed topic handling**: Bot now gracefully skips closed forum topics during automated quiz delivery. When a topic is closed, the bot logs it as info and continues to the next group without errors. Only open topics receive quizzes.

## Previous Changes (Oct 7, 2025)
- **Implemented REAL-TIME MODE with zero caching**: Completely removed ALL caching from stats and leaderboard systems. Every `/mystats`, `/ranks`, `/leaderboard`, and `/stats` command now fetches live data directly from the database with zero delays. After each quiz attempt, user stats and ranks update instantly in the database, and subsequent commands show the updated data immediately. Removed all cache variables (_stats_cache, _leaderboard_cache), cache methods (_get_leaderboard_cached, _preload_leaderboard), and cache invalidation logic. All callbacks and scheduled jobs now query the database directly. This guarantees real-time synchronization with zero latency between quiz attempts and rank display.
- **Ranking system restored**: Leaderboard ranks users by `correct_answers DESC` (most correct answers first), with tiebreaker using `total_quizzes ASC` (fewer attempts rank higher for same correct answers). Both `/mystats` and `/ranks` use consistent ranking logic without timestamp dependencies.
- **Fixed async event loop blocking**: Database operations in quiz answer handler now use `asyncio.to_thread()` to prevent blocking, ensuring responsive bot during concurrent quiz attempts.
- **Fixed quiz ID visibility bug**: Quiz IDs are now completely hidden from users. Poll explanations are empty, and poll_id→quiz_id mappings are stored in database for `/delquiz` persistence across restarts.
- **Fixed /delquiz for old quizzes**: `/delquiz` now works on both old and new quizzes by using 3-tier extraction: database mapping → context.bot_data → question text matching. Works perfectly after bot restarts.
- **Fixed PostgreSQL SQL syntax errors**: Converted all direct `cursor.execute()` calls to use `self._execute()` for proper placeholder conversion (`?` → `%s`).
- **Fixed foreign key constraint error**: User deletion now properly removes related records from `user_daily_activity`, `quiz_history`, and `activity_logs`.
- **Fixed bare except blocks**: Replaced all dangerous bare `except:` blocks with proper exception handling to improve error logging and prevent catching system signals.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Application Structure
The application employs a modular, production-ready architecture with a clear package structure: `src/core/`, `src/bot/`, `src/web/`, and `main.py`. Key components include a Flask Web Application for admin and webhooks, a Telegram Bot Handler for interactions and commands, a Database Manager with dual-backend support, a Quiz Manager for core quiz logic, and centralized Configuration. It supports dual deployment modes (polling/webhook) with automatic detection.

## Data Storage
The system supports dual database backends: PostgreSQL for production (recommended, with `BIGINT` support for Telegram IDs and automatic migration) and SQLite for development. Cloud PostgreSQL options like Neon/Supabase are supported. A robust SQLite fallback system is implemented for read-only filesystems, ensuring data preservation and clear logging. Quiz data is stored exclusively in PostgreSQL with in-memory caching for performance.

## Frontend Architecture
The Flask web application provides a health check endpoint (`/`), an admin panel (`/admin`) using Bootstrap for question management, and a Prometheus-style metrics endpoint (`/metrics`) with caching. Jinja2 is used for templating, and RESTful APIs are available for quiz data management.

## Bot Architecture
The bot features structured command processing with advanced rate limiting, role-based access control, and PicklePersistence for poll data across restarts. An optimized auto-clean system manages message deletion in groups. Comprehensive statistics tracking, a versatile broadcast system, and an auto-quiz scheduler are included. It supports universal PM tracking and a three-tier rate limiting system. Quiz management includes `/addquiz` (fully asynchronous) and `/editquiz` with interactive editing. Reply-based command UX, paginated leaderboards, post-quiz action buttons, enhanced help with Unicode UI, and a premium stats dashboard provide an interactive user experience. Developer-only commands like `/status` and friendly error messages are also present.

## System Design Choices
The system is designed for production-ready deployment supporting both webhook and polling modes. It features lazy initialization, bulletproof conflict recovery with a three-tier system, and Docker support with multi-stage Dockerfile and docker-compose. A comprehensive pytest suite (118 tests, >70% coverage) ensures reliability. Advanced broadcasts, automated scheduling, robust error handling, real-time tracking, and performance optimizations (database query optimization, caching, batch logging) are integrated. Data integrity is maintained through PostgreSQL-only storage, in-memory caching, database ID-based operations, transaction safety, and quiz validation. Network resilience is ensured with `HTTPXRequest` timeouts, and single instance enforcement is achieved via a PID lockfile. The system is platform-agnostic and health check compliant.

# External Dependencies

-   **python-telegram-bot**: Telegram Bot API wrapper.
-   **Flask**: Web framework.
-   **apscheduler**: Task scheduling.
-   **psutil**: System monitoring.
-   **httpx**: Async HTTP client.
-   **gunicorn**: Production WSGI server.

## External Services
-   **Telegram Bot API**: Primary external service.
-   **Replit Environment**: Hosting platform.

## Environment Variables
-   **Required**: `TELEGRAM_TOKEN`, `SESSION_SECRET`.
-   **Database**: `DATABASE_URL` (for PostgreSQL).
-   **Deployment**: `RENDER_URL`, or manual `MODE` and `WEBHOOK_URL`.
-   **Server**: `HOST`, `PORT`.
-   **Optional**: `OWNER_ID`, `WIFU_ID`.