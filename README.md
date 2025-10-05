# 🎯 Telegram Quiz Bot

**An interactive quiz bot with automated scheduling, comprehensive analytics, and universal deployment support.**

A production-ready Telegram bot that delivers engaging quizzes to users and groups with automated scheduling, detailed statistics tracking, and a web-based admin panel. Designed for seamless deployment across any platform—from cloud services to local servers—with intelligent auto-detection of webhook or polling modes.

---

## 📑 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Deployment Options](#-deployment-options)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Commands](#-commands)
- [Development](#-development)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

### Core Functionality
- 🎲 **Interactive Quiz System** - Native Telegram quiz polls with instant results and automatic scoring
- ⏰ **Automated Scheduling** - Quizzes automatically delivered every 30 minutes to active groups
- 📊 **Comprehensive Statistics** - Track user performance, quiz history, and engagement metrics
- 🏆 **Leaderboards** - Rankings for top performers with detailed breakdowns
- 🗂️ **Category System** - Organize quizzes by topic for targeted learning

### Administration
- 🎨 **Web Admin Panel** - Flask-based interface for quiz management (add/edit/delete questions)
- 📢 **Broadcast System** - Send announcements to all users or groups with inline button support
- 👨‍💻 **Developer Commands** - Advanced tools for bot administration, analytics, and maintenance
- 🧹 **Smart Auto-Cleanup** - Automatically removes old quiz messages to keep groups clean

### Production-Ready Features
- 🔄 **Dual-Mode Support** - Auto-detects webhook (Render/Heroku/Railway) or polling (VPS/Replit) modes
- 🗄️ **SQLite Database** - Persistent storage for questions, users, groups, and detailed analytics
- 🐳 **Docker Support** - Multi-stage Dockerfile with health checks and docker-compose configuration
- 🌍 **Universal Deployment** - Deploy on any platform without code modifications
- 🔌 **Network Resilience** - Automatic reconnection with balanced timeouts for stable operation
- 📈 **Performance Monitoring** - Memory tracking, API call logging, and automated cleanup jobs

---

## 🏗️ Architecture

### Modular Structure

The bot uses a clean, production-ready architecture organized into three main modules:

```
src/
├── core/          # Core business logic
│   ├── config.py       # Configuration and environment management
│   ├── database.py     # SQLite database operations
│   ├── quiz.py         # Quiz management and scoring logic
│   └── exceptions.py   # Custom exception handling
├── bot/           # Telegram bot components
│   ├── handlers.py     # Command handlers and schedulers
│   └── dev_commands.py # Developer-specific commands
└── web/           # Flask web application
    ├── app.py          # Web server and API endpoints
    └── wsgi.py         # Production WSGI entry point
```

### Database Layer

- **SQLite** for data persistence and performance
- **Tables:** questions, users, developers, groups, user_daily_activity, quiz_history, activity_logs, performance_metrics, quiz_stats, broadcast_logs
- **Automatic migrations** and schema initialization on startup
- **Database indexing** for optimized queries

### Web Interface

- **Flask** web framework with Bootstrap UI
- **Admin Panel** at `/admin` for question management
- **RESTful API** endpoints for programmatic access
- **Health Check** endpoint at `/` for platform monitoring

### Dual-Mode Support

The bot intelligently detects deployment mode:

- **Polling Mode** (Replit, VPS, local): Bot actively polls Telegram servers
- **Webhook Mode** (Render, Railway, Heroku): Telegram pushes updates to your server
- **Auto-detection** based on `WEBHOOK_URL` or `RENDER_URL` environment variables

---

## 🚀 Quick Start

### Prerequisites

1. **Python 3.11+** installed on your system
2. **Telegram Bot Token** - Create a bot via [@BotFather](https://t.me/BotFather)
3. **Session Secret** - Generate with: 
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
4. **Your Telegram User ID** - Get from [@userinfobot](https://t.me/userinfobot) (optional but recommended)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/telegram-quiz-bot.git
   cd telegram-quiz-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and set your values:
   ```env
   TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   SESSION_SECRET=your_64_character_hex_string_here
   OWNER_ID=123456789
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

5. **Access admin panel** (optional)
   
   Open your browser: `http://localhost:5000/admin`

### Verify Installation

1. Open Telegram and find your bot
2. Send `/start` to begin
3. Send `/quiz` to test quiz functionality
4. Check logs in `bot.log` or console output

---

## 📦 Deployment Options

### 🟦 Replit (Easiest)

**Best for:** Quick testing, development, always-free hosting

1. **Import Repository**
   - Fork this Repl or import from GitHub URL
   - Click "Import from GitHub"

2. **Configure Secrets**
   - Click the 🔒 Secrets icon in sidebar
   - Add these secrets:
     ```
     TELEGRAM_TOKEN=your_bot_token
     SESSION_SECRET=your_session_secret
     OWNER_ID=your_telegram_user_id
     ```

3. **Run**
   - Click the "Run" button
   - Bot automatically starts in polling mode ✅

4. **Access Admin Panel**
   - Click the webview URL at top
   - Add `/admin` to access the dashboard

**Mode:** Polling (automatic)  
**Free Tier:** Yes, with always-on capability

---

### 🟩 Railway

**Best for:** Production deployments, reliable uptime

1. **Create New Project**
   - Go to [Railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your forked repository

2. **Configure Environment Variables**
   - Go to Variables tab
   - Add:
     ```
     TELEGRAM_TOKEN=your_token_here
     SESSION_SECRET=your_secret_here
     OWNER_ID=your_user_id
     ```

3. **Deploy**
   - Railway auto-detects Python
   - Runs `python main.py` automatically
   - Bot starts in polling mode

**Mode:** Polling (default)  
**Free Tier:** $5 credit/month  
**Advantages:** Fast deployment, automatic scaling

---

### 🟪 Render

**Best for:** Webhook mode, free tier with good limits

1. **Create Web Service**
   - Go to [Render.com](https://render.com)
   - Click "New" → "Web Service"
   - Connect your GitHub repository

2. **Configure Service**
   - **Name:** `telegram-quiz-bot`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT`

3. **Set Environment Variables**
   ```
   TELEGRAM_TOKEN=your_token_here
   SESSION_SECRET=your_secret_here
   OWNER_ID=your_user_id
   RENDER_URL=https://your-app-name.onrender.com/webhook
   ```

4. **Deploy**
   - Click "Create Web Service"
   - Wait for build to complete
   - Bot automatically uses webhook mode

**Mode:** Webhook (auto-detected from `RENDER_URL`)  
**Free Tier:** 750 hours/month  
**Note:** Services sleep after inactivity on free tier

---

### 🟥 Heroku

**Best for:** Enterprise deployments, add-on ecosystem

1. **Install Heroku CLI**
   ```bash
   # Download from https://devcenter.heroku.com/articles/heroku-cli
   heroku login
   ```

2. **Create Heroku App**
   ```bash
   heroku create your-quiz-bot
   ```

3. **Set Configuration**
   ```bash
   heroku config:set TELEGRAM_TOKEN=your_token
   heroku config:set SESSION_SECRET=your_secret
   heroku config:set OWNER_ID=your_user_id
   heroku config:set WEBHOOK_URL=https://your-quiz-bot.herokuapp.com/webhook
   ```

4. **Deploy**
   ```bash
   git push heroku main
   ```

5. **Check Status**
   ```bash
   heroku logs --tail
   heroku ps
   ```

**Mode:** Webhook (auto-detected)  
**Note:** Uses `Procfile` automatically  
**Advantages:** Professional-grade, extensive add-ons

---

### 🐳 Docker

**Best for:** Containerized deployments, consistent environments

#### Option 1: Docker CLI

```bash
# Build image
docker build -t telegram-quiz-bot .

# Run container
docker run -d \
  -e TELEGRAM_TOKEN=your_token \
  -e SESSION_SECRET=your_secret \
  -e OWNER_ID=your_user_id \
  -p 5000:5000 \
  --name quiz-bot \
  telegram-quiz-bot

# View logs
docker logs -f quiz-bot

# Stop container
docker stop quiz-bot
```

#### Option 2: Docker Compose

```bash
# Create .env file with your variables
cp .env.example .env
# Edit .env with your values

# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

**Mode:** Polling (default), webhook if `WEBHOOK_URL` is set  
**Advantages:** Portable, isolated, easy to scale

---

### 🖥️ VPS / Linux Server

**Best for:** Full control, maximum customization

1. **Connect to Server**
   ```bash
   ssh user@your-server-ip
   ```

2. **Install Python**
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip python3-venv -y
   ```

3. **Clone Repository**
   ```bash
   git clone https://github.com/yourusername/telegram-quiz-bot.git
   cd telegram-quiz-bot
   ```

4. **Set Up Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Configure Environment**
   ```bash
   nano .env
   # Add TELEGRAM_TOKEN, SESSION_SECRET, OWNER_ID
   ```

6. **Run Bot**
   
   **Simple (foreground):**
   ```bash
   python main.py
   ```
   
   **Background (using screen):**
   ```bash
   screen -S telegram-bot
   python main.py
   # Press Ctrl+A then D to detach
   # Reattach: screen -r telegram-bot
   ```

7. **Create Systemd Service** (recommended for production)
   ```bash
   sudo nano /etc/systemd/system/telegram-quiz-bot.service
   ```
   
   ```ini
   [Unit]
   Description=Telegram Quiz Bot
   After=network.target

   [Service]
   Type=simple
   User=your-username
   WorkingDirectory=/home/your-username/telegram-quiz-bot
   ExecStart=/home/your-username/telegram-quiz-bot/venv/bin/python main.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
   
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-quiz-bot
   sudo systemctl start telegram-quiz-bot
   sudo systemctl status telegram-quiz-bot
   ```

**Mode:** Polling (recommended for VPS)  
**Advantages:** Full control, no platform limits

---

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `TELEGRAM_TOKEN` | ✅ Yes | Bot token from @BotFather | `123456789:ABCdefGHIjklMNOpqrs` |
| `SESSION_SECRET` | ✅ Yes | Flask session encryption key (64 chars) | `a1b2c3d4e5f6...` |
| `OWNER_ID` | ⚠️ Recommended | Your Telegram user ID (enables admin features) | `123456789` |
| `WEBHOOK_URL` | ❌ Optional | Full webhook URL (triggers webhook mode) | `https://yourapp.com/webhook` |
| `RENDER_URL` | ❌ Optional | Render-specific webhook URL | `https://app.onrender.com/webhook` |
| `WIFU_ID` | ❌ Optional | Secondary admin user ID | `987654321` |
| `PORT` | ❌ Optional | Web server port (default: 5000) | `5000` |
| `DATABASE_PATH` | ❌ Optional | Custom database location | `data/quiz_bot.db` |

### .env File Example

```env
# Required Variables
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
SESSION_SECRET=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2

# Recommended (Enables Admin Features)
OWNER_ID=123456789

# Optional - Deployment Mode Configuration
# Leave empty for polling mode (Replit, VPS, local)
# Set for webhook mode (Render, Railway, Heroku)
# WEBHOOK_URL=https://your-app.railway.app/webhook
# RENDER_URL=https://your-app.onrender.com/webhook

# Optional - Additional Configuration
# WIFU_ID=987654321
# PORT=5000
# DATABASE_PATH=data/quiz_bot.db
```

### Mode Auto-Detection

The bot automatically selects the appropriate mode:

- **Polling Mode:** Used when `WEBHOOK_URL` and `RENDER_URL` are **not set**
  - Best for: Replit, VPS, local development
  - Command: `python main.py`

- **Webhook Mode:** Used when `WEBHOOK_URL` or `RENDER_URL` **is set**
  - Best for: Render, Railway, Heroku, cloud platforms
  - Command: `gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT`

---

## 📖 Usage

### Getting Started

1. **Find Your Bot** - Search for your bot's username on Telegram
2. **Start Chatting** - Send `/start` to initialize
3. **Take a Quiz** - Use `/quiz` to get your first question
4. **Check Stats** - Use `/mystats` to see your performance

### In Groups

1. **Add Bot to Group** - Add bot as member to any group
2. **Make Bot Admin** (optional) - For enhanced features like auto-scheduling
3. **Start Quiz** - Any member can use `/quiz` to trigger a quiz
4. **Automated Quizzes** - Bot sends quizzes every 30 minutes (if admin)

### Admin Panel

Access the web interface at `/admin`:

1. **Add Questions**
   - Click "Add New Question"
   - Enter question text, options, and correct answer
   - Optional: Set category

2. **Edit Questions**
   - Click edit icon on any question
   - Modify text, options, or correct answer
   - Save changes

3. **Delete Questions**
   - Click delete icon
   - Confirm deletion

4. **REST API Access**
   - `GET /api/questions` - List all questions
   - `POST /api/questions` - Add new question
   - `PUT /api/questions/<id>` - Update question
   - `DELETE /api/questions/<id>` - Remove question

---

## 🎮 Commands

### User Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Begin your quiz journey and see welcome message | `/start` |
| `/help` | View all available commands and usage guide | `/help` |
| `/quiz` | Get a random quiz question | `/quiz` |
| `/category` | Browse and select quiz categories | `/category` |
| `/mystats` | View your personal statistics and performance | `/mystats` |
| `/ping` | Check bot responsiveness and uptime | `/ping` |

**Example Usage:**
```
User: /start
Bot: 🎯 Welcome to Quiz Bot! Test your knowledge with fun quizzes.

User: /quiz
Bot: [Sends interactive quiz poll]

User: /mystats
Bot: 📊 Your Statistics
     Quizzes Taken: 15
     Correct: 12 (80%)
     Streak: 3 days
```

### Developer Commands (Owner Only)

| Command | Description | Usage |
|---------|-------------|-------|
| `/addquiz` | Add new quiz questions | `/addquiz Question? / Option1 / Option2 / Option3 / Option4 / correct_index` |
| `/editquiz` | View and edit existing quizzes | `/editquiz` |
| `/delquiz` | Delete quiz questions | `/delquiz [quiz_id]` or reply to quiz |
| `/delquiz_confirm` | Confirm quiz deletion | `/delquiz_confirm` |
| `/totalquiz` | View total number of quizzes | `/totalquiz` |
| `/stats` | View comprehensive bot statistics | `/stats` |
| `/dev` | Developer dashboard with system info | `/dev` |
| `/broadcast` | Send announcements to all users/groups | `/broadcast Your message here` |
| `/broadcast_confirm` | Confirm and send broadcast | `/broadcast_confirm` |
| `/delbroadcast` | Delete the last broadcast | `/delbroadcast` |
| `/delbroadcast_confirm` | Confirm broadcast deletion | `/delbroadcast_confirm` |

**Example Usage:**
```
Developer: /stats
Bot: 📊 Bot Statistics
     Total Users: 1,234
     Active Groups: 56
     Quizzes Sent Today: 234
     Database Size: 2.3 MB
     Uptime: 5d 12h 34m

Developer: /broadcast 🎉 New features coming soon!
Bot: Preview: "🎉 New features coming soon!"
     Will send to 1,234 users and 56 groups.
     Confirm: /broadcast_confirm

Developer: /broadcast_confirm
Bot: ✅ Broadcast sent successfully!
     Delivered: 1,180 / 1,234 users
     Failed: 54 (users blocked bot)
```

### Advanced Features

**Broadcast with Inline Buttons:**
```
/broadcast Your message here [["Button Text","https://example.com"]]
```

**Quiz Categories:**
```
/category
Bot: Select a category:
     • General Knowledge
     • Science
     • History
     • Technology
```

---

## 🛠️ Development

### Project Structure

```
telegram-quiz-bot/
├── main.py                     # Universal entry point (polling/webhook)
├── src/
│   ├── core/                   # Core business logic
│   │   ├── config.py           # Configuration management
│   │   ├── database.py         # Database operations
│   │   ├── quiz.py             # Quiz logic and scoring
│   │   └── exceptions.py       # Custom exceptions
│   ├── bot/                    # Telegram bot
│   │   ├── handlers.py         # User command handlers
│   │   └── dev_commands.py     # Admin/developer commands
│   └── web/                    # Web interface
│       ├── app.py              # Flask application
│       └── wsgi.py             # WSGI entry point (production)
├── templates/
│   └── admin.html              # Admin panel HTML
├── static/
│   └── js/
│       └── admin.js            # Admin panel JavaScript
├── data/                       # Persistent data
│   ├── quiz_bot.db             # SQLite database (auto-created)
│   ├── questions.json          # Quiz questions backup
│   └── *.json                  # Other data files
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Docker configuration
├── docker-compose.yml          # Docker Compose setup
├── Procfile                    # Heroku/Render config
└── .env.example                # Environment template
```

### Adding New Features

#### 1. Add a New Command

Edit `src/bot/handlers.py`:

```python
async def my_new_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /mynewcommand"""
    await update.message.reply_text("Hello from new command!")

# Register in initialize() method:
self.application.add_handler(CommandHandler("mynewcommand", self.my_new_command))
```

#### 2. Add Developer Command

Edit `src/bot/dev_commands.py`:

```python
async def my_admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only command"""
    if not await self.check_access(update):
        await self.send_unauthorized_message(update)
        return
    
    # Your admin logic here
    await update.message.reply_text("Admin command executed!")
```

#### 3. Add Database Table

Edit `src/core/database.py`:

```python
def create_tables(self):
    """Create database tables"""
    self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS my_new_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    self.conn.commit()
```

#### 4. Add API Endpoint

Edit `src/web/app.py`:

```python
@app.route('/api/my-endpoint', methods=['GET'])
def my_endpoint():
    """Custom API endpoint"""
    data = {"message": "Hello from API"}
    return jsonify(data)
```

### Testing Locally

1. **Set up development environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure test bot**
   - Create a separate test bot via @BotFather
   - Use test bot token in `.env`

3. **Run in development mode**
   ```bash
   python main.py
   ```

4. **Test commands**
   - Message your test bot on Telegram
   - Check `bot.log` for detailed logs
   - Monitor console output

5. **Test admin panel**
   - Open `http://localhost:5000/admin`
   - Add/edit/delete test questions
   - Check database changes in `data/quiz_bot.db`

### Code Style

- Follow **PEP 8** style guide
- Use **async/await** for Telegram API calls
- Add **docstrings** to functions
- Include **error handling** with try/except
- Log important events with `logger.info()` or `logger.error()`

### Database Access

```python
from src.core.database import DatabaseManager

db = DatabaseManager()

# Query users
users = db.get_all_users()

# Add activity log
db.log_activity(
    activity_type='command',
    user_id=user_id,
    command='/mycommand',
    success=True
)
```

### Performance Monitoring

The bot includes built-in performance tracking:

- **Memory Usage:** Tracked every 5 minutes
- **API Calls:** Logged for rate limiting analysis
- **Response Times:** Measured for all commands
- **Error Rates:** Tracked by error type

Access via `/dev` command or query `performance_metrics` table.

---

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### Getting Started

1. **Fork the repository**
   ```bash
   git clone https://github.com/yourusername/telegram-quiz-bot.git
   cd telegram-quiz-bot
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make your changes**
   - Follow code style guidelines
   - Add tests if applicable
   - Update documentation

4. **Commit your changes**
   ```bash
   git commit -m "Add amazing feature"
   ```

5. **Push to branch**
   ```bash
   git push origin feature/amazing-feature
   ```

6. **Open a Pull Request**
   - Describe your changes clearly
   - Link related issues
   - Wait for review

### Contribution Guidelines

- **Code Quality:** Follow PEP 8, add docstrings, handle errors
- **Testing:** Test on both Telegram (PM and groups) and admin panel
- **Documentation:** Update README if adding features
- **Commits:** Write clear, descriptive commit messages
- **Pull Requests:** One feature per PR, include description

### Areas for Contribution

- 🐛 Bug fixes and issue resolution
- ✨ New quiz categories and question types
- 🎨 UI/UX improvements for admin panel
- 📚 Documentation improvements and translations
- 🚀 Performance optimizations
- 🧪 Test coverage expansion
- 🌐 Multi-language support

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## 📄 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

### What This Means

✅ You can use this project commercially  
✅ You can modify the code  
✅ You can distribute it  
✅ You can use it privately  

⚠️ Include the original license and copyright notice  
⚠️ No warranty provided

---

## 🛡️ Security

- ✅ Never commit `.env` file (already in `.gitignore`)
- ✅ Never share your `TELEGRAM_TOKEN` publicly
- ✅ Regenerate `SESSION_SECRET` for each deployment
- ✅ Use environment variables on cloud platforms
- ✅ Keep `OWNER_ID` private
- ✅ Regularly update dependencies: `pip install -r requirements.txt --upgrade`

---

## 🐛 Troubleshooting

### Bot Not Responding

1. **Check logs** for errors (`bot.log` or platform-specific logs)
2. **Verify token** - Test with `/start` on Telegram
3. **Check mode** - Look for "POLLING mode" or "WEBHOOK mode" in logs
4. **Test health endpoint** - Visit `https://yourapp.com/` (should return `{"status":"ok"}`)

### Webhook Issues (Render/Heroku/Railway)

- Ensure `WEBHOOK_URL` is `https://` and ends with `/webhook`
- Check webhook status: `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`
- Verify start command: `gunicorn src.web.wsgi:app --bind 0.0.0.0:$PORT`

### Polling Issues (Replit/VPS)

- Only one instance can poll at a time - kill duplicates
- Check internet connection: `ping telegram.org`
- Verify no webhook is active: Bot should delete it automatically

### Database Issues

- **Locked:** Stop all bot instances, check file permissions
- **Corrupted:** Delete `data/quiz_bot.db` (auto-recreates on restart)
- **Missing questions:** Check `data/questions.json` exists

---

## 🙏 Acknowledgments

Built with these amazing open-source projects:

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram Bot API wrapper
- [Flask](https://flask.palletsprojects.com/) - Web framework
- [APScheduler](https://apscheduler.readthedocs.io/) - Task scheduling
- [Gunicorn](https://gunicorn.org/) - WSGI HTTP Server
- [SQLite](https://www.sqlite.org/) - Embedded database

---

## 💬 Support

Need help? Here's how to get support:

1. **Check Documentation** - Review this README and troubleshooting section
2. **Search Issues** - Look for similar problems in GitHub Issues
3. **Check Logs** - Review `bot.log` or platform logs for errors
4. **Open an Issue** - [GitHub Issues](https://github.com/yourusername/telegram-quiz-bot/issues)
5. **Community** - Join discussions and share experiences

When reporting issues, please include:
- Platform (Replit/Render/VPS/etc.)
- Python version
- Error messages from logs
- Steps to reproduce

---

## 🌟 Features Roadmap

Planned features for future releases:

- [ ] Multi-language support (i18n)
- [ ] Custom quiz timers
- [ ] Quiz difficulty levels
- [ ] Export statistics to CSV
- [ ] Integration with Google Sheets
- [ ] Quiz analytics dashboard
- [ ] User badges and achievements
- [ ] Quiz scheduling per group

---

**Made with ❤️ for the Telegram community**

*Deploy once, run anywhere! 🚀*

---

### Quick Links

- [Report Bug](https://github.com/yourusername/telegram-quiz-bot/issues)
- [Request Feature](https://github.com/yourusername/telegram-quiz-bot/issues)
- [View Documentation](https://github.com/yourusername/telegram-quiz-bot/wiki)
- [Join Community](https://github.com/yourusername/telegram-quiz-bot/discussions)

If this project helped you, please consider giving it a ⭐️ on GitHub!
