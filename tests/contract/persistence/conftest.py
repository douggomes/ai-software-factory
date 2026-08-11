"""Pytest configuration and fixtures for contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SQLiteRunStore]:
    """Provide a SQLiteRunStore instance for contract tests."""
    db_path = tmp_path / "contract_test.db"
    store = await SQLiteRunStore.create(db_path)
    try:
        yield store
    finally:
        await store.close()
