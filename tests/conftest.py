from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from bot.config import Settings
from bot.db import Database, Repository


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:TEST_TOKEN",
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test.db",
        download_dir=tmp_path / "data" / "downloads",
        generated_dir=tmp_path / "data" / "generated",
        log_file=tmp_path / "data" / "test.log",
        health_port=0,
    )


@pytest_asyncio.fixture()
async def repo(tmp_path: Path) -> Repository:
    db = Database(tmp_path / "test.db")
    await db.connect()
    repository = Repository(db)
    yield repository
    await db.close()
