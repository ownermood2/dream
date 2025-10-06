"""Pytest configuration and shared fixtures for MissQuiz tests.

This module provides reusable test fixtures for all test modules including:
- In-memory database instances
- Quiz manager instances
- Rate limiter instances
- Mock Telegram objects (Update, Context)
- Test data generators
"""

import pytest
import tempfile
import os
import json
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime
from src.core.database import DatabaseManager
from src.core.quiz import QuizManager
from src.utils.rate_limiter import RateLimiter


@pytest.fixture
def test_db():
    """Create a test database instance using SQLite in-memory.
    
    This fixture provides a clean database for each test with proper
    schema initialization and automatic cleanup.
    
    Yields:
        DatabaseManager: Configured test database instance
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as tmp:
        db_path = tmp.name
    
    db = DatabaseManager(db_path=db_path)
    
    yield db
    
    if hasattr(db, '_conn') and db._conn:
        db._conn.close()
    
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_questions():
    """Provide sample quiz questions for testing.
    
    Returns:
        list: List of sample question dictionaries
    """
    return [
        {
            "question": "What is the capital of France?",
            "options": ["London", "Berlin", "Paris", "Madrid"],
            "correct_answer": 2,
            "category": "Geography",
            "difficulty": "easy"
        },
        {
            "question": "What is 2 + 2?",
            "options": ["3", "4", "5", "6"],
            "correct_answer": 1,
            "category": "Math",
            "difficulty": "easy"
        },
        {
            "question": "Who wrote 'Romeo and Juliet'?",
            "options": ["Charles Dickens", "William Shakespeare", "Mark Twain", "Jane Austen"],
            "correct_answer": 1,
            "category": "Literature",
            "difficulty": "medium"
        },
        {
            "question": "What is the largest planet?",
            "options": ["Earth", "Mars", "Jupiter", "Saturn"],
            "correct_answer": 2,
            "category": "Science",
            "difficulty": "medium"
        },
        {
            "question": "What year did World War II end?",
            "options": ["1943", "1944", "1945", "1946"],
            "correct_answer": 2,
            "category": "History",
            "difficulty": "hard"
        }
    ]


@pytest.fixture
def quiz_manager(test_db, sample_questions, tmp_path):
    """Create QuizManager with test database and sample questions.
    
    Args:
        test_db: Test database fixture
        sample_questions: Sample questions fixture
        tmp_path: Pytest temporary path fixture
    
    Yields:
        QuizManager: Configured quiz manager instance
    """
    questions_file = tmp_path / "questions.json"
    questions_file.write_text(json.dumps(sample_questions))
    
    scores_file = tmp_path / "scores.json"
    scores_file.write_text(json.dumps({}))
    
    active_chats_file = tmp_path / "active_chats.json"
    active_chats_file.write_text(json.dumps([]))
    
    stats_file = tmp_path / "user_stats.json"
    stats_file.write_text(json.dumps({}))
    
    manager = QuizManager(db_manager=test_db)
    manager.questions_file = str(questions_file)
    manager.scores_file = str(scores_file)
    manager.active_chats_file = str(active_chats_file)
    manager.stats_file = str(stats_file)
    manager.load_data()
    
    yield manager


@pytest.fixture
def rate_limiter():
    """Create RateLimiter instance for testing.
    
    Yields:
        RateLimiter: Fresh rate limiter instance
    """
    limiter = RateLimiter()
    yield limiter


@pytest.fixture
def mock_user():
    """Create mock Telegram User object.
    
    Returns:
        Mock: Mock User with id, username, first_name, last_name
    """
    user = Mock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    user.is_bot = False
    return user


@pytest.fixture
def mock_chat():
    """Create mock Telegram Chat object.
    
    Returns:
        Mock: Mock Chat with id, type, title
    """
    chat = Mock()
    chat.id = -1001234567890
    chat.type = "supergroup"
    chat.title = "Test Group"
    return chat


@pytest.fixture
def mock_private_chat():
    """Create mock Telegram private Chat object.
    
    Returns:
        Mock: Mock Chat for private conversation
    """
    chat = Mock()
    chat.id = 123456789
    chat.type = "private"
    chat.title = None
    return chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Create mock Telegram Message object.
    
    Args:
        mock_user: Mock user fixture
        mock_chat: Mock chat fixture
    
    Returns:
        Mock: Mock Message with text, chat, from_user
    """
    message = Mock()
    message.message_id = 1
    message.from_user = mock_user
    message.chat = mock_chat
    message.text = "/test"
    message.date = datetime.now()
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.reply_poll = AsyncMock()
    message.delete = AsyncMock()
    return message


@pytest.fixture
def mock_update(mock_message):
    """Create mock Telegram Update object.
    
    Args:
        mock_message: Mock message fixture
    
    Returns:
        Mock: Mock Update with message, effective_user, effective_chat
    """
    update = Mock()
    update.update_id = 1
    update.message = mock_message
    update.effective_user = mock_message.from_user
    update.effective_chat = mock_message.chat
    update.effective_message = mock_message
    update.callback_query = None
    return update


@pytest.fixture
def mock_callback_query(mock_user, mock_chat):
    """Create mock Telegram CallbackQuery object.
    
    Args:
        mock_user: Mock user fixture
        mock_chat: Mock chat fixture
    
    Returns:
        Mock: Mock CallbackQuery with data, message, from_user
    """
    callback_query = Mock()
    callback_query.id = "callback_1"
    callback_query.from_user = mock_user
    callback_query.data = "test_callback"
    callback_query.message = Mock()
    callback_query.message.chat = mock_chat
    callback_query.message.message_id = 1
    callback_query.answer = AsyncMock()
    callback_query.edit_message_text = AsyncMock()
    return callback_query


@pytest.fixture
def mock_context():
    """Create mock Telegram CallbackContext object.
    
    Returns:
        Mock: Mock context with bot, user_data, chat_data, args
    """
    context = Mock()
    context.bot = AsyncMock()
    context.bot.username = "testbot"
    context.bot.send_message = AsyncMock()
    context.bot.send_poll = AsyncMock()
    context.bot.delete_message = AsyncMock()
    context.user_data = {}
    context.chat_data = {}
    context.bot_data = {}
    context.args = []
    context.job_queue = Mock()
    return context


@pytest.fixture
def mock_developer_user():
    """Create mock Telegram User object for developer.
    
    Returns:
        Mock: Mock User with developer ID
    """
    user = Mock()
    user.id = 999999999
    user.username = "developer"
    user.first_name = "Dev"
    user.last_name = "User"
    user.is_bot = False
    return user


@pytest.fixture
def mock_poll_answer():
    """Create mock Telegram PollAnswer object.
    
    Returns:
        Mock: Mock PollAnswer with poll_id, user, option_ids
    """
    poll_answer = Mock()
    poll_answer.poll_id = "poll_123"
    poll_answer.user = Mock()
    poll_answer.user.id = 123456789
    poll_answer.user.username = "testuser"
    poll_answer.option_ids = [0]
    return poll_answer


@pytest.fixture
def test_questions_file(tmp_path, sample_questions):
    """Create a temporary questions JSON file.
    
    Args:
        tmp_path: Pytest temporary path fixture
        sample_questions: Sample questions fixture
    
    Returns:
        str: Path to temporary questions file
    """
    questions_file = tmp_path / "test_questions.json"
    questions_file.write_text(json.dumps(sample_questions))
    return str(questions_file)


@pytest.fixture
def cleanup_test_data():
    """Fixture to cleanup test data after tests.
    
    This fixture runs after the test to ensure clean state.
    """
    yield
    
    test_files = [
        'test_questions.json',
        'test_scores.json',
        'test_stats.json'
    ]
    
    for file in test_files:
        if os.path.exists(file):
            os.unlink(file)
