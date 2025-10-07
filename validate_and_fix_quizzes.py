#!/usr/bin/env python3
"""Quiz Validation and Auto-Correction System

This standalone script validates all quiz questions in the database and 
auto-corrects any incorrect answer indices. It checks for common issues like
off-by-one errors (1-4 instead of 0-3) and ensures data integrity.

Usage:
    python validate_and_fix_quizzes.py              # Dry-run mode (default)
    python validate_and_fix_quizzes.py --fix        # Apply corrections
    python validate_and_fix_quizzes.py --fix --yes  # Skip confirmation
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from collections import Counter

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("Error: psycopg2 is not installed. Install it with: pip install psycopg2-binary")
    sys.exit(1)


class QuizValidator:
    """Validates and corrects quiz questions in the database."""
    
    def __init__(self, database_url: str):
        """Initialize validator with database connection.
        
        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.conn = None
        self.issues = []
        self.corrections = []
        self.stats = {
            'total': 0,
            'valid': 0,
            'corrected': 0,
            'flagged': 0,
            'invalid_range': 0,
            'off_by_one': 0,
            'null_answers': 0
        }
    
    def connect(self):
        """Establish database connection."""
        try:
            self.conn = psycopg2.connect(self.database_url)
            print("✅ Connected to PostgreSQL database")
            return True
        except Exception as e:
            print(f"❌ Failed to connect to database: {e}")
            return False
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            print("🔌 Database connection closed")
    
    def get_all_questions(self) -> List[Dict]:
        """Query all questions from the database.
        
        Returns:
            List of question dictionaries
        """
        try:
            cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute("""
                SELECT id, question, options, correct_answer, 
                       created_at, updated_at
                FROM questions
                ORDER BY id
            """)
            questions = cursor.fetchall()
            cursor.close()
            print(f"📊 Retrieved {len(questions)} questions from database")
            return questions
        except Exception as e:
            print(f"❌ Failed to retrieve questions: {e}")
            return []
    
    def validate_question(self, question: Dict) -> Tuple[bool, Optional[str], Optional[int]]:
        """Validate a single question.
        
        Args:
            question: Question dictionary with id, question, options, correct_answer
        
        Returns:
            Tuple of (is_valid, issue_description, suggested_correction)
        """
        q_id = question['id']
        correct_answer = question['correct_answer']
        
        try:
            options = json.loads(question['options']) if isinstance(question['options'], str) else question['options']
        except json.JSONDecodeError:
            return False, "Invalid JSON in options field", None
        
        if not isinstance(options, list):
            return False, "Options is not a list", None
        
        if len(options) != 4:
            return False, f"Expected 4 options, found {len(options)}", None
        
        if correct_answer is None:
            self.stats['null_answers'] += 1
            return False, "correct_answer is NULL", None
        
        if not isinstance(correct_answer, int):
            return False, f"correct_answer is not an integer: {type(correct_answer).__name__}", None
        
        if 0 <= correct_answer <= 3:
            return True, None, None
        
        if 1 <= correct_answer <= 4:
            self.stats['off_by_one'] += 1
            suggested = correct_answer - 1
            return False, f"Off-by-one error: answer is {correct_answer} (should be 0-3)", suggested
        
        self.stats['invalid_range'] += 1
        return False, f"correct_answer {correct_answer} is outside valid range (0-3)", None
    
    def detect_patterns(self, questions: List[Dict]):
        """Detect suspicious patterns in the questions.
        
        Args:
            questions: List of all questions
        """
        if not questions:
            return
        
        print("\n🔍 Analyzing patterns...")
        
        answer_distribution = Counter(q['correct_answer'] for q in questions if q['correct_answer'] is not None)
        
        print(f"\n📈 Answer Distribution:")
        for answer_idx in sorted(answer_distribution.keys()):
            count = answer_distribution[answer_idx]
            percentage = (count / len(questions)) * 100
            bar = "█" * int(percentage / 2)
            print(f"  Answer {answer_idx}: {count:4d} ({percentage:5.1f}%) {bar}")
        
        if answer_distribution:
            max_answer = max(answer_distribution, key=answer_distribution.get)
            max_count = answer_distribution[max_answer]
            if max_count > len(questions) * 0.5:
                print(f"\n⚠️  WARNING: {(max_count/len(questions)*100):.1f}% of questions have answer={max_answer}")
                print(f"   This might indicate a systematic issue or bias in the questions")
        
        answers_outside_range = [q for q in questions if q['correct_answer'] not in [0, 1, 2, 3] and q['correct_answer'] is not None]
        if answers_outside_range:
            print(f"\n⚠️  WARNING: {len(answers_outside_range)} questions have answers outside range 0-3")
            if all(1 <= q['correct_answer'] <= 4 for q in answers_outside_range):
                print(f"   → All out-of-range answers are 1-4, suggesting off-by-one error pattern")
    
    def validate_all(self, questions: List[Dict]):
        """Validate all questions and collect issues.
        
        Args:
            questions: List of all questions
        """
        print(f"\n🔎 Validating {len(questions)} questions...")
        
        self.stats['total'] = len(questions)
        
        for question in questions:
            is_valid, issue, correction = self.validate_question(question)
            
            if is_valid:
                self.stats['valid'] += 1
            else:
                self.stats['flagged'] += 1
                issue_record = {
                    'id': question['id'],
                    'question': question['question'][:80] + '...' if len(question['question']) > 80 else question['question'],
                    'current_answer': question['correct_answer'],
                    'issue': issue,
                    'suggested_correction': correction
                }
                self.issues.append(issue_record)
                
                if correction is not None:
                    self.corrections.append({
                        'id': question['id'],
                        'old_value': question['correct_answer'],
                        'new_value': correction
                    })
    
    def create_backup(self) -> bool:
        """Create a backup of the questions table.
        
        Returns:
            True if backup successful, False otherwise
        """
        try:
            cursor = self.conn.cursor()
            
            cursor.execute("DROP TABLE IF EXISTS questions_backup")
            
            cursor.execute("""
                CREATE TABLE questions_backup AS 
                SELECT * FROM questions
            """)
            
            cursor.execute("SELECT COUNT(*) FROM questions_backup")
            backup_count = cursor.fetchone()[0]
            
            self.conn.commit()
            cursor.close()
            
            print(f"💾 Backup created: {backup_count} questions saved to 'questions_backup' table")
            return True
            
        except Exception as e:
            print(f"❌ Failed to create backup: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def apply_corrections(self) -> bool:
        """Apply all corrections to the database.
        
        Returns:
            True if all corrections applied successfully, False otherwise
        """
        if not self.corrections:
            print("ℹ️  No corrections to apply")
            return True
        
        try:
            cursor = self.conn.cursor()
            
            print(f"\n🔧 Applying {len(self.corrections)} corrections...")
            
            for correction in self.corrections:
                cursor.execute("""
                    UPDATE questions 
                    SET correct_answer = %s, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (correction['new_value'], correction['id']))
                
                print(f"  ✓ Question {correction['id']}: {correction['old_value']} → {correction['new_value']}")
            
            self.conn.commit()
            cursor.close()
            
            self.stats['corrected'] = len(self.corrections)
            print(f"\n✅ Successfully applied {len(self.corrections)} corrections")
            return True
            
        except Exception as e:
            print(f"❌ Failed to apply corrections: {e}")
            if self.conn:
                self.conn.rollback()
            return False
    
    def generate_report(self) -> str:
        """Generate detailed validation report.
        
        Returns:
            Report text as string
        """
        report_lines = [
            "=" * 80,
            "QUIZ VALIDATION REPORT",
            "=" * 80,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "SUMMARY STATISTICS",
            "-" * 80,
            f"Total questions checked:     {self.stats['total']:6d}",
            f"Valid questions:             {self.stats['valid']:6d} ({self.stats['valid']/max(self.stats['total'],1)*100:5.1f}%)",
            f"Questions with issues:       {self.stats['flagged']:6d} ({self.stats['flagged']/max(self.stats['total'],1)*100:5.1f}%)",
            f"Corrections applied:         {self.stats['corrected']:6d}",
            "",
            "ISSUE BREAKDOWN",
            "-" * 80,
            f"Off-by-one errors (1-4):     {self.stats['off_by_one']:6d}",
            f"Out of range (other):        {self.stats['invalid_range']:6d}",
            f"NULL answers:                {self.stats['null_answers']:6d}",
            "",
        ]
        
        if self.issues:
            report_lines.extend([
                "DETAILED ISSUES",
                "-" * 80,
            ])
            
            for issue in self.issues:
                report_lines.append(f"\nQuestion ID: {issue['id']}")
                report_lines.append(f"Question: {issue['question']}")
                report_lines.append(f"Current Answer: {issue['current_answer']}")
                report_lines.append(f"Issue: {issue['issue']}")
                if issue['suggested_correction'] is not None:
                    report_lines.append(f"Suggested Correction: {issue['suggested_correction']}")
        
        if self.corrections:
            report_lines.extend([
                "",
                "CORRECTIONS APPLIED",
                "-" * 80,
            ])
            
            for correction in self.corrections:
                report_lines.append(
                    f"Question {correction['id']:4d}: "
                    f"{correction['old_value']} → {correction['new_value']}"
                )
        
        report_lines.extend([
            "",
            "=" * 80,
            "END OF REPORT",
            "=" * 80,
        ])
        
        return "\n".join(report_lines)
    
    def print_summary(self):
        """Print summary to console."""
        print(f"\n{'=' * 80}")
        print("VALIDATION SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total questions:      {self.stats['total']:6d}")
        print(f"Valid questions:      {self.stats['valid']:6d} ({self.stats['valid']/max(self.stats['total'],1)*100:5.1f}%)")
        print(f"Issues found:         {self.stats['flagged']:6d} ({self.stats['flagged']/max(self.stats['total'],1)*100:5.1f}%)")
        print(f"Corrections applied:  {self.stats['corrected']:6d}")
        print(f"{'=' * 80}")


def main():
    """Main entry point for the validation script."""
    parser = argparse.ArgumentParser(
        description='Validate and auto-correct quiz questions in the database'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='Apply corrections (default is dry-run mode)'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    args = parser.parse_args()
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("❌ Error: DATABASE_URL environment variable not set")
        sys.exit(1)
    
    print("🚀 Quiz Validation and Auto-Correction System")
    print(f"Mode: {'FIX' if args.fix else 'DRY-RUN'}")
    print(f"{'=' * 80}\n")
    
    validator = QuizValidator(database_url)
    
    if not validator.connect():
        sys.exit(1)
    
    try:
        questions = validator.get_all_questions()
        
        if not questions:
            print("ℹ️  No questions found in database")
            validator.close()
            return
        
        validator.detect_patterns(questions)
        
        validator.validate_all(questions)
        
        validator.print_summary()
        
        if validator.issues:
            print(f"\n⚠️  Found {len(validator.issues)} questions with issues:")
            print(f"\n{'ID':<6} {'Current':<10} {'Issue':<50} {'Fix':<10}")
            print("-" * 80)
            for issue in validator.issues[:10]:
                fix_str = str(issue['suggested_correction']) if issue['suggested_correction'] is not None else 'MANUAL'
                print(f"{issue['id']:<6} {str(issue['current_answer']):<10} {issue['issue'][:48]:<50} {fix_str:<10}")
            
            if len(validator.issues) > 10:
                print(f"... and {len(validator.issues) - 10} more (see report file for full details)")
        
        if args.fix:
            if validator.corrections:
                print(f"\n⚠️  WARNING: About to modify {len(validator.corrections)} questions in the database")
                
                if not args.yes:
                    response = input("\nCreate backup and apply corrections? [y/N]: ")
                    if response.lower() != 'y':
                        print("❌ Corrections cancelled by user")
                        validator.close()
                        return
                
                if validator.create_backup():
                    validator.apply_corrections()
                else:
                    print("❌ Corrections aborted due to backup failure")
            else:
                print("\n✅ No corrections needed - all questions are valid!")
        else:
            print("\n💡 Running in DRY-RUN mode - no changes made to database")
            if validator.corrections:
                print(f"   Run with --fix to apply {len(validator.corrections)} corrections")
        
        report = validator.generate_report()
        report_file = 'quiz_validation_report.txt'
        with open(report_file, 'w') as f:
            f.write(report)
        print(f"\n📄 Detailed report saved to: {report_file}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        validator.close()


if __name__ == "__main__":
    main()
