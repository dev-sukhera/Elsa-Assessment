import pytest

from quiz_server.config import Settings


def test_from_env_reads_overrides(monkeypatch):
    monkeypatch.setenv("QUIZ_STORE", "redis")
    monkeypatch.setenv("QUIZ_LEADERBOARD_TOP_N", "25")
    monkeypatch.setenv("QUIZ_RATE_LIMIT_PER_S", "2.5")
    monkeypatch.setenv("QUIZ_REDIS_MAX_CONNECTIONS", "32")
    settings = Settings.from_env()
    assert settings.store_backend == "redis"
    assert settings.leaderboard_top_n == 25
    assert settings.rate_limit_per_s == 2.5
    assert settings.redis_max_connections == 32


def test_defaults_without_env(monkeypatch):
    for name in ("QUIZ_STORE", "QUIZ_LEADERBOARD_TOP_N"):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env() == Settings()


def test_unknown_store_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("QUIZ_STORE", "reddis")
    with pytest.raises(ValueError, match="QUIZ_STORE"):
        Settings.from_env()
