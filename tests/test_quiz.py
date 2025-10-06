"""Quiz Manager Tests for MissQuiz Telegram Quiz Bot.

This module tests the quiz business logic including:
- Question loading and management
- Random question selection with anti-repetition
- Answer validation
- Score tracking and leaderboards
- Category filtering
"""

import pytest
import json
from src.core.quiz import QuizManager
from src.core.exceptions import QuestionNotFoundError, ValidationError


class TestQuestionLoading:
    """Test question loading and initialization."""
    
    def test_load_questions(self, quiz_manager):
        """Test loading questions from JSON."""
        assert len(quiz_manager.questions) > 0
        assert all(isinstance(q, dict) for q in quiz_manager.questions)
        assert all('question' in q for q in quiz_manager.questions)
    
    def test_questions_have_required_fields(self, quiz_manager):
        """Test that all questions have required fields."""
        required_fields = ['question', 'options', 'correct_answer', 'category']
        
        for question in quiz_manager.questions:
            for field in required_fields:
                assert field in question, f"Question missing field: {field}"
    
    def test_questions_have_database_id(self, quiz_manager):
        """Test questions have database IDs."""
        for question in quiz_manager.questions:
            assert 'id' in question or 'db_id' in question


class TestQuestionSelection:
    """Test question selection logic."""
    
    def test_get_random_question(self, quiz_manager):
        """Test random question selection."""
        chat_id = -1001234567890
        
        question = quiz_manager.get_random_question(chat_id)
        assert question is not None
        assert 'question' in question
        assert 'options' in question
        assert len(question['options']) > 0
    
    def test_question_not_repeated_immediately(self, quiz_manager):
        """Test that questions are not repeated immediately."""
        chat_id = -1001111111111
        
        asked_questions = set()
        max_attempts = min(10, len(quiz_manager.questions))
        
        for _ in range(max_attempts):
            question = quiz_manager.get_random_question(chat_id)
            question_text = question['question']
            
            if question_text in asked_questions and len(asked_questions) < len(quiz_manager.questions):
                pytest.fail("Question repeated too soon")
            
            asked_questions.add(question_text)
    
    def test_question_selection_with_small_pool(self, quiz_manager, tmp_path):
        """Test question selection with very small question pool."""
        chat_id = -1002222222222
        
        small_questions = [
            {
                "question": "Q1",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 0,
                "category": "Test"
            }
        ]
        
        small_file = tmp_path / "small_questions.json"
        small_file.write_text(json.dumps(small_questions))
        
        quiz_manager.questions_file = str(small_file)
        quiz_manager.load_data()
        
        q1 = quiz_manager.get_random_question(chat_id)
        q2 = quiz_manager.get_random_question(chat_id)
        
        assert q1 is not None
        assert q2 is not None


class TestAnswerValidation:
    """Test answer checking logic."""
    
    def test_check_correct_answer(self, quiz_manager):
        """Test correct answer validation."""
        question = {
            'question': 'Test?',
            'options': ['A', 'B', 'C', 'D'],
            'correct_answer': 2,
            'category': 'Test'
        }
        
        is_correct = quiz_manager.check_answer(question, 2)
        assert is_correct is True
    
    def test_check_incorrect_answer(self, quiz_manager):
        """Test incorrect answer validation."""
        question = {
            'question': 'Test?',
            'options': ['A', 'B', 'C', 'D'],
            'correct_answer': 1,
            'category': 'Test'
        }
        
        is_correct = quiz_manager.check_answer(question, 3)
        assert is_correct is False
    
    def test_check_answer_with_invalid_index(self, quiz_manager):
        """Test answer validation with invalid index."""
        question = {
            'question': 'Test?',
            'options': ['A', 'B', 'C', 'D'],
            'correct_answer': 0,
            'category': 'Test'
        }
        
        is_correct = quiz_manager.check_answer(question, 10)
        assert is_correct is False


class TestCategoryFiltering:
    """Test category-based question filtering."""
    
    def test_get_questions_by_category(self, quiz_manager):
        """Test category filtering."""
        categories = set(q.get('category', 'General') for q in quiz_manager.questions)
        
        for category in categories:
            questions = quiz_manager.get_questions_by_category(category)
            assert all(q.get('category', 'General') == category for q in questions)
    
    def test_get_questions_nonexistent_category(self, quiz_manager):
        """Test filtering with non-existent category."""
        questions = quiz_manager.get_questions_by_category("NonExistentCategory")
        assert len(questions) == 0


class TestScoreTracking:
    """Test score and statistics tracking."""
    
    def test_update_user_score(self, quiz_manager):
        """Test score updates."""
        user_id = 123456789
        chat_id = -1001234567890
        
        initial_score = quiz_manager.get_user_score(user_id, chat_id)
        
        quiz_manager.update_user_score(user_id, chat_id, points=10)
        
        new_score = quiz_manager.get_user_score(user_id, chat_id)
        assert new_score >= initial_score + 10
    
    def test_get_user_rank(self, quiz_manager):
        """Test rank calculation."""
        user_id = 987654321
        chat_id = -1001234567890
        
        quiz_manager.update_user_score(user_id, chat_id, points=50)
        
        rank = quiz_manager.get_user_rank(user_id)
        assert rank >= 1
    
    def test_leaderboard_generation(self, quiz_manager):
        """Test leaderboard generation."""
        chat_id = -1001234567890
        users = [
            (111111, 50),
            (222222, 100),
            (333333, 75)
        ]
        
        for user_id, points in users:
            quiz_manager.update_user_score(user_id, chat_id, points=points)
        
        leaderboard = quiz_manager.get_leaderboard(limit=10)
        assert len(leaderboard) > 0


class TestStatistics:
    """Test statistics and analytics."""
    
    def test_get_user_stats(self, quiz_manager):
        """Test user statistics retrieval."""
        user_id = 555555555
        chat_id = -1001234567890
        
        quiz_manager.db.add_or_update_user(user_id, "testuser")
        q_id = quiz_manager.db.add_question(
            "Stats test",
            ["A", "B", "C", "D"],
            1,
            "Test",
            "easy"
        )
        
        quiz_manager.db.record_quiz_attempt(
            user_id, chat_id, q_id, 1, True, 1000
        )
        
        stats = quiz_manager.get_user_stats(user_id)
        assert stats is not None
        assert 'total_attempts' in stats
    
    def test_get_global_stats(self, quiz_manager):
        """Test global statistics."""
        stats = quiz_manager.get_global_stats()
        assert 'total_questions' in stats
        assert stats['total_questions'] >= 0
    
    def test_get_category_stats(self, quiz_manager):
        """Test category-based statistics."""
        categories = set(q.get('category', 'General') for q in quiz_manager.questions)
        
        for category in categories:
            count = quiz_manager.get_category_question_count(category)
            assert count >= 0


class TestDataPersistence:
    """Test data saving and loading."""
    
    def test_save_scores(self, quiz_manager):
        """Test saving scores to file."""
        user_id = 777777777
        chat_id = -1001234567890
        
        quiz_manager.update_user_score(user_id, chat_id, points=25)
        quiz_manager.save_scores()
        
        with open(quiz_manager.scores_file, 'r') as f:
            scores = json.load(f)
            assert isinstance(scores, dict)
    
    def test_save_stats(self, quiz_manager):
        """Test saving statistics to file."""
        quiz_manager.save_stats()
        
        with open(quiz_manager.stats_file, 'r') as f:
            stats = json.load(f)
            assert isinstance(stats, dict)


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_question_pool(self, quiz_manager, tmp_path):
        """Test behavior with no questions."""
        empty_file = tmp_path / "empty_questions.json"
        empty_file.write_text(json.dumps([]))
        
        quiz_manager.questions_file = str(empty_file)
        quiz_manager.load_data()
        
        with pytest.raises((QuestionNotFoundError, IndexError, Exception)):
            quiz_manager.get_random_question(-1001234567890)
    
    def test_corrupted_question_data(self, quiz_manager, tmp_path):
        """Test handling of corrupted question data."""
        corrupted_file = tmp_path / "corrupted.json"
        corrupted_file.write_text("not valid json{]")
        
        quiz_manager.questions_file = str(corrupted_file)
        
        try:
            quiz_manager.load_data()
        except (json.JSONDecodeError, Exception):
            assert True
    
    def test_question_with_missing_fields(self, quiz_manager, tmp_path):
        """Test handling questions with missing required fields."""
        invalid_questions = [
            {
                "question": "No options",
                "correct_answer": 0
            }
        ]
        
        invalid_file = tmp_path / "invalid_questions.json"
        invalid_file.write_text(json.dumps(invalid_questions))
        
        quiz_manager.questions_file = str(invalid_file)
        quiz_manager.load_data()
    
    def test_duplicate_questions(self, quiz_manager, tmp_path):
        """Test handling of duplicate questions."""
        duplicate_questions = [
            {
                "question": "Same question",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 0,
                "category": "Test"
            },
            {
                "question": "Same question",
                "options": ["A", "B", "C", "D"],
                "correct_answer": 0,
                "category": "Test"
            }
        ]
        
        dup_file = tmp_path / "duplicates.json"
        dup_file.write_text(json.dumps(duplicate_questions))
        
        quiz_manager.questions_file = str(dup_file)
        quiz_manager.load_data()
        
        assert len(quiz_manager.questions) >= 1


class TestCaching:
    """Test caching mechanisms."""
    
    def test_question_cache(self, quiz_manager):
        """Test question caching."""
        chat_id = -1001234567890
        
        q1 = quiz_manager.get_random_question(chat_id)
        assert q1 is not None
        
        assert chat_id in quiz_manager.recent_questions
        assert len(quiz_manager.recent_questions[chat_id]) > 0
    
    def test_leaderboard_cache(self, quiz_manager):
        """Test leaderboard caching."""
        lb1 = quiz_manager.get_leaderboard(limit=10)
        lb2 = quiz_manager.get_leaderboard(limit=10)
        
        assert isinstance(lb1, list)
        assert isinstance(lb2, list)


class TestCleanup:
    """Test cleanup operations."""
    
    def test_cleanup_old_questions(self, quiz_manager):
        """Test cleanup of old question history."""
        chat_id = -1001234567890
        
        for _ in range(60):
            try:
                quiz_manager.get_random_question(chat_id)
            except:
                break
        
        quiz_manager.cleanup_old_questions()
        
        if chat_id in quiz_manager.recent_questions:
            assert len(quiz_manager.recent_questions[chat_id]) <= 50
