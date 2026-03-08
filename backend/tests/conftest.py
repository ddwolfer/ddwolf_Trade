"""Shared pytest fixtures for the crypto backtest test suite."""
import pytest
import os
import sys

# Ensure backend is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
