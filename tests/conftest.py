import pytest


@pytest.fixture(autouse=True)
def _isolate_local_app_data(monkeypatch, tmp_path):
    """Never let tests write cache/log state into the developer's real profile."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
