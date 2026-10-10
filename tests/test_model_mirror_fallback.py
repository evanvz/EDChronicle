"""Model downloads fall back to the EDChronicle-models mirror when the original
source fails, and a file with the wrong checksum is never accepted from either."""
import hashlib
from unittest.mock import patch

import download_models as dm

GOOD = b"model bytes"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()


def _fake_download(responses):
    def fake(url, dest, reporthook=None):
        body = responses[url]
        if isinstance(body, Exception):
            raise body
        open(dest, "wb").write(body)
    return fake


def test_fetch_falls_back_to_mirror(tmp_path):
    dest = tmp_path / "f.bin"
    fake = _fake_download({"orig": OSError("404"), "mirror": GOOD})
    with patch.object(dm.urllib.request, "urlretrieve", fake):
        assert dm._fetch(["orig", "mirror"], dest, GOOD_SHA, "[t]")
    assert dest.read_bytes() == GOOD


def test_fetch_rejects_bad_checksum_everywhere(tmp_path):
    dest = tmp_path / "f.bin"
    fake = _fake_download({"orig": b"tampered", "mirror": b"also wrong"})
    with patch.object(dm.urllib.request, "urlretrieve", fake):
        assert not dm._fetch(["orig", "mirror"], dest, GOOD_SHA, "[t]")
    assert not dest.exists()


def test_vosk_runtime_download_falls_back_to_mirror(tmp_path):
    import io
    import zipfile
    from edc.audio import voice_commands as vc
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vosk-model-x/README", "model")
    zip_bytes = buf.getvalue()
    orig, mirror = vc.MODEL_URLS

    def fake(url, path):
        if url == orig:
            raise OSError("gone")
        open(path, "wb").write(zip_bytes)

    with patch.object(vc.urllib.request, "urlretrieve", fake), \
         patch.object(vc, "MODEL_SHA256", hashlib.sha256(zip_bytes).hexdigest()):
        assert vc.ensure_model(tmp_path) == tmp_path / vc.MODEL_DIR_NAME
    assert (tmp_path / vc.MODEL_DIR_NAME / "README").exists()
