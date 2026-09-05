"""Readiness check a student can run before asking for help.

Every check answers one question in plain Thai: is this piece ready, and if not,
what single command fixes it. The exit code lets the setup script decide whether
to keep going, so the messages here are the only troubleshooting guide a student
needs for the common cases.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MINIMUM_PYTHON = (3, 11)
# The SEC rejects a request whose contact address cannot receive mail, so a
# placeholder left in .env fails later with a 403 that looks like a network fault.
PLACEHOLDER_EMAILS = {"your.real.email@example.com", "you@example.com", ""}
FRESH_PRICE_DAYS = 5


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""

    @property
    def mark(self) -> str:
        return "[ ผ่าน ]" if self.ok else "[ ขาด ]"


def _python_check() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info >= MINIMUM_PYTHON:
        return Check("Python", True, f"เวอร์ชัน {version}")
    return Check(
        "Python",
        False,
        f"เวอร์ชัน {version} เก่าเกินไป",
        "ติดตั้ง Python 3.12 จาก https://www.python.org/downloads/ แล้วติ๊ก Add Python to PATH",
    )


def _contact_check() -> Check:
    from .local_config import get_setting
    from .sec_edgar import SEC_CONTACT_SETTING

    contact = (get_setting(SEC_CONTACT_SETTING) or "").strip()
    if contact.lower() in PLACEHOLDER_EMAILS:
        return Check(
            "อีเมลติดต่อ SEC",
            False,
            "ยังไม่ได้ใส่อีเมลจริง" if not contact else f"ยังเป็นค่าตัวอย่าง: {contact}",
            "เปิดไฟล์ .env แล้วแก้ FASTDEEP_SEC_CONTACT ให้เป็นอีเมลจริงของตัวเอง",
        )
    if "@" not in contact or "." not in contact.split("@")[-1]:
        return Check(
            "อีเมลติดต่อ SEC",
            False,
            f"รูปแบบอีเมลไม่ถูกต้อง: {contact}",
            "แก้ FASTDEEP_SEC_CONTACT ในไฟล์ .env ให้เป็นอีเมลที่ใช้งานได้จริง",
        )
    return Check("อีเมลติดต่อ SEC", True, contact)


def _universe_check() -> Check:
    path = ROOT / "data" / "fastdeep_universe.csv"
    if not path.exists():
        return Check(
            "รายชื่อหุ้น",
            False,
            "ไม่พบ data/fastdeep_universe.csv",
            "ไฟล์นี้มากับโปรเจกต์ ถ้าหายให้ดาวน์โหลดโปรเจกต์ใหม่",
        )
    # Counting raw lines double-counts, because some fields carry newlines.
    import csv

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = sum(1 for _ in csv.DictReader(handle))
    return Check("รายชื่อหุ้น", True, f"{rows:,} ตัว")


def _price_check() -> Check:
    path = ROOT / "data" / "fastdeep_prices.csv"
    fix = "รันคำสั่ง: python -m fastdeep_scanner update-prices --universe data/fastdeep_universe.csv --out data/fastdeep_prices.csv --range 5y --interval 1d --workers 6"
    if not path.exists():
        return Check("ราคาหุ้น", False, "ยังไม่ได้ดึงราคา", fix)
    size_mb = path.stat().st_size / 1_048_576
    # The status file describes the run in progress and is left behind when one
    # is killed. The source file records what actually landed in the CSV, so ask
    # it first and only fall back to the status.
    latest = ""
    for candidate in ("fastdeep_prices_source.json", "fastdeep_price_update_status.json"):
        meta_path = ROOT / "data" / candidate
        if not meta_path.exists():
            continue
        try:
            latest = str(json.loads(meta_path.read_text(encoding="utf-8")).get("latest_candle_date") or "")
        except (OSError, json.JSONDecodeError):
            latest = ""
        if latest:
            break
    if not latest:
        return Check("ราคาหุ้น", True, f"{size_mb:,.0f} MB (ไม่ทราบวันที่ล่าสุด)")
    try:
        age = (date.today() - date.fromisoformat(latest)).days
    except ValueError:
        return Check("ราคาหุ้น", True, f"{size_mb:,.0f} MB, ล่าสุด {latest}")
    if age > FRESH_PRICE_DAYS:
        return Check("ราคาหุ้น", False, f"ล่าสุด {latest} (เก่า {age} วัน)", fix)
    return Check("ราคาหุ้น", True, f"{size_mb:,.0f} MB, ล่าสุด {latest}")


def _financial_check() -> Check:
    cache = ROOT / "data" / "financial_cache"
    fix = "รันคำสั่ง: python -m fastdeep_scanner update-sec-financials --universe data/fastdeep_universe.csv --cache-dir data/financial_cache --groups SP500,NASDAQ100,SP400"
    if not cache.exists():
        return Check("งบการเงิน", False, "ยังไม่ได้ดึงงบ", fix)
    count = sum(1 for _ in cache.glob("*.json"))
    if count < 100:
        return Check("งบการเงิน", False, f"มีแค่ {count} บริษัท (ยังไม่ครบ)", fix)
    return Check("งบการเงิน", True, f"{count:,} บริษัท")


def _filing_check() -> Check:
    path = ROOT / "data" / "fastdeep_filing_profiles.json"
    if not path.exists():
        return Check(
            "ข้อมูลธุรกิจภาษาไทย",
            False,
            "ไม่พบไฟล์",
            "ไฟล์นี้มากับโปรเจกต์ ถ้าหายให้ดาวน์โหลดโปรเจกต์ใหม่",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Check("ข้อมูลธุรกิจภาษาไทย", False, "ไฟล์เสียหาย", "ดาวน์โหลดโปรเจกต์ใหม่")
    # The companies live under "profiles"; the rest of the file is metadata.
    entries = len(payload.get("profiles") or {}) if isinstance(payload, dict) else len(payload)
    return Check("ข้อมูลธุรกิจภาษาไทย", True, f"{entries:,} บริษัท")


def _hall_check() -> Check:
    path = ROOT / "data" / "fastdeep_hall_prices.csv"
    if not path.exists():
        return Check(
            "Hall of Fame (ไม่บังคับ)",
            True,
            "ยังไม่มี - แท็บนี้จะว่าง แต่ส่วนอื่นใช้ได้ปกติ",
            "ถ้าต้องการ: python -m fastdeep_scanner update-prices --universe data/fastdeep_universe.csv --out data/fastdeep_hall_prices.csv --range 10y --interval 1mo",
        )
    return Check("Hall of Fame (ไม่บังคับ)", True, f"{path.stat().st_size / 1_048_576:,.0f} MB")


def _disk_check() -> Check:
    import shutil

    free_gb = shutil.disk_usage(ROOT).free / 1_073_741_824
    if free_gb < 1.5:
        return Check(
            "พื้นที่ว่าง",
            False,
            f"เหลือ {free_gb:.1f} GB",
            "ต้องการอย่างน้อย 1.5 GB - ลบไฟล์ที่ไม่ใช้แล้วลองใหม่",
        )
    return Check("พื้นที่ว่าง", True, f"เหลือ {free_gb:.1f} GB")


def run_doctor() -> int:
    """Print the readiness report. Returns the number of blocking problems."""
    checks = [
        _python_check(),
        _disk_check(),
        _contact_check(),
        _universe_check(),
        _filing_check(),
        _price_check(),
        _financial_check(),
        _hall_check(),
    ]
    width = max(len(check.name) for check in checks)
    print()
    print("  ตรวจความพร้อมของ FastDeep Scanner")
    print("  " + "-" * (width + 46))
    for check in checks:
        print(f"  {check.mark} {check.name.ljust(width)}  {check.detail}")
    problems = [check for check in checks if not check.ok]
    print()
    if not problems:
        print("  พร้อมใช้งานครบทุกอย่าง")
        print("  เปิดโปรแกรมด้วย: OPEN_FASTDEEP_SCANNER.bat")
        print()
        return 0
    print(f"  ยังขาดอยู่ {len(problems)} อย่าง - แก้ตามนี้ทีละข้อ")
    print()
    for index, check in enumerate(problems, start=1):
        print(f"  {index}. {check.name}: {check.detail}")
        if check.fix:
            print(f"     วิธีแก้ - {check.fix}")
        print()
    return len(problems)
