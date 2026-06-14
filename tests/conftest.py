"""
Pytest configuration for J.A.R.V.I.S tests.
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: smoke test (requires live API keys)")
    config.addinivalue_line("markers", "windows: Windows-only test")
    config.addinivalue_line("markers", "macos: macOS-only test")
    config.addinivalue_line("markers", "slow: slow test (>10s)")
    config.addinivalue_line("markers", "integration: integration test (requires external service)")


def pytest_collection_modifyitems(config, items):
    """Skip tests based on platform markers."""
    import platform

    for item in items:
        if "windows" in item.keywords and platform.system() != "Windows":
            item.add_marker(pytest.mark.skip(reason="Windows-only test"))
        if "macos" in item.keywords and platform.system() != "Darwin":
            item.add_marker(pytest.mark.skip(reason="macOS-only test"))
