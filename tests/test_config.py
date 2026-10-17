from __future__ import annotations

from pathlib import Path

from bot.config import Settings


def test_defaults_and_upload_limit(tmp_path: Path):
    cfg = Settings(_env_file=None, bot_token="1:T", data_dir=tmp_path)
    assert cfg.upload_limit == 50 * 1024 * 1024
    assert cfg.max_upload_label == "50 MB"
    assert cfg.ai_enabled
    assert cfg.image_enabled
    assert not cfg.use_local_api

    local = Settings(_env_file=None, bot_token="1:T", api_server="http://127.0.0.1:8081")
    assert local.upload_limit == 2000 * 1024 * 1024
    assert local.max_upload_label == "2000 MB"

    custom = Settings(_env_file=None, bot_token="1:T", max_upload_mb=1500)
    assert custom.upload_limit == 1500 * 1024 * 1024


def test_admin_and_channel_parsing(tmp_path: Path):
    cfg = Settings(
        _env_file=None,
        bot_token="1:T",
        owner_ids=" 1, 2 ,bad",
        admin_ids="3",
        force_join_channels="@one, -100123 https://t.me/+abc",
        data_dir=tmp_path,
    )
    assert cfg.admins == {1, 2, 3}
    assert cfg.join_channels == ["@one", "-100123", "https://t.me/+abc"]


def test_dirs_created(tmp_path: Path):
    cfg = Settings(
        _env_file=None,
        bot_token="1:T",
        data_dir=tmp_path / "data",
        download_dir=tmp_path / "data" / "downloads",
        generated_dir=tmp_path / "data" / "generated",
        log_file=tmp_path / "data" / "x.log",
        db_path=tmp_path / "data" / "x.db",
    )
    cfg.ensure_dirs()
    assert (tmp_path / "data" / "downloads").is_dir()
    assert (tmp_path / "data" / "generated").is_dir()
