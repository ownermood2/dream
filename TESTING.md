# Testing Guide for MissQuiz Telegram Quiz Bot

This document provides comprehensive instructions for running and maintaining the test suite for the MissQuiz Telegram Quiz Bot.

## Table of Contents

- [Quick Start](#quick-start)
- [Test Structure](#test-structure)
- [Running Tests](#running-tests)
- [Test Coverage](#test-coverage)
- [Writing New Tests](#writing-new-tests)
- [Troubleshooting](#troubleshooting)

## Quick Start

### Install Test Dependencies

Test dependencies are already included in `requirements.txt`:

```bash
pip install -r requirements.txt
```

The following test packages will be installed:
- `pytest>=7.0.0` - Testing framework
- `pytest-asyncio>=0.21.0` - Async test support
- `pytest-cov>=4.0.0` - Coverage reporting
- `pytest-mock>=3.10.0` - Mocking utilities

### Run All Tests

```bash
# Run all tests with default configuration
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=src --cov-report=html
```

## Test Structure

The test suite is organized as follows:

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Shared fixtures and configuration
├── test_database.py         # Database layer tests (90%+ coverage target)
├── test_quiz.py             # Quiz manager tests (85%+ coverage target)
├── test_rate_limiter.py     # Rate limiting tests (90%+ coverage target)
├── test_handlers.py         # Bot handler integration tests (70%+ coverage target)
└── test_commands.py         # Developer command tests (70%+ coverage target)
```

### Test Categories

#### 1. Database Tests (`test_database.py`)
Tests all database operations including:
- Schema creation and initialization
- Question CRUD operations
- User statistics and leaderboard
- Developer access management
- Quiz attempts and history
- Activity logging and metrics

#### 2. Quiz Manager Tests (`test_quiz.py`)
Tests quiz business logic:
- Question loading from JSON
- Random question selection with anti-repetition
- Answer validation
- Category filtering
- Score tracking and leaderboards
- Data persistence

#### 3. Rate Limiter Tests (`test_rate_limiter.py`)
Tests rate limiting functionality:
- Heavy command limits (5/min, 20/hr)
- Medium command limits (10/min, 50/hr)
- Light command limits (15/min)
- Developer bypass mechanism
- Rate limit window reset
- Concurrent access safety

#### 4. Handler Tests (`test_handlers.py`)
Integration tests for bot handlers:
- Command handlers (/start, /help, /quiz, etc.)
- Rate limit enforcement
- Private vs group chat behavior
- User tracking and PM access
- Poll answer handling

#### 5. Developer Command Tests (`test_commands.py`)
Tests developer-only features:
- Add/Edit/Delete quiz questions
- Broadcast messages
- Bot statistics and diagnostics
- Access control enforcement

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_database.py
pytest tests/test_rate_limiter.py

# Run specific test class
pytest tests/test_database.py::TestQuestionOperations

# Run specific test method
pytest tests/test_database.py::TestQuestionOperations::test_add_question

# Run with verbose output
pytest -v

# Run with short traceback
pytest --tb=short

# Run with line-level traceback
pytest --tb=line
```

### Test Markers

Tests can be marked with custom markers for selective execution:

```bash
# Run only fast tests (skip slow tests)
pytest -m "not slow"

# Run only integration tests
pytest -m integration

# Run only async tests
pytest -m asyncio
```

### Parallel Execution

For faster test execution, you can run tests in parallel:

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel (auto-detect CPU cores)
pytest -n auto

# Run tests using 4 workers
pytest -n 4
```

## Test Coverage

### Generate Coverage Report

```bash
# Run tests with coverage
pytest --cov=src

# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Generate terminal report with missing lines
pytest --cov=src --cov-report=term-missing

# Generate XML report (for CI/CD)
pytest --cov=src --cov-report=xml
```

### View HTML Coverage Report

After generating the HTML report:

```bash
# The report is saved to htmlcov/index.html
# Open it in your browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Coverage Goals

The test suite targets the following coverage levels:

- **Database operations**: 90%+ coverage
- **Quiz manager**: 85%+ coverage
- **Rate limiter**: 90%+ coverage
- **Command handlers**: 70%+ coverage
- **Developer commands**: 70%+ coverage
- **Overall**: 70%+ coverage

### Current Coverage

To check current coverage:

```bash
pytest --cov=src --cov-report=term-missing --cov-fail-under=70
```

This will fail if coverage drops below 70%.

## Writing New Tests

### Using Fixtures

The test suite provides several fixtures in `conftest.py`:

```python
def test_example(test_db, quiz_manager, rate_limiter):
    """Example test using fixtures."""
    # test_db: Clean database instance
    # quiz_manager: Configured quiz manager
    # rate_limiter: Fresh rate limiter instance
    
    question_id = test_db.add_question(
        "What is 2+2?",
        ["3", "4", "5", "6"],
        1,
        "Math",
        "easy"
    )
    
    assert question_id > 0
```

### Mock Telegram Objects

Use mock fixtures for Telegram objects:

```python
@pytest.mark.asyncio
async def test_command(mock_update, mock_context):
    """Test command with mock Telegram objects."""
    await some_command_handler(mock_update, mock_context)
    
    # Assert on mock calls
    mock_update.message.reply_text.assert_called_once()
```

### Async Tests

Mark async tests with `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_function():
    """Test async functionality."""
    result = await some_async_function()
    assert result is not None
```

### Testing Edge Cases

Always test edge cases:

```python
def test_edge_cases(test_db):
    """Test edge cases and error handling."""
    # Empty data
    result = test_db.get_question_by_id(99999)
    assert result is None
    
    # Invalid input
    with pytest.raises(ValidationError):
        test_db.add_question("", [], 0, "", "")
```

## Continuous Integration

### GitHub Actions

The repository includes a GitHub Actions workflow for CI (optional):

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest --cov --cov-report=xml
      - uses: codecov/codecov-action@v3
```

### Local CI Simulation

Run tests as they would run in CI:

```bash
# Clean environment
rm -rf .pytest_cache htmlcov .coverage

# Install dependencies
pip install -r requirements.txt

# Run tests with coverage
pytest --cov=src --cov-report=xml --cov-fail-under=70
```

## Troubleshooting

### Common Issues

#### 1. Import Errors

If you see import errors:

```bash
# Ensure PYTHONPATH is set
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Or run pytest with Python module syntax
python -m pytest
```

#### 2. Async Test Failures

If async tests fail with "no event loop":

```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio

# Check pytest.ini has asyncio_mode = auto
cat pytest.ini | grep asyncio_mode
```

#### 3. Database Lock Errors

If you see database lock errors:

```bash
# Stop the bot before running tests
# Tests use in-memory databases to avoid conflicts
```

#### 4. Slow Tests

If tests are too slow:

```bash
# Run only fast tests
pytest -m "not slow"

# Run specific test files
pytest tests/test_rate_limiter.py

# Use parallel execution
pytest -n auto
```

### Debug Mode

Run tests in debug mode:

```bash
# Show print statements
pytest -s

# Show full traceback
pytest --tb=long

# Drop into debugger on failure
pytest --pdb

# Verbose with full output
pytest -vvs
```

## Best Practices

### 1. Test Isolation

- Each test should be independent
- Use fixtures for setup and teardown
- Don't rely on test execution order

### 2. Mock External Services

- Mock all Telegram API calls
- Don't send real messages during tests
- Use in-memory databases for speed

### 3. Meaningful Assertions

```python
# Good
assert user_stats['total_attempts'] == 5
assert question['category'] == "Math"

# Bad
assert user_stats
assert question
```

### 4. Test Naming

- Use descriptive test names
- Follow pattern: `test_<what>_<condition>_<expected_result>`
- Example: `test_rate_limit_exceeded_returns_wait_time`

### 5. Coverage

- Aim for high coverage but don't chase 100%
- Focus on critical paths and business logic
- Test both success and failure cases

## Quick Reference

### Essential Commands

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific file
pytest tests/test_database.py

# Run with verbose output
pytest -v

# Run fast tests only
pytest -m "not slow"

# Debug mode
pytest -vvs --tb=long

# Parallel execution
pytest -n auto
```

### Fixture Reference

- `test_db` - Clean SQLite database instance
- `quiz_manager` - Configured quiz manager
- `rate_limiter` - Fresh rate limiter instance
- `mock_update` - Mock Telegram Update object
- `mock_context` - Mock Telegram Context object
- `mock_user` - Mock Telegram User object
- `mock_chat` - Mock Telegram Chat object
- `mock_message` - Mock Telegram Message object
- `sample_questions` - Sample quiz questions list

## Resources

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [python-telegram-bot Testing](https://docs.python-telegram-bot.org/en/stable/examples/testing.html)

## Support

For issues or questions:
1. Check this documentation
2. Review test examples in the test files
3. Check pytest documentation
4. Open an issue on GitHub
