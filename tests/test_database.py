"""Database Layer Tests for MissQuiz Telegram Quiz Bot.

This module tests all database operations including:
- Schema creation and migrations
- Question CRUD operations
- User statistics and leaderboard
- Developer access management
- Quiz attempts and history
- Metrics and analytics
"""

import pytest
from datetime import datetime, timedelta
from src.core.database import DatabaseManager
from src.core.exceptions import DatabaseError


class TestDatabaseSchema:
    """Test database schema creation and initialization."""
    
    def test_create_tables(self, test_db):
        """Test database schema creation."""
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            
            tables = [
                'questions', 'users', 'groups', 'quiz_attempts',
                'developers', 'broadcasts', 'activity_logs',
                'performance_metrics'
            ]
            
            for table in tables:
                if test_db.db_type == 'postgresql':
                    cursor.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                        (table,)
                    )
                else:
                    cursor.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)
                    )
                result = cursor.fetchone()
                assert result is not None, f"Table {table} should exist"
    
    def test_database_initialization(self, test_db):
        """Test database is properly initialized."""
        assert test_db is not None
        assert test_db.db_path is not None or test_db.database_url is not None


class TestQuestionOperations:
    """Test question CRUD operations."""
    
    def test_add_question(self, test_db):
        """Test adding a quiz question."""
        question_id = test_db.add_question(
            question="What is 2+2?",
            options=["3", "4", "5", "6"],
            correct_answer=1,
            category="Math",
            difficulty="easy"
        )
        
        assert question_id > 0
        question = test_db.get_question_by_id(question_id)
        assert question is not None
        assert question['question'] == "What is 2+2?"
        assert question['correct_answer'] == 1
    
    def test_get_all_questions(self, test_db):
        """Test retrieving all questions."""
        test_db.add_question("Q1", ["A", "B", "C", "D"], 0, "Test", "easy")
        test_db.add_question("Q2", ["A", "B", "C", "D"], 1, "Test", "medium")
        
        questions = test_db.get_all_questions()
        assert len(questions) >= 2
        assert all('question' in q for q in questions)
    
    def test_get_question_by_id(self, test_db):
        """Test getting specific question by ID."""
        q_id = test_db.add_question(
            "Test Question",
            ["A", "B", "C", "D"],
            2,
            "General",
            "hard"
        )
        
        question = test_db.get_question_by_id(q_id)
        assert question is not None
        assert question['question'] == "Test Question"
        assert question['correct_answer'] == 2
        assert question['difficulty'] == "hard"
    
    def test_update_question(self, test_db):
        """Test updating question fields."""
        q_id = test_db.add_question(
            "Original Question",
            ["A", "B", "C", "D"],
            0,
            "Test",
            "easy"
        )
        
        test_db.update_question(
            q_id,
            question="Updated Question",
            difficulty="medium"
        )
        
        updated = test_db.get_question_by_id(q_id)
        assert updated['question'] == "Updated Question"
        assert updated['difficulty'] == "medium"
    
    def test_delete_question(self, test_db):
        """Test question deletion with cascade."""
        q_id = test_db.add_question(
            "To Delete",
            ["A", "B", "C", "D"],
            1,
            "Test",
            "easy"
        )
        
        test_db.delete_question(q_id)
        
        deleted = test_db.get_question_by_id(q_id)
        assert deleted is None
    
    def test_get_questions_by_category(self, test_db):
        """Test filtering questions by category."""
        test_db.add_question("Math Q1", ["1", "2", "3", "4"], 0, "Math", "easy")
        test_db.add_question("Math Q2", ["1", "2", "3", "4"], 1, "Math", "medium")
        test_db.add_question("Science Q1", ["A", "B", "C", "D"], 2, "Science", "hard")
        
        math_questions = test_db.get_questions_by_category("Math")
        assert len(math_questions) >= 2
        assert all(q['category'] == "Math" for q in math_questions)


class TestUserOperations:
    """Test user-related database operations."""
    
    def test_add_or_update_user(self, test_db):
        """Test adding and updating users."""
        user_id = 123456789
        
        test_db.add_or_update_user(user_id, "testuser", "Test", "User")
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = test_db._get_placeholder()
            cursor.execute(
                f"SELECT * FROM users WHERE user_id = {placeholder}",
                (user_id,)
            )
            user = cursor.fetchone()
            
            assert user is not None
            if test_db.db_type == 'postgresql':
                assert user[1] == "testuser"
            else:
                assert user['username'] == "testuser"
    
    def test_record_quiz_attempt(self, test_db):
        """Test recording quiz attempts."""
        user_id = 123456789
        chat_id = -1001234567890
        q_id = test_db.add_question("Test Q", ["A", "B", "C", "D"], 1, "Test", "easy")
        
        test_db.add_or_update_user(user_id, "testuser")
        test_db.record_quiz_attempt(
            user_id=user_id,
            chat_id=chat_id,
            question_id=q_id,
            selected_answer=1,
            is_correct=True,
            response_time_ms=1500
        )
        
        stats = test_db.get_user_stats(user_id)
        assert stats is not None
        assert stats['total_attempts'] >= 1
        assert stats['correct_answers'] >= 1
    
    def test_get_user_stats(self, test_db):
        """Test user statistics calculation."""
        user_id = 987654321
        chat_id = -1001111111111
        
        test_db.add_or_update_user(user_id, "statsuser")
        q1 = test_db.add_question("Q1", ["A", "B", "C", "D"], 0, "Test", "easy")
        q2 = test_db.add_question("Q2", ["A", "B", "C", "D"], 1, "Test", "medium")
        
        test_db.record_quiz_attempt(user_id, chat_id, q1, 0, True, 1000)
        test_db.record_quiz_attempt(user_id, chat_id, q2, 2, False, 2000)
        
        stats = test_db.get_user_stats(user_id)
        assert stats['total_attempts'] == 2
        assert stats['correct_answers'] == 1
        assert stats['accuracy'] == 50.0
    
    def test_get_leaderboard(self, test_db):
        """Test leaderboard generation."""
        users = [(111, "user1"), (222, "user2"), (333, "user3")]
        chat_id = -1001234567890
        q_id = test_db.add_question("Q", ["A", "B", "C", "D"], 0, "Test", "easy")
        
        for user_id, username in users:
            test_db.add_or_update_user(user_id, username)
            test_db.record_quiz_attempt(user_id, chat_id, q_id, 0, True, 1000)
        
        leaderboard, total = test_db.get_leaderboard_realtime(limit=10, offset=0)
        assert len(leaderboard) >= 3
        assert total >= 3
        assert all('user_id' in entry for entry in leaderboard)


class TestDeveloperAccess:
    """Test developer access management."""
    
    def test_add_developer(self, test_db):
        """Test adding developer access."""
        dev_id = 999999999
        
        test_db.add_developer(dev_id, "devuser", "Developer")
        
        is_dev = test_db.is_developer(dev_id)
        assert is_dev is True
    
    def test_check_developer(self, test_db):
        """Test developer access check."""
        dev_id = 888888888
        normal_id = 777777777
        
        test_db.add_developer(dev_id, "admin")
        
        assert test_db.is_developer(dev_id) is True
        assert test_db.is_developer(normal_id) is False
    
    def test_remove_developer(self, test_db):
        """Test removing developer access."""
        dev_id = 666666666
        
        test_db.add_developer(dev_id, "temp_dev")
        assert test_db.is_developer(dev_id) is True
        
        test_db.remove_developer(dev_id)
        assert test_db.is_developer(dev_id) is False
    
    def test_get_all_developers(self, test_db):
        """Test retrieving all developers."""
        test_db.add_developer(111, "dev1")
        test_db.add_developer(222, "dev2")
        
        developers = test_db.get_all_developers()
        assert len(developers) >= 2


class TestGroupTracking:
    """Test group chat tracking."""
    
    def test_add_or_update_group(self, test_db):
        """Test adding and updating groups."""
        chat_id = -1001234567890
        
        test_db.add_or_update_group(chat_id, "Test Group", "supergroup")
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = test_db._get_placeholder()
            cursor.execute(
                f"SELECT * FROM groups WHERE chat_id = {placeholder}",
                (chat_id,)
            )
            group = cursor.fetchone()
            
            assert group is not None
    
    def test_set_group_active(self, test_db):
        """Test setting group active status."""
        chat_id = -1001111111111
        
        test_db.add_or_update_group(chat_id, "Active Group", "supergroup")
        test_db.set_group_active(chat_id, True)
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = test_db._get_placeholder()
            cursor.execute(
                f"SELECT is_active FROM groups WHERE chat_id = {placeholder}",
                (chat_id,)
            )
            result = cursor.fetchone()
            
            is_active = result[0] if test_db.db_type == 'postgresql' else result['is_active']
            assert is_active == 1 or is_active is True


class TestActivityLogging:
    """Test activity logging functionality."""
    
    def test_log_activity(self, test_db):
        """Test logging user activity."""
        test_db.log_activity(
            activity_type="command",
            user_id=123456789,
            chat_id=-1001234567890,
            username="testuser",
            command="quiz",
            success=True,
            response_time_ms=500
        )
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM activity_logs")
            count = cursor.fetchone()[0]
            assert count >= 1
    
    def test_get_recent_activity(self, test_db):
        """Test retrieving recent activity."""
        test_db.log_activity("command", 111, -1001, "user1", command="start")
        test_db.log_activity("command", 222, -1002, "user2", command="help")
        
        activities = test_db.get_recent_activity(limit=10)
        assert len(activities) >= 2


class TestMetrics:
    """Test metrics and analytics."""
    
    def test_get_metrics_summary(self, test_db):
        """Test metrics endpoint data."""
        user_id = 123456
        chat_id = -1001234
        
        test_db.add_or_update_user(user_id, "metricuser")
        test_db.add_or_update_group(chat_id, "Metric Group", "supergroup")
        
        q_id = test_db.add_question("Metric Q", ["A", "B", "C", "D"], 0, "Test", "easy")
        test_db.record_quiz_attempt(user_id, chat_id, q_id, 0, True, 1000)
        
        metrics = test_db.get_metrics_summary()
        assert 'total_users' in metrics
        assert 'total_groups' in metrics
        assert 'total_questions' in metrics
        assert metrics['total_users'] >= 1
        assert metrics['total_questions'] >= 1
    
    def test_log_performance_metric(self, test_db):
        """Test performance metric logging."""
        test_db.log_performance_metric(
            metric_type="api_call",
            value=250.5,
            unit="ms",
            details={"endpoint": "/quiz"}
        )
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM performance_metrics")
            count = cursor.fetchone()[0]
            assert count >= 1


class TestBroadcasts:
    """Test broadcast functionality."""
    
    def test_record_broadcast(self, test_db):
        """Test recording broadcast messages."""
        broadcast_id = test_db.record_broadcast(
            sender_id=999999999,
            message="Test broadcast",
            target_type="all"
        )
        
        assert broadcast_id > 0
    
    def test_get_broadcast_stats(self, test_db):
        """Test retrieving broadcast statistics."""
        b_id = test_db.record_broadcast(
            sender_id=888888888,
            message="Stats test",
            target_type="groups"
        )
        
        test_db.update_broadcast_stats(b_id, sent=10, failed=2)
        
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            placeholder = test_db._get_placeholder()
            cursor.execute(
                f"SELECT sent_count, failed_count FROM broadcasts WHERE id = {placeholder}",
                (b_id,)
            )
            result = cursor.fetchone()
            
            if test_db.db_type == 'postgresql':
                assert result[0] == 10
                assert result[1] == 2
            else:
                assert result['sent_count'] == 10
                assert result['failed_count'] == 2


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_get_nonexistent_question(self, test_db):
        """Test getting a question that doesn't exist."""
        result = test_db.get_question_by_id(99999)
        assert result is None
    
    def test_delete_nonexistent_question(self, test_db):
        """Test deleting a question that doesn't exist."""
        test_db.delete_question(99999)
    
    def test_user_stats_no_attempts(self, test_db):
        """Test getting stats for user with no attempts."""
        user_id = 555555555
        test_db.add_or_update_user(user_id, "newuser")
        
        stats = test_db.get_user_stats(user_id)
        assert stats['total_attempts'] == 0
        assert stats['correct_answers'] == 0
        assert stats['accuracy'] == 0.0
    
    def test_empty_leaderboard(self, test_db):
        """Test leaderboard with no quiz attempts."""
        leaderboard, total = test_db.get_leaderboard_realtime(limit=10, offset=0)
        assert isinstance(leaderboard, list)
        assert total >= 0
    
    def test_invalid_question_data(self, test_db):
        """Test adding question with invalid data."""
        with pytest.raises((DatabaseError, Exception)):
            test_db.add_question(
                question="",
                options=[],
                correct_answer=10,
                category="",
                difficulty="invalid"
            )
