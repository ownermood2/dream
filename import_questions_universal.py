#!/usr/bin/env python3
"""
Universal Quiz Questions Import Script
======================================
This script imports questions from questions_export.json to either PostgreSQL or SQLite.
Automatically detects DATABASE_URL and uses appropriate database.

Usage:
1. Make sure DATABASE_URL is set (for PostgreSQL) or leave empty (for SQLite)
2. Run: python3 import_questions_universal.py
"""

import json
import os
from datetime import datetime

# Try to import both database libraries
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

import sqlite3

def import_to_postgresql(database_url):
    """Import questions to PostgreSQL database"""
    print(f"🐘 Using PostgreSQL database")
    
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    
    try:
        # Load questions from JSON
        with open('questions_export.json', 'r', encoding='utf-8') as f:
            questions = json.load(f)
        
        # Clear existing questions
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
                    VALUES (%s, %s, %s, %s, %s, %s)
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

def import_to_sqlite(db_path):
    """Import questions to SQLite database"""
    print(f"📁 Using SQLite database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    try:
        # Load questions from JSON
        with open('questions_export.json', 'r', encoding='utf-8') as f:
            questions = json.load(f)
        
        # Clear existing questions
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
    """Import questions with automatic database detection"""
    
    # Check for DATABASE_URL (PostgreSQL)
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url and database_url.startswith('postgresql://'):
        if not PSYCOPG2_AVAILABLE:
            raise Exception("PostgreSQL database URL found but psycopg2 is not installed!")
        import_to_postgresql(database_url)
    else:
        # Use SQLite with fallback logic
        primary_path = os.environ.get('DB_PATH', '/app/data/quiz_bot.db')
        fallback_path = '/tmp/quiz_bot.db'
        
        # Try primary path first
        try:
            os.makedirs(os.path.dirname(primary_path), exist_ok=True)
            import_to_sqlite(primary_path)
        except (OSError, PermissionError):
            print(f"⚠️  Primary path not writable, using fallback: {fallback_path}")
            import_to_sqlite(fallback_path)

if __name__ == "__main__":
    try:
        import_questions()
    except FileNotFoundError:
        print("❌ Error: questions_export.json not found!")
        print("   Make sure to upload questions_export.json to the same directory.")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        raise
