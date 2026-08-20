# วิธีเปลี่ยน FastDeep จาก Demo Data เป็นราคาจริง

ตอนนี้ FastDeep Scanner จะใช้ข้อมูลตามลำดับนี้:

1. ถ้ามี `data/fastdeep_prices.csv` จะใช้ราคาจริงจากไฟล์นี้
2. ถ้ามี `data/fastdeep_fundamentals.csv` จะใช้พื้นฐานจริงจากไฟล์นี้
3. ถ้าไม่มีไฟล์จริง ระบบจะกลับไปใช้ sample/demo data

## วิธีเริ่มง่ายสุดด้วย CSV จาก TradingView

1. เปิดกราฟหุ้นใน TradingView
2. เลือก timeframe ที่ต้องการ export เช่น `1D`
3. Export chart data เป็น CSV
4. รวมข้อมูลหลายหุ้นให้อยู่ในไฟล์เดียวชื่อ:

```text
data/fastdeep_prices.csv
```

รูปแบบที่ระบบอ่านได้:

```csv
date,symbol,open,high,low,close,volume
2026-06-01,ADVANC.BK,250,262,248,260,12000000
2026-06-02,ADVANC.BK,260,268,258,266,15000000
2026-06-01,NVDA,1120,1168,1110,1162,48000000
```

ถ้า CSV จาก TradingView เป็นหัวคอลัมน์แบบนี้ก็อ่านได้:

```csv
time,open,high,low,close,Volume
2026-06-01,250,262,248,260,12000000
```

แต่กรณีไม่มีคอลัมน์ `symbol` ให้ตั้งชื่อไฟล์แบบมีชื่อหุ้น เช่น:

```text
data/fastdeep_prices_ADVANC_BK.csv
```

แล้วค่อยรวมเป็น `fastdeep_prices.csv` เมื่อจะ scan หลายหุ้นพร้อมกัน

## ไฟล์พื้นฐานหุ้น

ใส่ไฟล์:

```text
data/fastdeep_fundamentals.csv
```

ตัวอย่าง:

```csv
symbol,name,market,sector,roe,roa,debt_to_equity,revenue_growth,profit_growth,gross_margin,net_margin,pe,pbv,dividend_yield,analyst_upside_pct,liquidity_score,moat,ai_trend,notes
ADVANC.BK,Advanced Info Service,TH,Digital Infrastructure,32,12.5,1.35,8,10,33,18,21,7.9,3.7,12,91,strong,beneficiary,Telecom cash flow
```

## เปิด Scanner หลังใส่ข้อมูลจริง

ดับเบิลคลิก:

```text
OPEN_FASTDEEP_SCANNER.bat
```

ระบบจะสร้างหน้าเว็บใหม่ และตรงหัวเว็บจะเปลี่ยนเป็น:

```text
Data Source และ Data Health
```

ถ้า Data Health ระบุว่าข้อมูลเก่า หรือ coverage ไม่ครบ ให้รอการอัปเดตสำเร็จก่อนใช้ผลสแกนหรือ export รายงาน

## ถ้าต้องการอัตโนมัติจริง

TradingView ไม่ได้มี API ราคาหุ้นแบบ official สำหรับให้เราดึงทั้งตลาดโดยตรงในแผนทั่วไป วิธีที่เหมาะกว่า:

- ใช้ `yfinance` สำหรับเริ่มต้น
- ใช้ Finnhub / Alpha Vantage สำหรับ API จริง
- ใช้ broker API ถ้าต้องการราคาใกล้ TradingView/real-time กว่า
- ใช้ TradingView Alert + Webhook สำหรับแจ้งสัญญาณ ไม่ใช่ดึงทั้งตลาดย้อนหลัง

## วิธีที่ทำไว้ให้แล้ว: ดึงราคาจริงจาก Yahoo Finance

แก้รายชื่อหุ้นในไฟล์:

```text
data/fastdeep_universe.csv
```

ตอนนี้ไฟล์นี้ถูกอัปเดตแล้ว มีประมาณ:

- `SP500` = S&P 500
- `NASDAQ100` = Nasdaq-100
- `CHINA50` = หุ้นจีนใหญ่ 50 ตัว
- `SET_SAMPLE` = หุ้นไทยเริ่มต้น 5 ตัว

ถ้าต้องการเพิ่ม/ลบหุ้น ให้แก้ไฟล์ `data/fastdeep_universe.csv` โดยคอลัมน์สำคัญคือ `symbol`, `name`, `market`, `sector`, `index_groups`

แล้วดับเบิลคลิก:

```text
UPDATE_FASTDEEP_PRICES_AND_OPEN.bat
```

ไฟล์นี้จะทำ 3 อย่าง:

1. ดึงราคา OHLCV จาก Yahoo Finance
2. เขียนลง `data/fastdeep_prices.csv` แบบ atomic เมื่อ coverage ผ่านเกณฑ์ 97%
3. สร้างและเปิดหน้า Scanner ใหม่

หมายเหตุ: Yahoo Finance อาจมี delay และราคาอาจไม่ตรง TradingView 100% โดยเฉพาะ exchange/feed ที่ต่างกัน แต่จะเป็นข้อมูลจริง ไม่ใช่ demo data ใช้ TradingView เพื่อยืนยัน chart/execution ก่อนทุกคำสั่ง

## ปุ่มแนบรูปกราฟ / Image Match

หน้า FastDeep Scanner v1 มีปุ่มแนบรูปกราฟแล้ว วิธีทำงานคือ:

- อ่านทรงกราฟจากรูปที่แนบ
- เทียบกับข้อมูลราคาล่าสุดใน `data/fastdeep_prices.csv`
- เคารพตัวกรอง `ตลาด`, `Universe`, และ `Timeframe` ที่เลือกอยู่
- แสดง asset ที่ทรงกราฟคล้ายที่สุด พร้อมปุ่มเปิด TradingView

ถ้าต้องการให้ผลแม่นขึ้น ให้ใช้รูปกราฟที่เห็นแท่ง/เส้นราคาชัด พื้นหลังไม่รก และเลือก timeframe ให้ตรงกับรูป เช่น D, W หรือ M
