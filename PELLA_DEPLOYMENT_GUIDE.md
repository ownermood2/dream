# 🚀 Pella Deployment Guide - Quiz Bot with 98 Questions

## ✅ What You Have Now

- ✅ **98 quiz questions** exported from Replit PostgreSQL
- ✅ **Import script** ready for Pella SQLite database
- ✅ **Production-ready bot** with Waitress WSGI server
- ✅ **Smart database fallback** for read-only filesystems
- ✅ **Bulletproof conflict recovery** - Zero "Conflict: terminated by other getUpdates" errors
- ✅ **Auto-detection** - Automatically selects polling mode on Pella

---

## 📦 Step 1: Upload Files to Pella

Upload these 2 files to your Pella deployment root directory:

1. **`questions_export.json`** - All 98 quiz questions
2. **`import_questions_to_pella.py`** - Import script

You can download them from this Replit project, or upload via Pella dashboard.

---

## 🔧 Step 2: Set Environment Variables on Pella

Go to Pella Dashboard → Environment Variables:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
SESSION_SECRET=your_random_secret_key_here
OWNER_ID=8376823449
WIFU_ID=7970305771
```

**Important Notes:**
- ✅ Don't set `DATABASE_URL` - Pella will use SQLite automatically
- ✅ Don't set `MODE` - Auto-detects polling mode (no webhook)
- ✅ Don't set `HOST` - Defaults to 0.0.0.0 automatically

---

## 🚀 Step 3: Deploy & Import Questions

### Option A: Manual Import (Recommended)

1. **Deploy your bot** first with start command:
   ```bash
   python main.py
   ```

2. **SSH into Pella** or use their console, then run:
   ```bash
   python3 import_questions_to_pella.py
   ```

3. **Restart your bot** - Questions are now loaded!

### Option B: Automatic Import on Startup

Add this to your start command in Pella:
```bash
python3 import_questions_to_pella.py && python main.py
```

This will import questions every time the bot starts.

---

## ✅ Step 4: Verify Everything Works

After deployment, send these commands to your bot on Telegram:

1. **`/start`** - Check if bot responds
2. **`/quiz`** - Get a quiz question (should work now!)
3. **`/totalquiz`** (developer command) - Should show 98 questions

---

## 📊 Expected Output

When you run the import script, you should see:

```
📁 Using database: /app/data/quiz_bot.db
🗑️  Cleared existing questions

✅ Import Complete!
   📊 Total questions in database: 98
   ✅ Successfully imported: 98

📝 Sample questions:
   1. The Tropic of Cancer passes through which of the following I...
   2. Which is the smallest continent in the world?...
   3. The longest river in the world is?...
   4. Which country has the largest population?...
   5. The Great Barrier Reef is located in which country?...
```

---

## 🔍 Troubleshooting

### Issue: "questions_export.json not found"
**Solution:** Make sure you uploaded `questions_export.json` to the same directory as the script.

### Issue: "Permission denied" for /app/data/
**Solution:** The script automatically falls back to `/tmp/quiz_bot.db` - this is normal and expected on Pella.

### Issue: Bot shows "0 questions loaded"
**Solution:** Run the import script first, then restart the bot.

### Issue: Bot shows "Conflict: terminated by other getUpdates"
**Solution:** The new 3-tier conflict recovery system automatically handles this:
- Cleans webhooks at startup (3 retries)
- Detects conflicts during initialization and retries
- Catches runtime conflicts and auto-recovers
- No manual intervention needed!

---

## 🎯 What Happens After Import

✅ **Auto Quiz System** - Sends quizzes every 30 minutes to groups  
✅ **User Commands** - `/quiz`, `/mystats`, `/leaderboard`, `/help`  
✅ **Developer Commands** - `/addquiz`, `/editquiz`, `/broadcast`, `/dev`  
✅ **Rate Limiting** - Prevents spam  
✅ **Leaderboard** - Cached for performance  
✅ **Stats Tracking** - All user interactions logged  

---

## 📝 Important Notes

1. **Database Location:**
   - Primary: `/app/data/quiz_bot.db`
   - Fallback: `/tmp/quiz_bot.db` (on read-only filesystems)
   - The bot automatically chooses the right path

2. **No Conflicts:**
   - Replit bot is now stopped
   - Only Pella bot will run
   - No more `getUpdates` conflicts

3. **Questions Persistence:**
   - Questions are stored in SQLite database
   - Survives bot restarts
   - No need to re-import unless you clear the database

---

## 🎉 Success Checklist

- ✅ Files uploaded to Pella
- ✅ Environment variables set
- ✅ Import script executed successfully
- ✅ Bot responds to `/start`
- ✅ Bot sends quiz questions with `/quiz`
- ✅ `/totalquiz` shows 98 questions
- ✅ No conflict errors in logs

---

**Your bot is now production-ready on Pella with all 98 quiz questions! 🎊**
