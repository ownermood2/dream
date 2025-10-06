#!/bin/bash
# Test Runner Script for MissQuiz Telegram Quiz Bot
# This script provides convenient commands for running tests

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}MissQuiz Test Runner${NC}"
echo "===================="
echo

# Parse command line arguments
COMMAND=${1:-"all"}

case $COMMAND in
  "all")
    echo -e "${YELLOW}Running all tests...${NC}"
    pytest -v
    ;;
    
  "fast")
    echo -e "${YELLOW}Running fast tests only...${NC}"
    pytest -v -m "not slow"
    ;;
    
  "coverage")
    echo -e "${YELLOW}Running tests with coverage...${NC}"
    pytest --cov=src --cov-report=term-missing --cov-report=html
    echo
    echo -e "${GREEN}Coverage report generated: htmlcov/index.html${NC}"
    ;;
    
  "database")
    echo -e "${YELLOW}Running database tests...${NC}"
    pytest -v tests/test_database.py
    ;;
    
  "quiz")
    echo -e "${YELLOW}Running quiz manager tests...${NC}"
    pytest -v tests/test_quiz.py
    ;;
    
  "rate-limiter")
    echo -e "${YELLOW}Running rate limiter tests...${NC}"
    pytest -v tests/test_rate_limiter.py
    ;;
    
  "handlers")
    echo -e "${YELLOW}Running handler tests...${NC}"
    pytest -v tests/test_handlers.py
    ;;
    
  "commands")
    echo -e "${YELLOW}Running developer command tests...${NC}"
    pytest -v tests/test_commands.py
    ;;
    
  "ci")
    echo -e "${YELLOW}Running tests as in CI...${NC}"
    pytest --cov=src --cov-report=xml --cov-fail-under=70 -v
    ;;
    
  "debug")
    echo -e "${YELLOW}Running tests in debug mode...${NC}"
    pytest -vvs --tb=long
    ;;
    
  "parallel")
    echo -e "${YELLOW}Running tests in parallel...${NC}"
    if ! command -v pytest-xdist &> /dev/null; then
      echo -e "${RED}pytest-xdist not installed. Installing...${NC}"
      pip install pytest-xdist
    fi
    pytest -n auto -v
    ;;
    
  "clean")
    echo -e "${YELLOW}Cleaning test artifacts...${NC}"
    rm -rf .pytest_cache htmlcov .coverage
    echo -e "${GREEN}Cleaned test artifacts${NC}"
    ;;
    
  "help")
    echo "Usage: ./run_tests.sh [command]"
    echo
    echo "Commands:"
    echo "  all         - Run all tests (default)"
    echo "  fast        - Run only fast tests (skip slow)"
    echo "  coverage    - Run tests with coverage report"
    echo "  database    - Run database tests only"
    echo "  quiz        - Run quiz manager tests only"
    echo "  rate-limiter- Run rate limiter tests only"
    echo "  handlers    - Run handler tests only"
    echo "  commands    - Run developer command tests only"
    echo "  ci          - Run tests as in CI (with coverage threshold)"
    echo "  debug       - Run tests in debug mode (verbose)"
    echo "  parallel    - Run tests in parallel"
    echo "  clean       - Clean test artifacts"
    echo "  help        - Show this help message"
    ;;
    
  *)
    echo -e "${RED}Unknown command: $COMMAND${NC}"
    echo "Run './run_tests.sh help' for usage information"
    exit 1
    ;;
esac
