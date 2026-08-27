"""ข้อความธุรกิจที่สกัดจากแบบ 10-K โดยตรง

ชั้นนี้อยู่ใต้แคตตาล็อกที่คนทบทวนแล้ว ใช้เติมช่องที่ยังว่างด้วยข้อความจากเอกสาร
ที่บริษัทยื่นเอง พร้อมลิงก์กลับไปยังไฟล์ต้นทางเสมอ

สิ่งที่ชั้นนี้ไม่ทำ: ไม่สรุป ไม่แปล และไม่ประเมิน Moat หรือจัดคู่เทียบให้ เพราะ
ทั้งสามอย่างเป็นการตีความ ไม่ใช่ข้อความที่ยกมาได้ตรง ๆ จากเอกสาร
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .sec_edgar import SecEdgarError, _sec_contact, _sec_user_agent


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / "data" / "fastdeep_filing_profiles.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
SCHEMA_VERSION = 1

SUMMARY_LIMIT = 1100
SECTION_LIMIT = 900
CUSTOMER_LIMIT = 700


def _download(url: str, timeout: int = 60) -> bytes:
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
        return response.read()


def plain_text(raw: str) -> str:
    """แปลง HTML ของ 10-K เป็นข้อความ โดยรักษาการขึ้นบรรทัดของบล็อกไว้

    การขึ้นบรรทัดสำคัญ เพราะหัวข้อย่อยอย่าง Competition ถูกระบุด้วยการอยู่ต้นบรรทัด
    ไม่ใช่ด้วยแท็กที่เชื่อถือได้
    """
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)</(p|div|tr|h[1-6]|li|table)>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def item1_body(text: str) -> str:
    """เนื้อหา Item 1 ตัวจริง

    สารบัญมีคำว่า Item 1 และ Item 1A เหมือนกัน จึงเลือกช่วงที่ยาวที่สุด เพราะ
    ช่วงในสารบัญห่างกันเพียงไม่กี่สิบตัวอักษร ส่วนเนื้อหาจริงยาวหลักหมื่น
    """
    starts = [m.end() for m in re.finditer(r"(?im)^\s*item\s*1\s*[.:\-–—]?\s*(business)?\b", text)]
    ends = [m.start() for m in re.finditer(r"(?im)^\s*item\s*1a\s*[.:\-–—]?\s*(risk)?\b", text)]
    best = ""
    for start in starts:
        following = [end for end in ends if end > start]
        if not following:
            continue
        chunk = text[start : following[0]]
        if len(chunk) > len(best):
            best = chunk
    return best.strip()


def _substantive_lines(body: str) -> list[str]:
    lines = []
    for line in body.split("\n"):
        line = line.strip()
        if len(line) < 120:
            continue
        if re.match(r"(?i)^(part\s+[ivx]+\b|table of contents)", line):
            continue
        lines.append(line)
    return lines


def business_summary(body: str, limit: int = SUMMARY_LIMIT) -> str:
    """ย่อหน้าแรก ๆ ของ Item 1 ตามลำดับที่ปรากฏในเอกสาร

    เคยลองข้ามย่อหน้านิยามคำแทนตัวบริษัท แต่ทำให้บางบริษัทได้ย่อหน้าการเปิดเผย
    ข้อมูลแทนคำอธิบายธุรกิจ การยกตามลำดับจริงจึงคาดเดาได้กว่า และผู้อ่านมีลิงก์
    ไปยังเอกสารเต็มอยู่แล้ว
    """
    collected: list[str] = []
    for line in _substantive_lines(body):
        collected.append(line)
        if sum(len(item) for item in collected) > limit:
            break
    return " ".join(collected)[:limit].strip()


def section_excerpt(body: str, heading: str, limit: int = SECTION_LIMIT) -> str:
    """ข้อความใต้หัวข้อย่อยที่ระบุ จนกว่าจะเจอหัวข้อถัดไป"""
    match = re.search(
        rf"(?im)^\s*({heading}[^\n]{{0,80}})\n(.{{200,2500}}?)(?=\n\s*[A-Z][^\n]{{0,70}}\n)",
        body,
        re.S,
    )
    if not match:
        return ""
    title = match.group(1).strip(" .:")
    detail = re.sub(r"\s+", " ", match.group(2)).strip()
    return f"{title} — {detail}"[:limit]


def customer_concentration(text: str, limit: int = CUSTOMER_LIMIT) -> str:
    """ประโยคที่บริษัทเปิดเผยการกระจุกตัวของลูกค้า

    เก็บมาทั้งประโยคโดยไม่ตัดต่อ เพราะบางบริษัทพูดถึงลูกหนี้การค้าไม่ใช่รายได้
    ผู้อ่านต้องเห็นข้อความเต็มจึงจะแยกออก
    """
    pattern = (
        r"[^.\n]{0,240}?(?:no single customer|no customer|one customer|largest customer|"
        r"customers? accounted for|customer represented|customers? represented)[^.\n]{0,240}\."
    )
    seen: list[str] = []
    for hit in re.findall(pattern, text, re.I):
        cleaned = re.sub(r"\s+", " ", hit).strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
        if len(" ".join(seen)) > limit:
            break
    return " ".join(seen)[:limit]


def latest_annual_filing(cik: str, timeout: int = 45) -> dict[str, Any]:
    payload = json.loads(_download(SUBMISSIONS_URL.format(cik=cik.zfill(10)), timeout).decode("utf-8"))
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    for index, form in enumerate(forms):
        if form not in ANNUAL_FORMS:
            continue
        document = (recent.get("primaryDocument") or [None] * len(forms))[index]
        if not document or not str(document).lower().endswith((".htm", ".html")):
            continue
        accession = str(recent["accessionNumber"][index]).replace("-", "")
        return {
            "form": form,
            "filed_at": recent["filingDate"][index],
            "period": (recent.get("reportDate") or [""] * len(forms))[index],
            "url": ARCHIVE_URL.format(cik=int(cik), accession=accession, document=document),
            "entity_name": payload.get("name") or "",
            "industry": payload.get("sicDescription") or "",
        }
    raise SecEdgarError(f"ไม่พบแบบรายปีที่อ่านได้ของ CIK {cik}")


def extract_filing_profile(symbol: str, cik: str, *, timeout: int = 60) -> dict[str, Any]:
    filing = latest_annual_filing(cik, timeout=timeout)
    text = plain_text(_download(filing["url"], timeout).decode("utf-8", "replace"))
    body = item1_body(text)
    summary = business_summary(body)
    competition = section_excerpt(body, r"competiti(?:on|ve[^\n]{0,40})")
    customers = customer_concentration(text)
    return {
        "symbol": symbol.upper(),
        "cik": cik.zfill(10),
        "entity_name": filing["entity_name"],
        "industry": filing["industry"],
        "form": filing["form"],
        "filed_at": filing["filed_at"],
        "period": filing["period"],
        "source_url": filing["url"],
        "language": "en",
        "business_summary": summary,
        "competition": competition,
        "customer_concentration": customers,
        "extracted_at": datetime.now(UTC).isoformat(),
        "found": {
            "business_summary": bool(summary),
            "competition": bool(competition),
            "customer_concentration": bool(customers),
        },
    }


def load_filing_profiles(path: str | Path = DEFAULT_STORE) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return {}
    profiles = payload.get("profiles")
    return profiles if isinstance(profiles, dict) else {}


def save_filing_profiles(profiles: dict[str, Any], path: str | Path = DEFAULT_STORE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(UTC).isoformat(),
        "note": (
            "ข้อความยกมาจากแบบที่บริษัทยื่นต่อ SEC โดยไม่ผ่านการเรียบเรียง "
            "ใช้เป็นข้อมูลตั้งต้น ไม่ใช่บทวิเคราะห์ที่ทบทวนแล้ว"
        ),
        "profiles": profiles,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)


def update_filing_profiles(
    symbols: dict[str, str],
    *,
    path: str | Path = DEFAULT_STORE,
    pause: float = 0.2,
    timeout: int = 60,
    refresh: bool = False,
    progress_every: int = 25,
) -> dict[str, Any]:
    """สกัดข้อความธุรกิจของทุก symbol ที่ส่งมา แล้วบันทึกแบบเพิ่มทีละตัว"""
    profiles = load_filing_profiles(path)
    succeeded: list[str] = []
    failed: list[str] = []
    skipped = 0
    for index, (symbol, cik) in enumerate(symbols.items(), start=1):
        if not refresh and symbol in profiles:
            skipped += 1
            continue
        try:
            profiles[symbol] = extract_filing_profile(symbol, cik, timeout=timeout)
            succeeded.append(symbol)
        except Exception as exc:  # noqa: BLE001 - หนึ่งบริษัทล้มต้องไม่ทำให้ทั้งชุดหยุด
            failed.append(f"{symbol}: {exc}")
        if progress_every and index % progress_every == 0:
            save_filing_profiles(profiles, path)
        if pause:
            time.sleep(pause)
    save_filing_profiles(profiles, path)
    return {
        "requested": len(symbols),
        "succeeded": len(succeeded),
        "skipped": skipped,
        "failed": failed,
        "stored": len(profiles),
    }
