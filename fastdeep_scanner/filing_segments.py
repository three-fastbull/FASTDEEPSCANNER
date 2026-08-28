"""รายได้แยกตามส่วนงานจากตารางในงบที่ยื่นต่อ SEC

โครงสร้างตารางของแต่ละบริษัทต่างกันมาก การเดาว่าแถวไหนคือส่วนงานจึงผิดได้ง่าย
และตัวเลขผิดที่ดูน่าเชื่อถือแย่กว่าการเว้นว่าง

ตัวตัดสินจึงเป็นเลขคณิต: เก็บเฉพาะชุดที่ผลรวมของส่วนย่อยเท่ากับยอดรวมที่รายงานไว้
ถ้าไม่ตรงแปลว่าจับผิดมิติหรือผิดตาราง และจะไม่บันทึกอะไรเลย
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from typing import Any

from .sec_edgar import _sec_contact, _sec_user_agent


FILING_SUMMARY = "{base}/FilingSummary.xml"
# ชื่อรายงานที่มักบรรจุตารางแยกรายได้ ต้องเป็นหน้า Details ที่มีตัวเลขจริง
REPORT_PATTERN = re.compile(
    r"(disaggregat|net sales|net operating revenue|revenue by|segment (information|data|reporting))",
    re.I,
)
DETAIL_PATTERN = re.compile(r"detail", re.I)
REVENUE_ROW = re.compile(
    r"^(net sales|net operating revenues?|revenues?|total revenues?|net revenues?|sales)$", re.I
)
# แถวเหล่านี้เป็นข้อมูลเชิงเทคนิคของไฟล์ ไม่ใช่ชื่อส่วนงาน
NOISE_LABEL = re.compile(r"Details|Axis|Line Items|Abstract|\$ in |Member|\[|^\s*$", re.I)
RECONCILE_TOLERANCE = 0.005


def _download(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _sec_user_agent(),
            "From": _sec_contact(),
            "Accept": "*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _to_number(text: str) -> float | None:
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if negative else value


def parse_table(raw: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S):
        cells = [
            re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", block, re.S)
        ]
        cells = [cell for cell in cells if cell]
        if not cells:
            continue
        values = [
            value
            for value in (_to_number(cell) for cell in cells[1:])
            if value is not None
        ]
        rows.append({"label": cells[0], "values": values})
    return rows


def unit_scale(rows: list[dict[str, Any]]) -> tuple[float, str]:
    """หน่วยของตารางอยู่ในหัวตาราง เช่น ``$ in Millions``"""
    header = rows[0]["label"] if rows else ""
    currency = "USD" if "USD" in header or "$" in header else ""
    if re.search(r"in Billions", header, re.I):
        return 1_000_000_000, currency
    if re.search(r"in Millions", header, re.I):
        return 1_000_000, currency
    if re.search(r"in Thousands", header, re.I):
        return 1_000, currency
    return 1.0, currency


def segments_from_rows(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """จับคู่ชื่อกลุ่มกับตัวเลขรายได้

    ตาราง R ของ SEC วางชื่อมิติไว้ในแถวที่ไม่มีตัวเลข แล้วตามด้วยแถวตัวเลขของ
    แต่ละรายการ ชื่อกลุ่มล่าสุดจึงเป็นเจ้าของแถวตัวเลขที่ตามมา
    """
    current = ""
    found: list[tuple[str, float]] = []
    for row in rows:
        label = row["label"]
        if not row["values"]:
            if not NOISE_LABEL.search(label) and len(label) < 90:
                current = label
            continue
        if REVENUE_ROW.match(label.strip()) and current:
            found.append((current, row["values"][0]))
    return found


def reconciled_segments(pairs: list[tuple[str, float]]) -> dict[str, Any] | None:
    """เก็บเฉพาะชุดที่ส่วนย่อยบวกกลับได้ตรงยอดรวม

    ยอดรวมคือค่าที่มากที่สุด ส่วนที่เหลือคือส่วนย่อย ถ้าบวกแล้วไม่ตรงแปลว่าตาราง
    ปนหลายมิติ เช่น แยกตามสินค้าและตามภูมิภาคพร้อมกัน ซึ่งจะนับซ้ำ
    """
    positives = [(name, value) for name, value in pairs if value > 0]
    if len(positives) < 3:
        return None
    total_name, total = max(positives, key=lambda item: item[1])
    parts = [(name, value) for name, value in positives if not (name == total_name and value == total)]
    if len(parts) < 2:
        return None
    subtotal = sum(value for _, value in parts)
    if not total or abs(subtotal - total) / total > RECONCILE_TOLERANCE:
        return None
    seen: set[str] = set()
    segments = []
    for name, value in parts:
        if name in seen:
            return None  # ชื่อซ้ำแปลว่าคนละมิติปนกัน
        seen.add(name)
        segments.append({"name": name, "amount": value})
    return {"total": total, "segments": segments}


# คำนำหน้าที่ SEC ใส่ไว้บอกมิติของตาราง ไม่ใช่ชื่อส่วนงานที่ผู้อ่านต้องการเห็น
GENERIC_DIMENSION = re.compile(
    r"^(operating segments?|reportable segments?|segments?|consolidation eliminations?|"
    r"product and service|geographical|revenue benchmark|customer concentration risk)$",
    re.I,
)


def clean_segment_name(name: str) -> str:
    parts = [part.strip() for part in name.split("|") if part.strip()]
    kept = [part for part in parts if not GENERIC_DIMENSION.match(part)]
    return " · ".join(kept or parts)


def _candidate_reports(base: str, timeout: int) -> list[tuple[str, str]]:
    summary = _download(FILING_SUMMARY.format(base=base), timeout)
    reports: list[tuple[str, str]] = []
    for block in re.findall(r"<Report[^>]*>(.*?)</Report>", summary, re.S):
        name = re.search(r"<ShortName>(.*?)</ShortName>", block)
        file = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", block)
        if not name or not file:
            continue
        label = html.unescape(name.group(1))
        if REPORT_PATTERN.search(label) and DETAIL_PATTERN.search(label):
            reports.append((label, file.group(1)))
    return reports


def extract_segments(
    source_url: str,
    *,
    timeout: int = 60,
    max_reports: int = 6,
) -> dict[str, Any] | None:
    """ลองทีละรายงานจนกว่าจะเจอชุดที่กระทบยอดได้ ไม่เจอก็คืน None"""
    base = source_url.rsplit("/", 1)[0]
    try:
        reports = _candidate_reports(base, timeout)
    except Exception:  # noqa: BLE001 - ไม่มี FilingSummary ก็แค่ไม่มีข้อมูลส่วนนี้
        return None

    for label, file in reports[:max_reports]:
        try:
            rows = parse_table(_download(f"{base}/{file}", timeout))
        except Exception:  # noqa: BLE001
            continue
        result = reconciled_segments(segments_from_rows(rows))
        if not result:
            continue
        scale, currency = unit_scale(rows)
        return {
            "basis": label,
            "currency": currency,
            "unit": "ล้าน",
            "total": round(result["total"] * scale / 1_000_000, 3),
            "segments": [
                {
                    "name": clean_segment_name(segment["name"]),
                    "amount": round(segment["amount"] * scale / 1_000_000, 3),
                }
                for segment in result["segments"]
            ],
            "source_url": f"{base}/{file}",
            "reconciled": True,
        }
    return None
