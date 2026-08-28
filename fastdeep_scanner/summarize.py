"""สรุปข้อความจากแบบที่ยื่นให้เป็นภาษาไทย

ข้อความใน 10-K เป็นภาษาอังกฤษและยาว ผู้ใช้ส่วนใหญ่อ่านไม่ไหว ชั้นนี้จึงย่อและ
แปลให้ โดยมีข้อบังคับเดียวคือ **ห้ามเติมสิ่งที่ไม่ได้อยู่ในข้อความต้นทาง**

ผลลัพธ์ยังผูกกับไฟล์ที่ยื่นเสมอ ทั้งเลข accession และลิงก์ จึงตรวจย้อนกลับได้ว่า
ประโยคไหนมาจากเอกสารฉบับใด และถ้าโมเดลเขียนอะไรที่ไม่มีในต้นทาง ผู้ตรวจจะจับได้
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .filing_extract import DEFAULT_STORE, load_filing_profiles, save_filing_profiles
from .local_config import get_setting


API_URL = "https://api.anthropic.com/v1/messages"
API_KEY_SETTING = "ANTHROPIC_API_KEY"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SCHEMA_VERSION = 1

SYSTEM_PROMPT = """คุณคือผู้ช่วยที่ย่อข้อมูลบริษัทจากแบบที่ยื่นต่อ ก.ล.ต. สหรัฐ ให้นักลงทุนไทยอ่าน

กฎที่ห้ามฝ่าฝืน
- ใช้ได้เฉพาะข้อมูลในข้อความที่ให้มาเท่านั้น ห้ามเติมความรู้ภายนอก ห้ามเดา
- ถ้าข้อความไม่ได้บอกเรื่องใด ให้เว้นช่องนั้นเป็นสตริงว่าง ห้ามแต่งขึ้น
- ห้ามประเมินว่าหุ้นน่าซื้อหรือไม่ ห้ามคาดการณ์ราคาหรือผลประกอบการ
- เขียนภาษาไทยที่คนทั่วไปเข้าใจ เลี่ยงศัพท์การเงินที่ไม่จำเป็น
- ชื่อสินค้าและชื่อบริษัทให้คงภาษาอังกฤษไว้

ตอบเป็น JSON เท่านั้น ตามรูปแบบนี้
{"summary_th": "...", "revenue_model_th": "...", "customers_th": "...", "competition_th": ""}

summary_th: บริษัททำอะไร ขายอะไร ให้ใคร 2-4 ประโยค
revenue_model_th: หาเงินจากทางไหน ถ้าข้อความไม่ได้บอกให้เว้นว่าง
customers_th: ลูกค้าหลักและการกระจุกตัว ถ้าไม่ได้บอกให้เว้นว่าง
competition_th: สภาพการแข่งขันตามที่บริษัทอธิบาย ถ้าไม่ได้บอกให้เว้นว่าง"""


class SummaryError(RuntimeError):
    """เรียกเมื่อสรุปไม่สำเร็จ"""


def api_key() -> str:
    return get_setting(API_KEY_SETTING)


def _request(payload: dict[str, Any], key: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if exc.code == 401:
            raise SummaryError(
                f"API key ไม่ถูกต้อง ตรวจค่า {API_KEY_SETTING} ในไฟล์ .env"
            ) from exc
        if exc.code == 429:
            raise SummaryError("ถูกจำกัดความถี่ชั่วคราว (429) ระบบจะรอแล้วลองใหม่") from exc
        raise SummaryError(f"เรียก API ไม่สำเร็จ ({exc.code}): {detail}") from exc


def _source_text(profile: dict[str, Any], limit: int = 6000) -> str:
    parts = [
        f"บริษัท: {profile.get('entity_name') or profile.get('symbol')}",
        f"กลุ่มอุตสาหกรรมตาม SEC: {profile.get('industry') or '-'}",
        f"แบบที่ยื่น: {profile.get('form')} งวด {profile.get('period')}",
        "",
        "[ส่วนอธิบายธุรกิจ]",
        profile.get("business_summary") or "(ไม่มี)",
        "",
        "[ส่วนการแข่งขัน]",
        profile.get("competition") or "(ไม่มี)",
        "",
        "[ส่วนลูกค้า]",
        profile.get("customer_concentration") or "(ไม่มี)",
    ]
    return "\n".join(parts)[:limit]


def _parse_reply(text: str) -> dict[str, str]:
    """อ่าน JSON จากคำตอบ เผื่อโมเดลห่อด้วย code fence"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise SummaryError("คำตอบไม่ใช่ JSON ที่อ่านได้")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SummaryError(f"อ่าน JSON จากคำตอบไม่ได้: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SummaryError("คำตอบไม่ใช่ออบเจกต์")
    return {
        key: str(parsed.get(key) or "").strip()
        for key in ("summary_th", "revenue_model_th", "customers_th", "competition_th")
    }


def summarize_profile(
    profile: dict[str, Any],
    *,
    key: str,
    model: str = DEFAULT_MODEL,
    timeout: int = 60,
) -> dict[str, Any]:
    if not (profile.get("business_summary") or "").strip():
        raise SummaryError("ไม่มีข้อความธุรกิจให้สรุป")
    payload = {
        "model": model,
        "max_tokens": 900,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": _source_text(profile)}],
    }
    response = _request(payload, key, timeout)
    blocks = [block.get("text", "") for block in response.get("content", []) if block.get("type") == "text"]
    fields = _parse_reply("".join(blocks))
    return {
        **fields,
        "model": model,
        "source_url": profile.get("source_url", ""),
        "form": profile.get("form", ""),
        "period": profile.get("period", ""),
        "summarized_at": datetime.now(UTC).isoformat(),
    }


def summarize_all(
    *,
    symbols: list[str] | None = None,
    path: str | Path = DEFAULT_STORE,
    model: str = DEFAULT_MODEL,
    pause: float = 0.3,
    timeout: int = 60,
    refresh: bool = False,
    limit: int | None = None,
    save_every: int = 20,
) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise SummaryError(
            f"ยังไม่ได้ตั้ง {API_KEY_SETTING} เพิ่มบรรทัด {API_KEY_SETTING}=ค่าคีย์ของคุณ "
            "ในไฟล์ .env ที่รากโปรเจกต์ (ไฟล์นี้ถูก gitignore ไว้แล้ว)"
        )
    profiles = load_filing_profiles(path)
    wanted = {value.strip().upper() for value in (symbols or []) if value.strip()}
    targets = [
        symbol
        for symbol, profile in sorted(profiles.items())
        if (not wanted or symbol in wanted)
        and (profile.get("business_summary") or "").strip()
        and (refresh or not (profile.get("thai") or {}).get("summary_th"))
    ]
    if limit:
        targets = targets[:limit]

    done: list[str] = []
    failed: list[str] = []
    for index, symbol in enumerate(targets, start=1):
        try:
            profiles[symbol]["thai"] = summarize_profile(
                profiles[symbol], key=key, model=model, timeout=timeout
            )
            done.append(symbol)
        except SummaryError as exc:
            failed.append(f"{symbol}: {exc}")
            if "API key" in str(exc):
                break
        except Exception as exc:  # noqa: BLE001 - หนึ่งบริษัทล้มต้องไม่หยุดทั้งชุด
            failed.append(f"{symbol}: {exc}")
        if save_every and index % save_every == 0:
            save_filing_profiles(profiles, path)
        if pause:
            time.sleep(pause)

    save_filing_profiles(profiles, path)
    return {
        "requested": len(targets),
        "summarized": len(done),
        "failed": failed,
        "model": model,
        "with_thai": sum(1 for item in profiles.values() if (item.get("thai") or {}).get("summary_th")),
    }
