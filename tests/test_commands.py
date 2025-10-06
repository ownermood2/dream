"""Developer Command Tests for MissQuiz Telegram Quiz Bot.

This module tests developer-only commands:
- Add/Edit/Delete quiz questions
- Broadcast messages
- Bot statistics and diagnostics
- Developer access control
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from src.bot.dev_commands import DeveloperCommands


@pytest.fixture
def dev_commands(test_db, quiz_manager):
    """Create DeveloperCommands instance for testing.
    
    Args:
        test_db: Test database fixture
        quiz_manager: Quiz manager fixture
    
    Returns:
        DeveloperCommands: Developer commands instance
    """
    return DeveloperCommands(test_db, quiz_manager)


class TestDeveloperAccessControl:
    """Test developer-only access enforcement."""
    
    @pytest.mark.asyncio
    async def test_developer_access_control(
        self, dev_commands, mock_update, mock_context, test_db
    ):
        """Test developer-only access enforcement."""
        dev_id = 999999999
        normal_id = 123456789
        
        test_db.add_developer(dev_id, "developer")
        
        assert test_db.is_developer(dev_id) is True
        assert test_db.is_developer(normal_id) is False
    
    @pytest.mark.asyncio
    async def test_non_developer_blocked(
        self, dev_commands, mock_update, mock_context
    ):
        """Test non-developer users are blocked from dev commands."""
        mock_update.effective_user.id = 111111111
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Non-developer should receive a response"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "developer" in text or "not authorized" in text or "permission" in text, \
            "Response should indicate lack of developer access"


class TestAddQuizCommand:
    """Test /addquiz command."""
    
    @pytest.mark.asyncio
    async def test_addquiz_command_no_args(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /addquiz command without arguments."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = []
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text']
        assert "usage" in text.lower() or "format" in text.lower()
    
    @pytest.mark.asyncio
    async def test_addquiz_command_with_question(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /addquiz command with valid question."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = [
            "What is 1+1?",
            "1|2|3|4",
            "2",
            "Math",
            "easy"
        ]
        
        initial_count = len(test_db.get_all_questions())
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Command should send a response"
        final_count = len(test_db.get_all_questions())
        assert final_count > initial_count, "Question should be added to database"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "added" in text or "success" in text, "Response should confirm question was added"


class TestEditQuizCommand:
    """Test /editquiz command with pagination."""
    
    @pytest.mark.asyncio
    async def test_editquiz_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /editquiz command."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        q_id = test_db.add_question(
            "Edit Test",
            ["A", "B", "C", "D"],
            0,
            "Test",
            "easy"
        )
        
        await dev_commands.editquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Edit command should send a response"
        call_args = mock_update.message.reply_text.call_args
        assert 'reply_markup' in call_args[1] or 'text' in call_args[1], \
            "Response should have markup or text"
        
        if 'reply_markup' in call_args[1]:
            assert call_args[1]['reply_markup'] is not None, "Should have inline keyboard for selection"
    
    @pytest.mark.asyncio
    async def test_editquiz_pagination(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /editquiz command pagination."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        for i in range(15):
            test_db.add_question(
                f"Question {i}",
                ["A", "B", "C", "D"],
                0,
                "Test",
                "easy"
            )
        
        await dev_commands.editquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Edit command should send a response with pagination"
        call_args = mock_update.message.reply_text.call_args
        
        if 'reply_markup' in call_args[1]:
            markup = call_args[1]['reply_markup']
            assert markup is not None, "Should have pagination keyboard"


class TestDeleteQuizCommand:
    """Test /delquiz command."""
    
    @pytest.mark.asyncio
    async def test_delquiz_command_confirmation(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /delquiz command shows confirmation."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        q_id = test_db.add_question(
            "To Delete",
            ["A", "B", "C", "D"],
            0,
            "Test",
            "easy"
        )
        
        mock_context.args = [str(q_id)]
        
        await dev_commands.delquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Delete command should send confirmation"
        call_args = mock_update.message.reply_text.call_args
        
        if 'reply_markup' in call_args[1]:
            assert call_args[1]['reply_markup'] is not None, "Should have confirmation buttons"
        
        text = call_args[1]['text'].lower()
        assert "delete" in text or "confirm" in text or "sure" in text, \
            "Should ask for confirmation"
    
    @pytest.mark.asyncio
    async def test_delquiz_invalid_id(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /delquiz with invalid question ID."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = ["99999"]
        
        await dev_commands.delquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Invalid ID should get response"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "not found" in text or "invalid" in text or "error" in text, \
            "Should indicate question doesn't exist"


class TestBroadcastCommand:
    """Test /broadcast command."""
    
    @pytest.mark.asyncio
    async def test_broadcast_command_no_message(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /broadcast command without message."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = []
        
        await dev_commands.broadcast_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_broadcast_command_with_message(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /broadcast command with message."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        test_db.add_or_update_group(-1001111, "Group 1", "supergroup")
        test_db.set_group_active(-1001111, True)
        
        mock_context.args = ["Test", "broadcast", "message"]
        mock_context.bot.send_message = AsyncMock()
        
        await dev_commands.broadcast_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Broadcast should send status message"
        assert mock_context.bot.send_message.called, "Broadcast should send message to groups"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "broadcast" in text or "sent" in text or "complete" in text, \
            "Should confirm broadcast completion"


class TestStatsCommand:
    """Test /stats command."""
    
    @pytest.mark.asyncio
    async def test_stats_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /stats command."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        test_db.add_or_update_user(111111, "user1")
        test_db.add_or_update_group(-1001111, "Group 1", "supergroup")
        
        await dev_commands.stats_command(mock_update, mock_context)
        
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text']
        
        assert "users" in text.lower() or "groups" in text.lower()


class TestDevDiagnosticsCommand:
    """Test /dev diagnostics command."""
    
    @pytest.mark.asyncio
    async def test_dev_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /dev diagnostics command."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        await dev_commands.dev_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Dev command should send diagnostics"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "bot" in text or "status" in text or "system" in text, \
            "Diagnostics should contain bot/system info"


class TestManageDevelopersCommand:
    """Test developer management commands."""
    
    @pytest.mark.asyncio
    async def test_add_developer_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test adding a new developer."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "admin")
        
        new_dev_id = 888888888
        mock_context.args = [str(new_dev_id), "newdev"]
        
        await dev_commands.add_dev_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Add dev command should send response"
        assert test_db.is_developer(new_dev_id), "New developer should be added to database"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "added" in text or "success" in text, "Should confirm developer was added"
    
    @pytest.mark.asyncio
    async def test_remove_developer_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test removing a developer."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "admin")
        
        remove_dev_id = 777777777
        test_db.add_developer(remove_dev_id, "temp")
        
        mock_context.args = [str(remove_dev_id)]
        
        await dev_commands.remove_dev_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Remove dev command should send response"
        assert not test_db.is_developer(remove_dev_id), "Developer should be removed from database"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "removed" in text or "success" in text, "Should confirm developer was removed"
    
    @pytest.mark.asyncio
    async def test_list_developers_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test listing all developers."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "admin")
        test_db.add_developer(111111, "dev1")
        test_db.add_developer(222222, "dev2")
        
        await dev_commands.list_devs_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "List devs should send response"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text']
        
        assert "111111" in text or "dev1" in text, "Should list first developer"
        assert "222222" in text or "dev2" in text, "Should list second developer"


class TestRestartCommand:
    """Test bot restart command."""
    
    @pytest.mark.asyncio
    async def test_restart_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /restart command."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        with patch('os.execv') as mock_execv:
            await dev_commands.restart_command(mock_update, mock_context)
            
            assert mock_update.message.reply_text.called, "Restart should send confirmation"
            call_args = mock_update.message.reply_text.call_args
            text = call_args[1]['text'].lower()
            assert "restart" in text, "Should mention restart"


class TestBackupCommand:
    """Test database backup command."""
    
    @pytest.mark.asyncio
    async def test_backup_command(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /backup command."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        await dev_commands.backup_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called, \
            "Backup command should send response or document"


class TestCallbackHandlers:
    """Test callback handlers for developer commands."""
    
    @pytest.mark.asyncio
    async def test_edit_question_callback(
        self, dev_commands, mock_callback_query, mock_context, test_db, mock_developer_user
    ):
        """Test edit question callback handler."""
        mock_callback_query.from_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        q_id = test_db.add_question(
            "Callback Test",
            ["A", "B", "C", "D"],
            0,
            "Test",
            "easy"
        )
        
        mock_callback_query.data = f"edit_q_{q_id}"
        
        mock_update = Mock()
        mock_update.callback_query = mock_callback_query
        mock_update.effective_user = mock_developer_user
        
        await dev_commands.handle_edit_callback(mock_update, mock_context)
        
        assert mock_callback_query.answer.called, "Callback should be acknowledged"
        assert mock_callback_query.edit_message_text.called or mock_callback_query.message.reply_text.called, \
            "Should show edit interface"
    
    @pytest.mark.asyncio
    async def test_delete_confirmation_callback(
        self, dev_commands, mock_callback_query, mock_context, test_db, mock_developer_user
    ):
        """Test delete confirmation callback."""
        mock_callback_query.from_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        q_id = test_db.add_question(
            "Delete Callback Test",
            ["A", "B", "C", "D"],
            0,
            "Test",
            "easy"
        )
        
        mock_callback_query.data = f"del_confirm_{q_id}"
        
        mock_update = Mock()
        mock_update.callback_query = mock_callback_query
        mock_update.effective_user = mock_developer_user
        
        initial_count = len(test_db.get_all_questions())
        
        await dev_commands.handle_delete_callback(mock_update, mock_context)
        
        assert mock_callback_query.answer.called, "Callback should be acknowledged"
        
        final_count = len(test_db.get_all_questions())
        assert final_count < initial_count, "Question should be deleted from database"


class TestErrorHandling:
    """Test error handling in developer commands."""
    
    @pytest.mark.asyncio
    async def test_addquiz_invalid_format(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /addquiz with invalid format."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = ["incomplete"]
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Invalid format should get error response"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "usage" in text or "format" in text or "error" in text, \
            "Should explain correct format"
    
    @pytest.mark.asyncio
    async def test_broadcast_failed_delivery(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /broadcast with failed message delivery."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        test_db.add_or_update_group(-1001111, "Group 1", "supergroup")
        test_db.set_group_active(-1001111, True)
        
        mock_context.args = ["Test message"]
        mock_context.bot.send_message = AsyncMock(side_effect=Exception("Failed"))
        
        await dev_commands.broadcast_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Failed broadcast should send status"
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "broadcast" in text or "complete" in text or "error" in text, \
            "Should report broadcast status even on failure"


class TestQuestionValidation:
    """Test question validation in developer commands."""
    
    @pytest.mark.asyncio
    async def test_addquiz_validates_options(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /addquiz validates number of options."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = [
            "Question?",
            "A|B",
            "1",
            "Test",
            "easy"
        ]
        
        initial_count = len(test_db.get_all_questions())
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Validation error should send response"
        final_count = len(test_db.get_all_questions())
        assert final_count == initial_count, "Invalid question should not be added"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "option" in text or "error" in text or "4" in text, \
            "Should explain that 4 options are required"
    
    @pytest.mark.asyncio
    async def test_addquiz_validates_correct_answer(
        self, dev_commands, mock_update, mock_context, test_db, mock_developer_user
    ):
        """Test /addquiz validates correct answer index."""
        mock_update.effective_user = mock_developer_user
        test_db.add_developer(mock_developer_user.id, "dev")
        
        mock_context.args = [
            "Question?",
            "A|B|C|D",
            "10",
            "Test",
            "easy"
        ]
        
        initial_count = len(test_db.get_all_questions())
        
        await dev_commands.addquiz_command(mock_update, mock_context)
        
        assert mock_update.message.reply_text.called, "Invalid answer index should send response"
        final_count = len(test_db.get_all_questions())
        assert final_count == initial_count, "Question with invalid answer should not be added"
        
        call_args = mock_update.message.reply_text.call_args
        text = call_args[1]['text'].lower()
        assert "answer" in text or "index" in text or "error" in text, \
            "Should explain answer index is invalid"
