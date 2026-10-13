"""Display-only brand names and private, persistent manufacturer logos."""
import hashlib
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


BRANDS = ("KALMAR", "TRITON", "CROWN", "HYUNDAI", "BOBCAT", "KUBOTA",
          "HOWO", "TVH", "HUSQVARNA", "LIEBHERR")
MAX_LOGO_BYTES = 1024 * 1024


def brand_name(value):
    raw = str(value or "").strip()
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().upper()
    tokens = set(re.findall(r"[A-Z0-9]+", normalized))
    matches = [name for name in BRANDS if name in tokens]
    return matches[0] if len(matches) == 1 else raw


def logo_directory(db_path):
    return Path(os.getenv("WMS_BRAND_LOGO_DIR") or Path(db_path).parent / "brand-logos").resolve()


@lru_cache(maxsize=32)
def _logo_bytes(path, modified, size):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        return None
    mime = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if data.startswith(b"\xff\xd8\xff") else ""
    return (data, mime, hashlib.sha256(data).hexdigest()) if mime else None


def logo_asset(name, db_path):
    if name not in BRANDS:
        return None
    try:
        root = logo_directory(db_path)
        candidates = []
        for extension in (".png", ".jpg", ".jpeg"):
            candidate = (root / (name.lower() + extension)).resolve()
            if candidate.parent == root and candidate.is_file():
                candidates.append(candidate)
        if len(candidates) != 1:
            return None
        stat = candidates[0].stat()
        if stat.st_size > MAX_LOGO_BYTES:
            return None
        return _logo_bytes(str(candidates[0]), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def label_brand(value, db_path):
    name = brand_name(value)
    asset = logo_asset(name, db_path)
    return {"label_brand": name, "brand_logo_url":
            "/api/reception-brand-logo?brand=" + name + "&v=" + asset[2] if asset else ""}
