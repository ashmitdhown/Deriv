"""Small helpers: text normalization, safe JSON I/O, atomic writes, logging."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

_CONTROL_RE = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f-\u009f​-‏‪-‮⁠-⁤﻿]")
_WS_RE = re.compile(r"\s+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")

MAX_INPUT_FILE_BYTES = 5 * 1024 * 1024


def normalize_text(text: str) -> str:
    """NFKC-normalize, drop control / zero-width / bidi characters, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text) if s.strip()]


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class InputFileError(Exception):
    """Raised when an input file is missing, too large, or not valid JSON of the right shape."""


def load_json_list(path: Path) -> list[Any]:
    """Load a JSON array from disk with size limits. Never evaluates content."""
    path = Path(path)
    if not path.is_file():
        raise InputFileError(f"{path.name}: file not found")
    if path.stat().st_size > MAX_INPUT_FILE_BYTES:
        raise InputFileError(f"{path.name}: file exceeds {MAX_INPUT_FILE_BYTES} bytes")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise InputFileError(f"{path.name}: invalid JSON ({e.__class__.__name__})") from None
    if not isinstance(data, list):
        raise InputFileError(f"{path.name}: top-level value must be a JSON array")
    return data


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    """Write to a temp file in the same directory, fsync, then os.replace (atomic on POSIX/NTFS)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def get_logger(name: str) -> logging.Logger:
    from src.config import settings

    logging.basicConfig(
        level=settings.log_level.upper() if settings.log_level.upper() in logging._nameToLevel else "INFO",
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return logging.getLogger(name)
