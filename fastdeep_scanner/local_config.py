"""ค่าตั้งเฉพาะเครื่องที่ไม่ควรอยู่ในซอร์สที่ push ขึ้น GitHub

อ่านจาก ``.env`` ที่รากโปรเจกต์ ซึ่ง gitignore ไว้แล้ว รองรับทั้งรูปแบบ
``NAME=value`` และ ``$env:NAME=value`` ที่สคริปต์ PowerShell ในเครื่องนี้ใช้อยู่
ตัวแปรแวดล้อมจริงมาก่อนไฟล์เสมอ เพื่อให้ตั้งค่าชั่วคราวตอนรันได้
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = ROOT / ".env"


@lru_cache(maxsize=4)
def _read_env_file(path_text: str, modified_ns: int) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path_text).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.lower().startswith("$env:"):
            name = name[5:]
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values


def load_local_env(path: str | Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return _read_env_file(str(path.resolve()), path.stat().st_mtime_ns)
    except OSError:
        return {}


def get_setting(name: str, default: str = "", *, env_path: str | Path = DEFAULT_ENV_PATH) -> str:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    return (load_local_env(env_path).get(name) or default).strip()
