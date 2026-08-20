# FastDeep Scanner v1

FastDeep Scanner v1 คือ MVP สำหรับ workflow ที่เริ่มจากกราฟก่อน แล้วค่อยตรวจพื้นฐานหุ้น:

ตอนนี้ระบบรองรับ S&P 500, Nasdaq-100, หุ้นจีน 50 ตัว, SET50, SET100, หุ้นไทยตัวอย่าง และ MAI starter list โดยราคาหลักมาจาก `data/fastdeep_prices.csv` ถ้ามีไฟล์นี้อยู่ ระบบจะใช้ราคาจริงจาก Yahoo Finance ที่ดาวน์โหลดไว้ ไม่ใช่ demo data

ก่อนใช้ผลสแกน ให้ดูบรรทัด `Data Health` ด้านบนของหน้าเว็บเสมอ: ระบบจะแสดงวันที่แท่งราคาล่าสุด, coverage และสถานะพร้อมใช้ หากข้อมูลเก่าหรือดาวน์โหลดไม่ครบ ระบบจะปิด CSV export และระบุว่าผลสแกนยังไม่ควรใช้ตัดสินใจ

ดูวิธีเปลี่ยนเป็นราคาจริงใน `REAL_DATA_SETUP.md`

ถ้าต้องการอัปเดตราคาจริงแบบกดครั้งเดียว ให้ใช้ `UPDATE_FASTDEEP_PRICES_AND_OPEN.bat`

1. Market Scanner สแกนหุ้นและหา pattern ตาม D / W / M ที่เลือกจริง
2. Technical Pattern Agent ตรวจ Breakout, Retest, Cup & Handle, Double Bottom, Head & Shoulders
3. Financial Analysis ตรวจ ROE, ROA, Debt, Growth, Margin จากงบที่ยืนยันแล้วเท่านั้น
4. Business Quality Agent ตรวจ Moat และ AI/automation trend
5. Valuation Agent ตรวจ PE, PBV, Dividend, Upside
6. Report Writer Agent สร้างรายงาน HTML ที่พิมพ์เป็น PDF ได้
7. Image Match แนบรูปกราฟเพื่อหา asset ที่ทรงกราฟคล้ายกันใน universe ที่เลือก

หุ้นที่ยังไม่มีงบใน cache จะปรากฏเป็น `Technical Candidate / Research required` และไม่มีสิทธิ์ได้คะแนนพื้นฐานปลอม ระบบนี้เป็น research workflow เท่านั้น ไม่ใช่คำแนะนำการลงทุน

## Run CLI

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner scan --market ALL --min-score 55
```

เลือกเฉพาะ pattern:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner scan --patterns breakout,retest,double_bottom
```

## Run Web Dashboard

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner serve --port 8765
```

เปิด:

```text
http://127.0.0.1:8765
```

## Financial Intelligence

หน้าเว็บ live มี 2 dashboard เพิ่มเติม:

1. `งบการเงิน 5 ปี` แสดงงบกำไรขาดทุน งบดุล กระแสเงินสด และอัตราส่วนเป็นภาษาไทย กดปีเพื่อดู Q1-Q4 ของปีนั้น
2. `VI Thesis` ให้ตั้งเป้าหมาย Revenue CAGR, Net Profit CAGR, ROE และ D/E แล้วเทียบความคืบหน้าจากงบจริง

งบจะโหลดเมื่อเลือกหุ้นและเก็บ cache ไว้ 24 ชั่วโมง จึงใช้ได้กับทุก symbol ใน universe โดยไม่ต้องรอดาวน์โหลดทั้งตลาดก่อนเปิดหน้าเว็บ:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner update-financials --universe data/fastdeep_universe.csv
```

## Daily Data Operations

`Launch-FastDeepScanner.ps1` จะตรวจโค้ดล่าสุดจาก GitHub และเริ่มอัปเดตราคา 5 ปีแบบ background โดยใช้ atomic publish: ข้อมูลชุดเก่าจะไม่ถูกเขียนทับจนกว่าจะดาวน์โหลดสำเร็จอย่างน้อย 97% ของ universe

ติดตั้งงาน Windows รายวัน 07:00 (ขณะบัญชี Windows นี้ sign in อยู่) เพียงครั้งเดียว:

```powershell
& '.\Install-FastDeepDailyTask.ps1'
```

งานนี้อัปเดตราคาและสร้าง `storage/fastdeep_daily_scan_summary.json` งบจะ refresh เมื่อเลือกหุ้นในหน้า Financial Intelligence; ระบบจะแสดง coverage ของงบที่ยืนยันแล้วเสมอ

หมายเหตุ: public endpoint ของ Yahoo Finance จำกัดความเร็วเมื่อ refresh งบหลายร้อยตัวพร้อมกัน จึงไม่ใช้เป็น batch scheduler สำหรับงานสถาบัน หากต้องการงบครบ universe แบบมี SLA ให้ต่อผู้ให้บริการข้อมูลที่ได้รับอนุญาตก่อน แล้วใช้ adapter เดียวกับ Financial Intelligence

ในรายละเอียดหุ้น มี workflow สั้น ๆ สำหรับบันทึก `Watch`, `Research`, `Approved`, `Owned` หรือ `Exit` พร้อมโน้ตการตัดสินใจ ข้อมูลอยู่ใน `storage/fastdeep_research_journal.json` เพื่อให้ทีมทบทวนเหตุผลย้อนหลังได้

## Pattern Validation

ก่อนใช้ pattern เป็นกฎลงทุน ให้รัน event study แยกตามตลาดและ timeframe:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner backtest --market US --universe SP500 --timeframe D --patterns breakout,retest --holding-bars 20
```

ผลอยู่ที่ `storage/fastdeep_event_study.json` และเป็น historical event study เท่านั้น: ยังไม่หักค่าธรรมเนียม, slippage, position sizing หรือผลจากสัญญาณซ้อนกัน จึงห้ามใช้แทนผลตอบแทนกองทุนจริง

แหล่งข้อมูลเริ่มต้นคือ Yahoo Finance fundamentals timeseries ซึ่งครอบคลุม US, China และ Thailand แต่โดยทั่วไปเปิดให้รายปีเต็ม 4 ปีและงบรายไตรมาสล่าสุดประมาณ 5 งวดเท่านั้น หน้า dashboard จะแสดงเฉพาะงวดที่ผู้ให้บริการส่งกลับและไม่สร้างตัวเลขย้อนหลังขึ้นเอง

## Image Match

ในหน้าเว็บจะมีส่วน `แนบรูปกราฟเพื่อหา asset คล้ายกัน`

วิธีใช้:

1. เลือก `ตลาด`, `Universe`, และ `Timeframe` ที่ต้องการ เช่น `ALL + China 50 + D`, `TH + SET50 + D`, `TH + SET100 + W` หรือ `TH + MAI + D`
2. กดเลือกไฟล์รูปกราฟ
3. กด `Scan รูปกราฟ`
4. ระบบจะแสดงหุ้นที่ทรงกราฟคล้ายที่สุด พร้อมปุ่ม `TV` เพื่อเปิด TradingView

หมายเหตุ: v1 ยังเป็นการเทียบ shape ของกราฟจากรูปกับข้อมูลราคาที่มีอยู่ ไม่ใช่ AI OCR/vision เต็มรูปแบบ ถ้ารูปมีเส้นเยอะมากหรือพื้นหลังรก ผลอาจเพี้ยนได้

## Export Report

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner report --symbol ADVANC.BK --out storage/ADVANC_fastdeep_report.html
```

ในหน้าเว็บกด `PDF Report` แล้วกด `Save as PDF` จาก browser print dialog

## Data Format

ถ้าจะใช้ข้อมูลจริง ให้เตรียม CSV ราคา:

```csv
date,symbol,open,high,low,close,volume
2026-06-01,ADVANC.BK,250,262,248,260,12000000
```

และ CSV พื้นฐาน:

```csv
symbol,name,market,sector,roe,roa,debt_to_equity,revenue_growth,profit_growth,gross_margin,net_margin,pe,pbv,dividend_yield,analyst_upside_pct,liquidity_score,moat,ai_trend,notes
ADVANC.BK,Advanced Info Service,TH,Digital Infrastructure,32,12.5,1.35,8,10,33,18,21,7.9,3.7,12,91,strong,beneficiary,Telecom cash flow
```

แล้วรัน:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner scan --market-data data/your_prices.csv --fundamentals data/your_fundamentals.csv
```

## Next Phase

Phase 2 ที่ควรต่อ:

- เพิ่ม data connector เช่น yfinance, Finnhub, AlphaVantage หรือ CSV จาก TradingView
- เพิ่ม backtest รายหุ้นและราย pattern
- เพิ่ม Telegram alert
- เพิ่ม ingestion เอกสาร 56-1 / 10-K เพื่อส่งต่อ NotebookLM
- ย้าย frontend เป็น Next.js ถ้าต้องการ authentication, database, และ deploy แบบ startup จริง
