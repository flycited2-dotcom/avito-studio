import logging

from avito_studio.diagnostics import configure_logging


def test_configure_logging_writes_utf8_windowed_diagnostics(tmp_path):
    path = configure_logging(tmp_path)
    logging.getLogger("avito_studio.test").warning("проверка журнала")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert path == tmp_path / "studio.log"
    assert "проверка журнала" in path.read_text(encoding="utf-8")
