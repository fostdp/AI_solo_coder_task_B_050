"""
pytest 配置
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

pytest_plugins = ["pytest_asyncio"]
