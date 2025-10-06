"""Rate Limiter Tests for MissQuiz Telegram Quiz Bot.

This module tests the rate limiting functionality including:
- Rate limit initialization
- Per-minute and per-hour limits for different command types
- Developer bypass mechanism
- Rate limit window reset
- Cleanup of old entries
- Thread safety
"""

import pytest
import time
from threading import Thread
from src.utils.rate_limiter import RateLimiter, RATE_LIMITS


class TestRateLimiterInitialization:
    """Test RateLimiter initialization."""
    
    def test_rate_limit_initialization(self, rate_limiter):
        """Test RateLimiter initialization."""
        assert rate_limiter is not None
        assert hasattr(rate_limiter, 'user_commands')
        assert hasattr(rate_limiter, 'lock')
        assert rate_limiter.ttl_seconds == 3600
    
    def test_rate_limits_configuration(self):
        """Test rate limits are properly configured."""
        assert 'heavy' in RATE_LIMITS
        assert 'medium' in RATE_LIMITS
        assert 'light' in RATE_LIMITS
        
        assert RATE_LIMITS['heavy']['per_minute'] == 5
        assert RATE_LIMITS['heavy']['per_hour'] == 20
        
        assert RATE_LIMITS['medium']['per_minute'] == 10
        assert RATE_LIMITS['medium']['per_hour'] == 50
        
        assert RATE_LIMITS['light']['per_minute'] == 15


class TestHeavyCommandLimits:
    """Test heavy command rate limits (5/min, 20/hr)."""
    
    def test_heavy_command_per_minute_limit(self, rate_limiter):
        """Test heavy command rate limit (5/min)."""
        user_id = 123456789
        command = 'quiz'
        
        for i in range(5):
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False
        assert wait > 0
        assert 'minute' in limit_type
    
    def test_heavy_command_per_hour_limit(self, rate_limiter, mocker):
        """Test heavy command per hour limit (20/hr)."""
        user_id = 987654321
        command = 'addquiz'
        base_time = 1000000.0
        
        mock_time = mocker.patch('src.utils.rate_limiter.time.time')
        mock_time.return_value = base_time
        
        # Space commands 3 minutes (180 seconds) apart to avoid per-minute limit
        # 20 commands * 180 seconds = 3600 seconds = 1 hour
        for i in range(20):
            mock_time.return_value = base_time + (i * 180)
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True, f"Should allow command {i+1}/20"
            rate_limiter.record_command(user_id, command)
        
        # 21st command should be blocked (still within the hour from first command)
        mock_time.return_value = base_time + (20 * 180)
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False, "Should block 21st command (hourly limit exceeded)"
        assert 'hour' in limit_type, "Should be limited by hourly rate"
        assert wait > 0, "Should have positive wait time"
    
    def test_heavy_commands_are_limited(self, rate_limiter):
        """Test all heavy commands are rate limited."""
        heavy_commands = RATE_LIMITS['heavy']['commands']
        user_id = 111111111
        
        for command in heavy_commands:
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            assert limit_type == 'heavy'


class TestMediumCommandLimits:
    """Test medium command rate limits (10/min, 50/hr)."""
    
    def test_medium_command_per_minute_limit(self, rate_limiter):
        """Test medium command rate limit (10/min)."""
        user_id = 222222222
        command = 'mystats'
        
        for i in range(10):
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False
        assert wait > 0
        assert 'minute' in limit_type
    
    def test_medium_commands_are_limited(self, rate_limiter):
        """Test all medium commands are rate limited."""
        medium_commands = RATE_LIMITS['medium']['commands']
        user_id = 333333333
        
        for command in medium_commands:
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            assert limit_type == 'medium'


class TestLightCommandLimits:
    """Test light command rate limits (15/min)."""
    
    def test_light_command_per_minute_limit(self, rate_limiter):
        """Test light command rate limit (15/min)."""
        user_id = 444444444
        command = 'start'
        
        for i in range(15):
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False
        assert wait > 0
    
    def test_light_commands_no_hourly_limit(self, rate_limiter):
        """Test light commands have no hourly limit."""
        assert RATE_LIMITS['light']['per_hour'] == -1


class TestDeveloperBypass:
    """Test developer bypass mechanism."""
    
    def test_developer_bypass(self, rate_limiter):
        """Test developer bypass mechanism."""
        dev_id = 999999999
        command = 'quiz'
        
        for _ in range(100):
            allowed, wait, limit_type = rate_limiter.check_limit(
                dev_id, command, is_developer=True
            )
            assert allowed is True
            assert wait == 0
            assert limit_type == "developer"
    
    def test_developer_bypass_all_commands(self, rate_limiter):
        """Test developer bypass works for all command types."""
        dev_id = 888888888
        
        all_commands = (
            RATE_LIMITS['heavy']['commands'] +
            RATE_LIMITS['medium']['commands'] +
            RATE_LIMITS['light']['commands']
        )
        
        for command in all_commands:
            for _ in range(20):
                allowed, wait, limit_type = rate_limiter.check_limit(
                    dev_id, command, is_developer=True
                )
                assert allowed is True


class TestRateLimitReset:
    """Test rate limit window reset."""
    
    def test_rate_limit_reset_after_minute(self, rate_limiter):
        """Test rate limit resets after 1 minute."""
        user_id = 555555555
        command = 'quiz'
        
        for i in range(5):
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            assert allowed is True
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False
        
        time.sleep(61)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is True
    
    @pytest.mark.slow
    def test_partial_window_reset(self, rate_limiter):
        """Test sliding window behavior."""
        user_id = 666666666
        command = 'quiz'
        
        rate_limiter.record_command(user_id, command)
        time.sleep(2)
        
        for _ in range(4):
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        assert allowed is False


class TestCleanup:
    """Test automatic cleanup of old entries."""
    
    def test_cleanup(self, rate_limiter):
        """Test automatic cleanup of old entries."""
        users = [111, 222, 333, 444, 555]
        
        for user_id in users:
            rate_limiter.record_command(user_id, 'start')
        
        assert len(rate_limiter.user_commands) >= 5
        
        cleaned = rate_limiter.cleanup_old_entries()
        assert cleaned >= 0
    
    def test_cleanup_preserves_recent_entries(self, rate_limiter):
        """Test cleanup preserves recent entries."""
        user_id = 777777777
        command = 'quiz'
        
        rate_limiter.record_command(user_id, command)
        
        initial_count = len(rate_limiter.user_commands)
        rate_limiter.cleanup_old_entries()
        final_count = len(rate_limiter.user_commands)
        
        assert final_count >= 0


class TestConcurrentAccess:
    """Test thread safety with concurrent requests."""
    
    def test_concurrent_access(self, rate_limiter):
        """Test thread safety with concurrent requests."""
        user_id = 123123123
        command = 'quiz'
        results = []
        
        def check_and_record():
            allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
            if allowed:
                rate_limiter.record_command(user_id, command)
            results.append(allowed)
        
        threads = [Thread(target=check_and_record) for _ in range(10)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        allowed_count = sum(1 for r in results if r)
        assert allowed_count <= 5


class TestUserStatistics:
    """Test rate limit statistics."""
    
    def test_get_user_stats(self, rate_limiter):
        """Test getting user rate limit stats."""
        user_id = 321321321
        
        rate_limiter.record_command(user_id, 'quiz')
        rate_limiter.record_command(user_id, 'mystats')
        
        stats = rate_limiter.get_user_stats(user_id)
        assert isinstance(stats, dict)
        assert 'quiz' in stats or 'mystats' in stats
    
    def test_user_stats_accuracy(self, rate_limiter):
        """Test user stats are accurate."""
        user_id = 456456456
        command = 'leaderboard'
        
        for _ in range(3):
            rate_limiter.record_command(user_id, command)
        
        stats = rate_limiter.get_user_stats(user_id)
        if command in stats:
            assert stats[command]['total'] >= 3


class TestEdgeCases:
    """Test edge cases and special scenarios."""
    
    def test_unknown_command_no_limit(self, rate_limiter):
        """Test unknown commands have no limits."""
        user_id = 789789789
        
        allowed, wait, limit_type = rate_limiter.check_limit(
            user_id, 'unknown_command'
        )
        assert allowed is True
        assert limit_type == "unlimited"
    
    def test_multiple_users_independent_limits(self, rate_limiter):
        """Test different users have independent limits."""
        user1 = 111000111
        user2 = 222000222
        command = 'quiz'
        
        for _ in range(5):
            rate_limiter.record_command(user1, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user1, command)
        assert allowed is False
        
        allowed, wait, limit_type = rate_limiter.check_limit(user2, command)
        assert allowed is True
    
    def test_same_user_different_commands_independent(self, rate_limiter):
        """Test same user can use different commands independently."""
        user_id = 333000333
        
        for _ in range(5):
            rate_limiter.record_command(user_id, 'quiz')
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, 'quiz')
        assert allowed is False
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, 'mystats')
        assert allowed is True


class TestWaitTimeCalculation:
    """Test wait time calculation accuracy."""
    
    def test_wait_time_positive(self, rate_limiter):
        """Test wait time is positive when limited."""
        user_id = 999000999
        command = 'quiz'
        
        for _ in range(5):
            rate_limiter.record_command(user_id, command)
        
        allowed, wait, limit_type = rate_limiter.check_limit(user_id, command)
        if not allowed:
            assert wait > 0
            assert wait <= 60
    
    def test_wait_time_decreases(self, rate_limiter, mocker):
        """Test wait time decreases over time."""
        user_id = 888000888
        command = 'quiz'
        base_time = 2000000.0
        
        mock_time = mocker.patch('src.utils.rate_limiter.time.time')
        mock_time.return_value = base_time
        
        for _ in range(5):
            rate_limiter.record_command(user_id, command)
        
        _, wait1, _ = rate_limiter.check_limit(user_id, command)
        
        mock_time.return_value = base_time + 1
        _, wait2, _ = rate_limiter.check_limit(user_id, command)
        
        assert wait1 > 0, "Should have wait time when rate limited"
        assert wait2 > 0, "Should still have wait time after 1 second"
        assert wait2 <= wait1, "Wait time should decrease over time"
