import tomllib
from pathlib import Path

from avito_studio.version import __version__, bridge_revision


def test_release_and_bridge_metadata_are_valid():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version_info = (root / "packaging" / "windows_version_info.txt").read_text(
        encoding="utf-8"
    )
    assert __version__ == "0.3.0"
    assert project["project"]["version"] == __version__
    assert f"StringStruct('FileVersion', '{__version__}.0')" in version_info
    revision = bridge_revision()
    assert revision == "development" or (
        len(revision) == 40
        and revision == revision.lower()
        and all(character in "0123456789abcdef" for character in revision)
    )
