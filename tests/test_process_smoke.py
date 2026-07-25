"""Real process-level smoke for the same entry point used by the Windows EXE."""
from __future__ import annotations

import os
import subprocess
import sys


def test_module_entry_point_opens_and_exits_without_network(tmp_path):
    bridge = tmp_path / "bridge"
    (bridge / "config").mkdir(parents=True)
    (bridge / "config" / "config.yaml").write_text(
        "catalog: {selected_series: []}\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["AVITO_STUDIO_BRIDGE_ROOT"] = str(bridge)
    environment["LOCALAPPDATA"] = str(tmp_path / "local-app-data")

    result = subprocess.run(
        [sys.executable, "-m", "avito_studio", "--smoke-test"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
