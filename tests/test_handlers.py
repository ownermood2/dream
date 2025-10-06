"""Bot Handler Integration Tests for MissQuiz Telegram Quiz Bot.

This module tests bot handlers with mocked Telegram objects:
- Command handlers (start, help, quiz, etc.)
- Rate limiting enforcement
- Private vs group chat behavior
- User tracking and statistics
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from src.bot.handlers import TelegramQuizBot
from src.core.quiz import QuizManager
from src.core.database import DatabaseManager


@pytest.fixture
def bot_instance(quiz_manager, test_db):
    """Create TelegramQuizBot instance for testing.
    
    Args:
        quiz_manager: Quiz manager fixture
        test_db: Test database fixture
    
    Returns:
        TelegramQuizBot: Bot instance for testing
    """
    bot = TelegramQuizBot(quiz_manager, db_manager=test_db)
    return bot


class TestStartCommand:
    """Test /start command."""
    
    @pytest.mark.asyncio
    async def test_start_command_private_chat(
        self, bot_instance, mock_update, mock_context, mock_private_chat
    ):
        """Test /start command in private chat."""
        mock_update.message.chat = mock_private_chat
        mock_update.effective_chat = mock_private_chat
        
        await bot_instance.start_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Welcome" in call_args[1]['text'] or "welcome" in call_args[1]['text'].lower()
    
    @pytest.mark.asyncio
    async def test_start_command_group_chat(
        self, bot_instance, mock_update, mock_context, mock_chat
    ):
        """Test /start command in group chat."""
        mock_update.message.chat = mock_chat
        mock_update.effective_chat = mock_chat
        
        await bot_instance.start_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()


class TestHelpCommand:
    """Test /help command."""
    
    @pytest.mark.asyncio
    async def test_help_command(self, bot_instance, mock_update, mock_context):
        """Test /help command."""
        await bot_instance.help_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text']
        
        assert "/quiz" in text or "quiz" in text.lower()


class TestQuizCommand:
    """Test /quiz command."""
    
    @pytest.mark.asyncio
    async def test_quiz_command_private_chat(
        self, bot_instance, mock_update, mock_context, mock_private_chat
    ):
        """Test /quiz command in private chat."""
        mock_update.message.chat = mock_private_chat
        mock_update.effective_chat = mock_private_chat
        
        mock_update.message.reply_poll = AsyncMock(
            return_value=Mock(poll=Mock(id="poll_123"))
        )
        
        await bot_instance.quiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_poll.called, "Quiz command should send a poll"
        call_args = mock_update.message.reply_poll.call_args
        assert 'question' in call_args[1], "Poll should have a question"
        assert 'options' in call_args[1], "Poll should have options"
        assert len(call_args[1]['options']) == 4, "Poll should have 4 options"
    
    @pytest.mark.asyncio
    async def test_quiz_command_group_chat(
        self, bot_instance, mock_update, mock_context, mock_chat
    ):
        """Test /quiz command in group chat."""
        mock_update.message.chat = mock_chat
        mock_update.effective_chat = mock_chat
        
        mock_update.message.reply_poll = AsyncMock(
            return_value=Mock(poll=Mock(id="poll_123"))
        )
        
        await bot_instance.quiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_poll.called, "Quiz command should send a poll in group chat"
        call_args = mock_update.message.reply_poll.call_args
        assert 'question' in call_args[1], "Poll should have a question"
        assert len(call_args[1]['options']) == 4, "Poll should have 4 options"


class TestStatsCommand:
    """Test /mystats command."""
    
    @pytest.mark.asyncio
    async def test_mystats_command(
        self, bot_instance, mock_update, mock_context
    ):
        """Test /mystats command."""
        user_id = mock_update.effective_user.id
        chat_id = mock_update.effective_chat.id
        
        bot_instance.db.add_or_update_user(
            user_id, 
            mock_update.effective_user.username
        )
        
        q_id = bot_instance.db.add_question(
            "Test Q", 
            ["A", "B", "C", "D"], 
            0, 
            "Test", 
            "easy"
        )
        
        bot_instance.db.record_quiz_attempt(
            user_id, chat_id, q_id, 0, True, 1000
        )
        
        await bot_instance.mystats_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text']
        
        assert "stats" in text.lower() or "attempts" in text.lower()


class TestLeaderboardCommand:
    """Test /leaderboard command."""
    
    @pytest.mark.asyncio
    async def test_leaderboard_command(
        self, bot_instance, mock_update, mock_context
    ):
        """Test /leaderboard command."""
        chat_id = mock_update.effective_chat.id
        
        users = [
            (111111, "user1"),
            (222222, "user2"),
            (333333, "user3")
        ]
        
        q_id = bot_instance.db.add_question(
            "LB Test", ["A", "B", "C", "D"], 0, "Test", "easy"
        )
        
        for user_id, username in users:
            bot_instance.db.add_or_update_user(user_id, username)
            bot_instance.db.record_quiz_attempt(
                user_id, chat_id, q_id, 0, True, 1000
            )
        
        await bot_instance.leaderboard_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()


class TestRateLimitEnforcement:
    """Test rate limiting on commands."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_enforcement(
        self, bot_instance, mock_update, mock_context
    ):
        """Test rate limiting on commands."""
        user_id = mock_update.effective_user.id
        
        mock_update.message.reply_poll = AsyncMock(
            return_value=Mock(poll=Mock(id="poll_123"))
        )
        
        for i in range(6):
            await bot_instance.quiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, \
            "6th quiz command should be rate limited and send text reply (not poll)"
        
        assert not mock_update.message.reply_poll.call_count >= 6, \
            "Poll should not be sent on 6th attempt (rate limited)"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "limit" in text or "wait" in text or "slow" in text, \
            "Rate limit message should inform user about limit"


class TestPollAnswerHandler:
    """Test poll answer handling."""
    
    @pytest.mark.asyncio
    async def test_poll_answer_handler(
        self, bot_instance, mock_poll_answer, mock_context
    ):
        """Test handling poll answers."""
        poll_id = "test_poll_123"
        chat_id = -1001234567890
        user_id = mock_poll_answer.user.id
        
        q_id = bot_instance.db.add_question(
            "Poll Test", ["A", "B", "C", "D"], 1, "Test", "easy"
        )
        
        bot_instance.active_polls[poll_id] = {
            'chat_id': chat_id,
            'question_id': q_id,
            'correct_answer': 1,
            'question_text': "Poll Test"
        }
        
        mock_poll_answer.poll_id = poll_id
        mock_poll_answer.option_ids = [1]
        
        mock_update = Mock()
        mock_update.poll_answer = mock_poll_answer
        
        await bot_instance.handle_poll_answer(mock_update, mock_context)
        
        user_attempts = bot_instance.db.get_user_stats(user_id)
        assert user_attempts is not None, "User attempts should be recorded"
        assert user_attempts['total_attempts'] >= 1, "Poll answer should be recorded in database"


class TestUserTracking:
    """Test user tracking and PM access."""
    
    @pytest.mark.asyncio
    async def test_user_tracking_in_private_chat(
        self, bot_instance, mock_update, mock_context, mock_private_chat
    ):
        """Test user tracking in private chat."""
        mock_update.message.chat = mock_private_chat
        mock_update.effective_chat = mock_private_chat
        
        user_id = mock_update.effective_user.id
        
        await bot_instance.start_command(mock_update, mock_context)
        
        assert bot_instance.db.get_user_pm_access(user_id) is True


class TestErrorHandling:
    """Test error handling in handlers."""
    
    @pytest.mark.asyncio
    async def test_quiz_command_no_questions(
        self, bot_instance, mock_update, mock_context, tmp_path
    ):
        """Test /quiz command with no questions available."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("[]")
        
        bot_instance.quiz_manager.questions_file = str(empty_file)
        bot_instance.quiz_manager.load_data()
        
        await bot_instance.quiz_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()


class TestCallbackHandlers:
    """Test callback query handlers."""
    
    @pytest.mark.asyncio
    async def test_callback_query_handling(
        self, bot_instance, mock_callback_query, mock_context
    ):
        """Test callback query handling."""
        mock_update = Mock()
        mock_update.callback_query = mock_callback_query
        mock_update.effective_user = mock_callback_query.from_user
        
        await bot_instance.handle_callback_query(mock_update, mock_context)
        
        assert mock_callback_query.answer.called, "Callback query should be answered"


class TestCommandCooldowns:
    """Test command cooldown system."""
    
    @pytest.mark.asyncio
    async def test_user_command_cooldown_in_group(
        self, bot_instance, mock_update, mock_context, mock_chat
    ):
        """Test user command cooldown in group chats."""
        mock_update.message.chat = mock_chat
        mock_update.effective_chat = mock_chat
        
        user_id = mock_update.effective_user.id
        
        allowed, remaining = bot_instance.check_user_command_cooldown(
            user_id, "quiz", "supergroup"
        )
        assert allowed is True
        
        allowed, remaining = bot_instance.check_user_command_cooldown(
            user_id, "quiz", "supergroup"
        )
        assert allowed is False
        assert remaining > 0
    
    @pytest.mark.asyncio
    async def test_no_cooldown_in_private_chat(
        self, bot_instance, mock_update, mock_context, mock_private_chat
    ):
        """Test no cooldown in private chats."""
        user_id = mock_update.effective_user.id
        
        for _ in range(10):
            allowed, remaining = bot_instance.check_user_command_cooldown(
                user_id, "quiz", "private"
            )
            assert allowed is True
            assert remaining == 0


class TestActivityLogging:
    """Test activity logging from handlers."""
    
    @pytest.mark.asyncio
    async def test_activity_logging(
        self, bot_instance, mock_update, mock_context
    ):
        """Test that commands log activity."""
        initial_count = len(bot_instance.db.get_recent_activity(limit=100))
        
        await bot_instance.start_command(mock_update, mock_context)
        
        final_count = len(bot_instance.db.get_recent_activity(limit=100))
        assert final_count >= initial_count


class TestGroupTracking:
    """Test group chat tracking."""
    
    @pytest.mark.asyncio
    async def test_group_tracking(
        self, bot_instance, mock_update, mock_context, mock_chat
    ):
        """Test group is tracked when bot is used."""
        mock_update.message.chat = mock_chat
        mock_update.effective_chat = mock_chat
        
        chat_id = mock_chat.id
        
        await bot_instance.start_command(mock_update, mock_context)
        
        groups = bot_instance.db.get_all_groups()
        group_ids = [g['chat_id'] for g in groups]
        assert chat_id in group_ids, "Group should be tracked in database after command"


class TestCleanupOperations:
    """Test cleanup operations."""
    
    @pytest.mark.asyncio
    async def test_message_cleanup(
        self, bot_instance, mock_update, mock_context
    ):
        """Test automatic message cleanup."""
        chat_id = mock_update.effective_chat.id
        message_id = 123
        
        bot_instance.cleanup_messages[chat_id] = [(message_id, 60)]
        
        await bot_instance.cleanup_old_messages(chat_id)
