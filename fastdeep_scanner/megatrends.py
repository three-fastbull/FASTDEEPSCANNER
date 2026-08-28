"""คัดหุ้นจากเมกะเทรนด์และกลุ่มอุตสาหกรรม

จัดกลุ่มจากรหัสอุตสาหกรรม (SIC) ที่บริษัทแจ้งไว้กับ SEC ซึ่งเป็นข้อเท็จจริงที่
ตรวจสอบได้ ไม่ใช่การประเมินว่าบริษัทได้ประโยชน์จากเทรนด์นั้นมากน้อยแค่ไหน

ข้อจำกัดที่ต้องบอกผู้ใช้ให้ชัด: รหัส SIC บอกว่าบริษัท "ยื่นแบบภายใต้กลุ่มไหน"
ไม่ได้บอกสัดส่วนรายได้ บริษัทที่มีหลายธุรกิจจะถูกจัดตามธุรกิจหลักเพียงกลุ่มเดียว
หน้าจอนี้จึงเป็นตัวกรองตั้งต้นสำหรับไปทำการบ้านต่อ ไม่ใช่ข้อสรุปว่าเป็นหุ้นเทรนด์นั้น
"""

from __future__ import annotations

import re
from typing import Any


# กลุ่มอุตสาหกรรม: ทุกบริษัทอยู่ได้กลุ่มเดียว ครอบคลุมทั้ง universe
# คีย์คือคำที่ต้องพบในชื่ออุตสาหกรรมของ SEC เรียงจากเฉพาะเจาะจงไปกว้าง
INDUSTRY_GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("semiconductor", "เซมิคอนดักเตอร์และอิเล็กทรอนิกส์", (
        "semiconductor", "printed circuit", "electronic component", "electronic connector",
        "drawing & insulating of  nonferrous wire",
    )),
    ("software", "ซอฟต์แวร์และบริการดิจิทัล", (
        "prepackaged software", "computer programming", "computer processing",
        "computer integrated systems", "services-business services",
        "consumer credit reporting", "advertising agencies",
    )),
    ("hardware", "คอมพิวเตอร์และอุปกรณ์เครือข่าย", (
        "electronic computers", "computer storage", "computer peripheral",
        "computer & office equipment", "computer communications",
        "telephone & telegraph apparatus", "communications equipment",
        "radio & tv broadcasting & communications equipment",
    )),
    ("healthcare", "สุขภาพและการแพทย์", (
        "pharmaceutical", "biological products", "surgical & medical", "orthopedic",
        "hospital & medical", "in vitro", "medical laborator", "x-ray apparatus",
        "electromedical", "general medical & surgical", "ophthalmic",
        "misc health", "commercial physical & biological research",
        "wholesale-drugs", "wholesale-medical", "retail-drug stores",
    )),
    ("energy", "พลังงานและเชื้อเพลิง", (
        "crude petroleum", "petroleum refining", "natural gas", "oil & gas", "oil royalty",
        "cogeneration",
    )),
    ("utilities", "สาธารณูปโภค", (
        "electric services", "electric & other services", "gas & other services",
        "water supply", "refuse systems",
    )),
    ("financials", "ธนาคารและตลาดทุน", (
        "commercial banks", "security brokers", "security & commodity", "investment advice",
        "finance services",
    )),
    ("insurance", "ประกันภัย", ("insurance", "life insurance", "accident & health")),
    ("realestate", "อสังหาริมทรัพย์และ REIT", ("real estate", "operative builders", "residential bldgs")),
    ("industrial", "อุตสาหกรรมและเครื่องจักร", (
        "machinery", "engines & turbines", "motors & generators", "aircraft", "guided missiles",
        "ordnance", "ship & boat", "railroad equipment", "metal cans", "fabricated metal",
        "industrial instruments", "measuring & controlling", "laboratory analytical",
        "instruments for meas", "optical instruments", "search, detection",
        "auto controls", "heating equip", "air-cond", "pumps & pumping",
        "electrical work", "heavy construction", "electronic & other electrical",
        "miscellaneous manufacturing", "cutlery", "household appliances",
        "services-engineering", "services-equipment rental", "services-management",
        "services-detective", "services-to dwellings",
    )),
    ("materials", "วัสดุและเคมีภัณฑ์", (
        "chemicals", "plastic materials", "paints", "paper mills", "paperboard",
        "converted paper", "steel works", "rolling drawing", "metal mining",
        "gold and silver", "mining & quarrying", "cement", "agricultural chemicals",
    )),
    ("transport", "ขนส่งและโลจิสติกส์", (
        "air transportation", "air courier", "railroads", "trucking", "water transportation",
        "transportation services", "arrangement of  transportation",
    )),
    ("consumer", "สินค้าและบริการผู้บริโภค", (
        "beverages", "bottled & canned", "malt beverages", "cigarettes", "food", "grain mill",
        "meat packing", "poultry", "sugar & confectionery", "fats & oils", "canned",
        "retail-", "apparel", "men's & boys", "rubber & plastics footwear", "leather",
        "perfumes", "soap, detergents", "specialty cleaning", "games, toys",
        "hotels & motels", "wholesale-groceries", "wholesale-", "household",
        "home furniture", "auto & home supply", "agricultural production",
    )),
    ("automotive", "ยานยนต์", ("motor vehicle", "motor vehicles & passenger")),
    ("media", "สื่อและความบันเทิง", (
        "cable & other pay television", "television broadcasting", "newspapers",
        "publishing", "amusement & recreation", "video tape rental",
        "radiotelephone", "telephone communications", "communications services",
    )),
]

# เมกะเทรนด์: บริษัทหนึ่งอยู่ได้หลายเทรนด์ ตามหลักสูตร ONE Investor
MEGATRENDS: list[dict[str, Any]] = [
    {
        "key": "ai",
        "name": "AI & Automation",
        "short": "ชิปและซอฟต์แวร์ที่ขับเคลื่อน AI",
        "thesis": "AI เข้าไปเปลี่ยนทุกอุตสาหกรรม ความต้องการชิปประมวลผลและซอฟต์แวร์จึงโตต่อเนื่อง",
        "watch": "ต้องแยกให้ออกว่าบริษัทขาย AI จริง หรือแค่พูดถึง AI ในเอกสาร",
        "industries": ("semiconductor", "software", "hardware"),
    },
    {
        "key": "cloud",
        "name": "Cloud & Big Data",
        "short": "โครงสร้างพื้นฐานข้อมูลและซอฟต์แวร์องค์กร",
        "thesis": "องค์กรย้ายระบบขึ้น Cloud และปริมาณข้อมูลโตเร็วกว่าโครงสร้างพื้นฐานที่มีอยู่",
        "watch": "ดูว่ารายได้เป็นแบบสัญญาต่อเนื่องหรือขายขาด ซึ่งให้คุณภาพกำไรต่างกันมาก",
        "industries": ("software", "hardware"),
    },
    {
        "key": "healthcare",
        "name": "Healthcare & Aging",
        "short": "ยา อุปกรณ์การแพทย์ และบริการสุขภาพ",
        "thesis": "สังคมผู้สูงอายุทำให้ความต้องการการรักษา ยา และอุปกรณ์การแพทย์เพิ่มขึ้นไม่หยุด",
        "watch": "ยาที่หมดสิทธิบัตรทำให้รายได้หายเป็นก้อน ต้องดูว่ามีตัวใหม่มาทดแทนหรือไม่",
        "industries": ("healthcare",),
    },
    {
        "key": "energy_transition",
        "name": "Clean Energy & EV",
        "short": "พลังงานสะอาดและยานยนต์ไฟฟ้า",
        "thesis": "การเปลี่ยนผ่านพลังงานต้องลงทุนโครงสร้างพื้นฐานมหาศาลตลอด 10-20 ปีข้างหน้า",
        "watch": "กลุ่มนี้อ่อนไหวกับนโยบายรัฐและเงินอุดหนุน ซึ่งเปลี่ยนได้เร็วกว่าที่คิด",
        "industries": ("utilities", "automotive", "materials"),
    },
    {
        "key": "digital_finance",
        "name": "Digital Finance",
        "short": "ธนาคาร ตลาดทุน และประกัน",
        "thesis": "บริการการเงินย้ายสู่ดิจิทัล ต้นทุนต่อธุรกรรมลดลงและเข้าถึงคนได้กว้างขึ้น",
        "watch": "ยังผูกกับวัฏจักรดอกเบี้ยและคุณภาพสินเชื่อ ไม่ใช่หุ้นเทคโนโลยีล้วน",
        "industries": ("financials", "insurance"),
    },
    {
        "key": "infrastructure",
        "name": "Infrastructure",
        "short": "เครื่องจักร ก่อสร้าง และขนส่ง",
        "thesis": "การย้ายฐานการผลิตและการลงทุนโครงสร้างพื้นฐานหนุนความต้องการเครื่องจักรและงานก่อสร้าง",
        "watch": "รายได้เป็นโครงการ ต้องดูงานคงค้างและอัตรากำไรของงานที่รับมาใหม่",
        "industries": ("industrial", "transport", "materials"),
    },
    {
        "key": "consumer",
        "name": "Consumer Brands",
        "short": "แบรนด์สินค้าและบริการผู้บริโภค",
        "thesis": "แบรนด์ที่ลูกค้าภักดีตั้งราคาได้สูงกว่าคู่แข่งและทนเงินเฟ้อได้ดีกว่า",
        "watch": "วัดที่อัตรากำไรขั้นต้น ถ้าลดลงต่อเนื่องแปลว่าอำนาจตั้งราคากำลังหาย",
        "industries": ("consumer", "media"),
    },
    {
        "key": "real_assets",
        "name": "Real Assets",
        "short": "อสังหาริมทรัพย์และสินทรัพย์ที่ให้กระแสเงินสด",
        "thesis": "สินทรัพย์ที่สร้างกระแสเงินสดสม่ำเสมอเป็นที่ต้องการในภาวะเงินเฟ้อ",
        "watch": "อ่อนไหวกับดอกเบี้ยมาก ต้องดูอายุหนี้และต้นทุนการกู้ใหม่",
        "industries": ("realestate", "energy"),
    },
]

INDUSTRY_LABELS = {key: label for key, label, _ in INDUSTRY_GROUPS}
UNCLASSIFIED = "other"
UNCLASSIFIED_LABEL = "อื่น ๆ ที่ยังไม่จัดกลุ่ม"


def classify_industry(industry: str) -> str:
    """จับกลุ่มอุตสาหกรรมจากชื่อที่ SEC ใช้

    เรียงตามลำดับที่ประกาศไว้ กลุ่มเฉพาะเจาะจงจึงชนะกลุ่มกว้าง เช่น ยานยนต์
    ต้องถูกจับก่อนคำว่า retail ที่กว้างกว่า
    """
    text = (industry or "").strip().lower()
    if not text:
        return UNCLASSIFIED
    for key, _, needles in INDUSTRY_GROUPS:
        if any(needle in text for needle in needles):
            return key
    return UNCLASSIFIED


def megatrends_for(industry_key: str) -> list[str]:
    return [trend["key"] for trend in MEGATRENDS if industry_key in trend["industries"]]


def build_catalog(companies: list[dict[str, Any]]) -> dict[str, Any]:
    """สรุปจำนวนบริษัทในแต่ละเมกะเทรนด์และกลุ่มอุตสาหกรรม"""
    industry_counts: dict[str, int] = {}
    trend_counts: dict[str, int] = {}
    for company in companies:
        key = company["industry_group"]
        industry_counts[key] = industry_counts.get(key, 0) + 1
        for trend in company["megatrends"]:
            trend_counts[trend] = trend_counts.get(trend, 0) + 1

    trends = [
        {
            "key": trend["key"],
            "name": trend["name"],
            "short": trend["short"],
            "thesis": trend["thesis"],
            "watch": trend["watch"],
            "industries": [
                {"key": key, "label": INDUSTRY_LABELS[key], "count": industry_counts.get(key, 0)}
                for key in trend["industries"]
            ],
            "count": trend_counts.get(trend["key"], 0),
        }
        for trend in MEGATRENDS
    ]
    industries = [
        {"key": key, "label": label, "count": industry_counts.get(key, 0)}
        for key, label, _ in INDUSTRY_GROUPS
        if industry_counts.get(key)
    ]
    if industry_counts.get(UNCLASSIFIED):
        industries.append(
            {"key": UNCLASSIFIED, "label": UNCLASSIFIED_LABEL, "count": industry_counts[UNCLASSIFIED]}
        )
    return {
        "megatrends": trends,
        "industries": industries,
        "total": len(companies),
        "basis": "จัดกลุ่มจากรหัสอุตสาหกรรมที่บริษัทยื่นต่อ SEC",
        "caveat": (
            "รหัสอุตสาหกรรมบอกว่าบริษัทยื่นแบบภายใต้กลุ่มไหน ไม่ได้บอกสัดส่วนรายได้ "
            "บริษัทที่ทำหลายธุรกิจจะถูกจัดตามธุรกิจหลักเพียงกลุ่มเดียว "
            "ใช้เป็นตัวกรองตั้งต้นเพื่อไปตรวจต่อ ไม่ใช่ข้อสรุปว่าเป็นหุ้นของเทรนด์นั้น"
        ),
    }


_TICKER = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def is_symbol(value: str) -> bool:
    return bool(_TICKER.match((value or "").strip().upper()))
