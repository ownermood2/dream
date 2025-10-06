#!/usr/bin/env python3
"""
Quiz Questions Import Script for Pella Deployment
=================================================
This script imports questions from questions_export.json into SQLite database.
Automatically handles read-only filesystems by falling back to /tmp/.

Usage on Pella:
1. Upload this script and questions_export.json to your Pella deployment
2. Run: python3 import_questions_to_pella.py
"""

import json
import sqlite3
import os
from datetime import datetime

def test_database_writable(db_path):
    """Test if database path is writable, returns True if successful"""
    conn = None
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("BEGIN")
        conn.commit()
        return True
    except (sqlite3.OperationalError, OSError, PermissionError):
        return False
    finally:
        if conn:
            conn.close()

def import_questions_to_database(db_path):
    """Import questions from JSON to the specified database path"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                correct_answer INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                category TEXT
            )
        ''')
        conn.commit()
        
        with open('questions_export.json', 'r', encoding='utf-8') as f:
            questions = json.load(f)
        
        cur.execute("DELETE FROM questions")
        conn.commit()
        print(f"🗑️  Cleared existing questions")
        
        imported = 0
        skipped = 0
        
        for q in questions:
            try:
                options = q['options']
                if isinstance(options, list):
                    options = json.dumps(options)
                
                cur.execute('''
                    INSERT INTO questions (question, options, correct_answer, category, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    q['question'],
                    options,
                    q['correct_answer'],
                    q.get('category', ''),
                    datetime.now(),
                    datetime.now()
                ))
                imported += 1
            except Exception as e:
                print(f"❌ Failed to import question {q.get('id')}: {e}")
                skipped += 1
        
        conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM questions")
        total = cur.fetchone()[0]
        
        print(f"\n✅ Import Complete!")
        print(f"   📊 Total questions in database: {total}")
        print(f"   ✅ Successfully imported: {imported}")
        if skipped > 0:
            print(f"   ⚠️  Skipped (errors): {skipped}")
        
        print(f"\n📝 Sample questions:")
        cur.execute("SELECT id, question FROM questions LIMIT 5")
        for row in cur.fetchall():
            print(f"   {row[0]}. {row[1][:60]}...")
        
    finally:
        cur.close()
        conn.close()

def import_questions():
    """Import questions from JSON to SQLite database with automatic fallback"""
    
    primary_path = os.environ.get('DB_PATH', '/app/data/quiz_bot.db')
    fallback_path = '/tmp/quiz_bot.db'
    
    print(f"📁 Attempting to use database: {primary_path}")
    
    if test_database_writable(primary_path):
        print(f"✅ Using primary database: {primary_path}")
        import_questions_to_database(primary_path)
    else:
        print(f"⚠️  Primary path not writable (read-only filesystem)")
        print(f"💾 Falling back to: {fallback_path}")
        
        if test_database_writable(fallback_path):
            print(f"✅ Using fallback database: {fallback_path}")
            import_questions_to_database(fallback_path)
        else:
            raise Exception(f"Failed to write to both primary and fallback databases")

if __name__ == "__main__":
    try:
        import_questions()
    except FileNotFoundError:
        print("❌ Error: questions_export.json not found!")
        print("   Make sure to upload questions_export.json to the same directory.")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        raise
