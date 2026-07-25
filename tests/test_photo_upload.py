from PIL import Image
import pytest

from avito_studio import photo_upload
from avito_studio.photo_upload import (
    is_safe_nc_code,
    upload_manual_photo,
    upload_manual_photo_bytes,
)


class FakeSsh:
    def __init__(self):
        self.run_calls = []
        self.put_calls = []

    def run(self, cmd):
        self.run_calls.append(cmd)
        return ""

    def put(self, remote_path, data):
        self.put_calls.append((remote_path, data))


def test_upload_manual_photo_converts_to_jpeg_and_returns_public_url(tmp_path):
    src = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color="red").save(src)
    ssh = FakeSsh()
    url = upload_manual_photo(ssh, src, "НС-42")
    assert url.startswith(
        "https://splithome.ru/static/manual-photos/НС-42-"
    )
    assert url.endswith(".jpg")
    assert len(ssh.put_calls) == 1
    remote_path, data = ssh.put_calls[0]
    assert remote_path.startswith(
        "/opt/oasis/staticfiles/manual-photos/.НС-42-"
    )
    assert remote_path.endswith(".tmp")
    assert data[:2] == b"\xff\xd8"   # JPEG-магия — реально сконвертировано, не сырой PNG
    assert any("install -d -m 755" in c for c in ssh.run_calls)
    promote = next(c for c in ssh.run_calls if "mv -f --" in c)
    assert remote_path in promote
    assert url.rsplit("/", 1)[-1] in promote


def test_safe_nc_code_rejects_product_title_but_accepts_internal_code():
    assert is_safe_nc_code("НС-1480532")
    assert is_safe_nc_code("RC-GR28HN")
    assert not is_safe_nc_code("Инвертор ROYAL CLIMA RC-GR28HN")
    assert not is_safe_nc_code("x" * 81)


def test_failed_atomic_promotion_cleans_candidate_without_touching_final(tmp_path):
    class FailingSsh(FakeSsh):
        def run(self, cmd):
            self.run_calls.append(cmd)
            if "mv -f --" in cmd:
                raise RuntimeError("connection dropped before rename")
            return ""

    src = tmp_path / "photo.png"
    Image.new("RGB", (4, 4), color="blue").save(src)
    ssh = FailingSsh()

    with pytest.raises(RuntimeError, match="connection dropped"):
        upload_manual_photo(ssh, src, "НС-42")

    assert any("rm -f --" in call for call in ssh.run_calls)
    # The only uploaded path is hidden and versioned; the legacy live path is
    # never passed to SFTP and therefore cannot be truncated.
    assert ssh.put_calls[0][0].split("/")[-1].startswith(".НС-42-")
    assert ssh.put_calls[0][0] != (
        "/opt/oasis/staticfiles/manual-photos/НС-42.jpg"
    )


def test_oversized_source_is_rejected_before_image_decoder_or_ssh(monkeypatch):
    monkeypatch.setattr(photo_upload, "MAX_SOURCE_BYTES", 4)
    ssh = FakeSsh()

    with pytest.raises(ValueError, match="безопасный предел"):
        upload_manual_photo_bytes(ssh, b"12345", "НС-42")

    assert ssh.run_calls == []
    assert ssh.put_calls == []
