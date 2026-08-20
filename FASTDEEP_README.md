# FastDeep Scanner v1

FastDeep Scanner v1 คือ MVP สำหรับ workflow ที่เริ่มจากกราฟก่อน แล้วค่อยตรวจพื้นฐานหุ้น:

ตอนนี้ระบบรองรับ S&P 500, Nasdaq-100, หุ้นจีน 50 ตัว, SET50, SET100, หุ้นไทยตัวอย่าง และ MAI starter list โดยราคาหลักมาจาก `data/fastdeep_prices.csv` ถ้ามีไฟล์นี้อยู่ ระบบจะใช้ราคาจริงจาก Yahoo Finance ที่ดาวน์โหลดไว้ ไม่ใช่ demo data

ก่อนใช้ผลสแกน ให้ดูแถบ `Data Health` ด้านบนของหน้าเว็บเสมอ: วันที่ EOD ที่ใช้สแกน, แท่งล่าสุดในไฟล์, ผู้ให้บริการ, จำนวนหุ้นที่ดาวน์โหลดสำเร็จ, **จำนวนหุ้นที่ราคาอัปเดตถึงวันสแกนจริง**, coverage ของงบการเงิน และสถานะอัตราแลกเปลี่ยน หากข้อมูลเก่าหรือดาวน์โหลดไม่ครบ ระบบจะปิด CSV export ทั้งฝั่งหน้าเว็บและฝั่ง server

จำนวนหุ้นที่ค้างสำคัญเป็นพิเศษ: ไฟล์ราคาอาจมีวันที่ล่าสุดถูกต้อง แต่หุ้นบางตัวหยุดอัปเดตเพราะถูกพักการซื้อขายหรือหลุดจากผู้ให้บริการ หุ้นเหล่านั้นจะถูกทำเครื่องหมาย `ข้อมูลราคาไม่สด` และไม่ได้รับสถานะซื้อ

ดูวิธีเปลี่ยนเป็นราคาจริงใน `REAL_DATA_SETUP.md`

ถ้าต้องการอัปเดตราคาจริงแบบกดครั้งเดียว ให้ใช้ `UPDATE_FASTDEEP_PRICES_AND_OPEN.bat`

1. Market Scanner สแกนหุ้นและหา pattern ตาม D / W / M ที่ aggregate จริง โดยตัดแท่งของสัปดาห์หรือเดือนที่ยังไม่ปิดออก
2. Technical Pattern Agent ตรวจ Breakout, Retest, Cup & Handle, Double Bottom, Head & Shoulders
3. Financial Analysis ตรวจ ROE, ROA, Debt, Growth, Margin จากงบที่ยืนยันแล้วเท่านั้น
4. Business Quality Agent ใช้ Moat และแนวโน้มธุรกิจที่นักวิเคราะห์บันทึกไว้เอง ไม่มีค่าตั้งต้น
5. Valuation Agent คำนวณ P/E และ P/BV จาก EPS และส่วนของผู้ถือหุ้นในงบจริง เทียบกับราคาปิดล่าสุด
6. Evidence Gate ตรวจว่า pattern นั้นเคยชนะการถือหุ้นเฉย ๆ ในอดีตหรือไม่ ก่อนอนุญาตให้ขึ้นสถานะ Candidate
7. Report Writer Agent สร้างรายงาน HTML ที่พิมพ์เป็น PDF ได้
8. Image Match แนบรูปกราฟเพื่อหา asset ที่ทรงกราฟคล้ายกันใน universe ที่เลือก

### ระดับการตรวจสอบและเพดานคะแนน

คะแนนเต็มสงวนไว้ให้หุ้นที่ตรวจครบทุกด้าน หุ้นที่ตรวจไม่ครบจะถูกจำกัดเพดานไว้ ไม่ให้กราฟสวยอย่างเดียวขึ้นไปอยู่บนสุดของตาราง

| ตรวจถึงระดับ | เพดานคะแนน | Grade | สถานะ |
| --- | --- | --- | --- |
| กราฟอย่างเดียว | 72 | `T-` | รอตรวจงบการเงิน |
| กราฟ + งบ | 82 | `T-` | รอประเมินมูลค่า |
| กราฟ + งบ + มูลค่า | 90 | `T-` | รอบทวิเคราะห์ธุรกิจ |
| ครบทุกด้าน | 100 | `A+` ถึง `D` | Candidate / Watchlist / Reject |

สถานะ `Candidate` ต้องผ่านทั้งสี่ด้าน **และ** pattern นั้นต้องมีหลักฐานย้อนหลังว่าชนะค่าฐาน หุ้นที่ยังไม่มีงบใน cache จะไม่มีสิทธิ์ได้คะแนนพื้นฐานปลอม ระบบนี้เป็น research workflow เท่านั้น ไม่ใช่คำแนะนำการลงทุน

### สกุลเงินของงบการเงิน

งบแต่ละบริษัทรายงานด้วยสกุลเงินของตัวเอง เช่น `USD` สำหรับหุ้นสหรัฐ `THB` สำหรับหุ้นไทย `HKD` หรือ `CNY` สำหรับหุ้นจีน หน้า `งบการเงิน 5 ปี` จะกำกับหน่วยไว้ทุกจุด: หัวตารางบอก `ล้าน <สกุล>` บรรทัด EPS บอก `<สกุล> ต่อหุ้น` และมีแถบเตือนว่าระบบ **ไม่แปลงค่าเงินให้** จึงห้ามนำตัวเลขข้ามบริษัทที่ยื่นงบคนละสกุลมาเทียบกันตรง ๆ

กรณีที่ราคาซื้อขายกับงบเป็นคนละสกุล เช่น หุ้นที่เทรดเป็น HKD แต่ยื่นงบเป็น CNY ระบบจะแปลงราคาด้วยอัตราแลกเปลี่ยนที่มีวันที่กำกับก่อนคำนวณ P/E และ P/BV ถ้าไม่มีอัตราแลกเปลี่ยนของสกุลนั้น ระบบจะไม่ประกาศตัวเลขมูลค่าเลย แทนที่จะเอาสองสกุลมาหารกัน

อัตราแลกเปลี่ยนเก็บที่ `data/fastdeep_fx_rates.json` และรีเฟรชทุกวันพร้อมราคา:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner update-fx
```

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

ตรวจ coverage จริงโดยไม่ดาวน์โหลดใหม่:

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner audit-financials
```

รายงาน `data/fastdeep_financial_coverage.json` แยก `มี cache`, `รายปีครบ 5 งวด` และ `ครบ 5 ปี + Q1-Q4` ออกจากกัน การมีไฟล์ cache ไม่ได้แปลว่างบครบตามเป้าหมาย หุ้นที่มีเพียง 4 ปีหรือไตรมาสบางส่วนยังเปิดดูได้ แต่หน้าเว็บจะระบุช่องว่างไว้ตรง ๆ

### SEC EDGAR สำหรับหุ้นสหรัฐ

FastDeep ใช้ SEC Company Tickers หา CIK แล้วอ่าน Company Facts/XBRL จาก 10-K และ 10-Q โดยตรง ระบบเลือก filing ต้นฉบับ/ฉบับแก้ไขที่ใกล้งวดบัญชี ตัดข้อมูลเปรียบเทียบที่ซ้ำ จัด Q1-Q3 ตามปีบัญชี และคำนวณ Q4 จากงบปีลบสามไตรมาสแรกพร้อมติดธง `derived_from_annual`

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner update-sec-financials --groups SP500,NASDAQ100
```

คำสั่งนี้รันต่อจาก cache เดิม จำกัดความเร็วต่ำกว่าเพดาน SEC และจะไม่เขียนทับงบเดิมเมื่อ SEC ปฏิเสธการเชื่อมต่อ สามารถกำหนด User-Agent และอีเมลติดต่อขององค์กรด้วย `FASTDEEP_SEC_USER_AGENT` และ `FASTDEEP_SEC_CONTACT` ตามนโยบาย automated access ของ SEC

## Daily Data Operations

`Launch-FastDeepScanner.ps1` จะตรวจโค้ดล่าสุดจาก GitHub และเริ่มอัปเดตราคา 5 ปีแบบ background โดยใช้ atomic publish: ข้อมูลชุดเก่าจะไม่ถูกเขียนทับจนกว่าจะดาวน์โหลดสำเร็จอย่างน้อย 97% ของ universe

ติดตั้งงาน Windows รายวัน 07:00 (ขณะบัญชี Windows นี้ sign in อยู่) เพียงครั้งเดียว:

```powershell
& '.\Install-FastDeepDailyTask.ps1'
```

งานนี้อัปเดตราคาและสร้าง `storage/fastdeep_daily_scan_summary.json` งบ SEC สำหรับ S&P 500/Nasdaq-100 จะลองทำงานแบบ resume ทุกวันโดยข้าม cache ที่ยังใหม่ ส่วน batch Yahoo สำรองจะทำงานวันเสาร์; ทุกวันจะสร้างรายงาน coverage ใหม่เพื่อให้ Data Health ตรงกับไฟล์จริง

หมายเหตุ: public endpoint ของ Yahoo Finance จำกัดความเร็วเมื่อ refresh งบหลายร้อยตัวพร้อมกัน จึงไม่ใช้เป็น batch scheduler สำหรับงานสถาบัน หากต้องการงบครบ universe แบบมี SLA ให้ต่อผู้ให้บริการข้อมูลที่ได้รับอนุญาตก่อน แล้วใช้ adapter เดียวกับ Financial Intelligence

ในรายละเอียดหุ้น มี workflow สั้น ๆ สำหรับบันทึก `Watch`, `Research`, `Approved`, `Owned` หรือ `Exit` พร้อมโน้ตการตัดสินใจ ข้อมูลอยู่ใน `storage/fastdeep_research_journal.json` เพื่อให้ทีมทบทวนเหตุผลย้อนหลังได้

## Pattern Validation

Event study วัดผลตอบแทนหลังสัญญาณจริงในอดีต และเทียบกับ **ค่าฐาน** คือการเข้าซื้อแบบสุ่มในหุ้นชุดเดียวกันช่วงเวลาเดียวกัน ตัวเลขที่ใช้ตัดสินคือส่วนต่างจากค่าฐาน ไม่ใช่ hit rate ดิบ เพราะ hit rate สูงอาจแปลว่าตลาดขึ้นเฉย ๆ

```powershell
& 'C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m fastdeep_scanner backtest --timeframe W --horizons 5,10,20 --cost-bps 30 --summary-only
```

ผลอยู่ที่ `storage/fastdeep_event_study_D.json`, `_W.json` และ `_M.json` ดูได้จากแท็บ `หลักฐานย้อนหลัง` ในหน้าเว็บ

ผลรอบล่าสุด (universe เต็ม, ถือ 20 แท่ง, หัก 30 bps):

| Timeframe | Pattern ที่ชนะค่าฐาน | Pattern ที่ยังไม่ชนะ |
| --- | --- | --- |
| D | ไม่มี (breakout ดีกว่าเพียง 0.45 จุด) | retest, double_bottom, head_shoulders |
| W | retest (+2.9 จุด), breakout (+0.5 จุด) | cup_handle, double_bottom, head_shoulders |
| M | breakout (+5.4 จุด), retest (+2.4 จุด) | double_bottom, head_shoulders |

`head_shoulders` ให้ผลลบทุก timeframe ในฐานะสัญญาณขาย จึงควรใช้เป็นเหตุผล "ไม่ซื้อ" เท่านั้น ไม่ใช่สัญญาณ short

Scanner อ่านไฟล์เหล่านี้ทุกครั้งที่สแกน pattern ที่ยังไม่มีหลักฐานว่าชนะค่าฐานจะถูกกันไม่ให้ขึ้นสถานะ `Candidate` และจะมีคำเตือนกำกับในผลสแกน

ยังเป็น historical event study เท่านั้น: ไม่ได้จำลอง position sizing, สัญญาณซ้อนกัน หรือการทบต้น จึงห้ามใช้แทนผลตอบแทนกองทุนจริง

## หน้า "ข้อมูลบริษัท"

กดปุ่ม `ข้อมูลบริษัท` ในรายละเอียดหุ้น (แทนที่ปุ่ม PDF Report เดิม ซึ่งย้ายไปอยู่ท้ายหน้านี้แทน) หรือเลือกจากแท็บ `ข้อมูลบริษัท` จะเปิดหน้าสรุปที่เรียงตามกรอบของหลักสูตร ONE Investor

**1. หุ้นตัวนี้เป็นหุ้นประเภทไหน** — จำแนกตาม 6 ประเภทของ Peter Lynch จากตัวเลขจริงในงบ ไม่ใช่การติดป้ายด้วยมือ

| ประเภท | เกณฑ์ที่ระบบใช้จำแนก |
| --- | --- |
| Turnarounds | เคยขาดทุนในช่วงที่ดูงบ แล้วปีล่าสุดกลับมามีกำไร |
| Asset Plays | P/BV ต่ำกว่า 1 เท่า ขณะที่ ROE ยังต่ำกว่า 8% |
| Cyclical | ส่วนเบี่ยงเบนของอัตราการเติบโตกำไรเกิน 45 จุด |
| Fast Growers | รายได้โตเฉลี่ยตั้งแต่ 20% ต่อปีขึ้นไป |
| Stalwarts | รายได้โตเฉลี่ย 8-20% ต่อปี |
| Slow Growers | รายได้โตเฉลี่ยต่ำกว่า 8% ต่อปี |

**2. Financial Quality Filter 4 ด่าน** — ทุกข้อคำนวณจากงบที่ยืนยันแล้ว

| ด่าน | ตรวจอะไร | เกณฑ์ผ่าน |
| --- | --- | --- |
| 1 GROWTH | Revenue, EPS, Profit | เติบโตต่อเนื่องอย่างน้อย 3 ปี ทั้งสามตัว |
| 2 QUALITY | ROE, ROIC, Cash Flow, D/E | ROE > 15%, ROIC > 10%, กระแสเงินสดบวกทุกปี, D/E ไม่เกิน 1.5 เท่า |
| 3 EFFICIENCY | Gross / Operating / Net Margin | ทั้งสามคงที่หรือดีขึ้นเมื่อเทียบครึ่งหลังกับครึ่งแรกของช่วงงบ |
| 4 MANAGEMENT | Insider, Dilution | จำนวนหุ้นเพิ่มไม่เกิน 5% ต่อปี |

`ROIC` คำนวณจาก NOPAT หารเงินลงทุนรวม โดยถอดอัตราภาษีจริงจากงบ และ `Dilution` ถอดจำนวนหุ้นจากกำไรสุทธิหารกำไรต่อหุ้นของงวดเดียวกัน

**Insider ownership เป็นข้อเดียวที่ระบบไม่เติมให้** เพราะฟีดข้อมูลสาธารณะที่ใช้ไม่ครอบคลุม หน้าจอจะขึ้นเป็นเครื่องหมาย `?` พร้อมบอกว่าต้องเปิดดูจาก 56-1 One Report หรือ SEC Form 4 เอง ไม่มีการใส่ตัวเลขประมาณลงไปแทน

**3. Margin of Safety** — ประเมินมูลค่าสามทางแล้วใช้ค่ากลาง

- `P/E เฉลี่ยย้อนหลัง` คูณ EPS ล่าสุด โดย P/E แต่ละปีคำนวณจากราคาปิดจริง ณ วันสิ้นงวดนั้น
- `PEG เท่ากับ 1` ใช้เฉพาะเมื่อ EPS โตอย่างน้อย 10% ต่อปี เพราะ PEG ออกแบบมาสำหรับหุ้นเติบโต ถ้าโตช้ากว่านั้นระบบจะข้ามวิธีนี้และบอกเหตุผลไว้
- `มูลค่าทางบัญชีต่อหุ้น` ใช้เป็นพื้นราคา ไม่นำมาเฉลี่ยเป็นมูลค่าที่เหมาะสม

ถ้าวิธีที่ใช้ได้ให้ผลห่างกันเกิน 1.8 เท่า ระบบจะไม่สรุปว่าราคาถูก แต่จะบอกว่ามูลค่ายังไม่ชัดพอจะตัดสินใจ

**4. เชิงคุณภาพ** — Moat, แนวโน้มธุรกิจ และ Thesis ที่บันทึกไว้ พร้อมคำถาม Five Forces ห้าข้อไว้ไล่ตรวจเอง

**ตารางตัวเลขย้อนหลัง** สรุปทิศทางของแต่ละบรรทัดเป็นตัวเลขเดียว ไม่ใช้กราฟ

- รายการที่เป็นจำนวนเงินและ EPS สรุปเป็น **อัตราเติบโตเฉลี่ยต่อปี** เช่น `โตเฉลี่ย +22.6% ต่อปี (เทียบ 3 ปี)` หรือ `แย่ลงเฉลี่ย -7.0% ต่อปี`
- อัตราส่วนอย่าง ROE, Margin และ D/E สรุปเป็น **ส่วนต่างที่เปลี่ยนไป** พร้อมค่าล่าสุด เช่น `ล่าสุด 46.9% · เพิ่มขึ้น 16.5 จุด ใน 3 ปี (ดีขึ้น)` เพราะ ROE ที่ขยับจาก 10% เป็น 15% คือเพิ่ม 5 จุด การรายงานว่าโต 50% ต่อปีจะทำให้เข้าใจผิดว่าเป็นการเติบโตแบบทบต้น
- หนี้สินต่อทุนแยกทิศทางของตัวเลขออกจากคำตัดสิน หนี้ที่ลดลงจะขึ้นว่า `ลดลง ... (ดีขึ้น)`
- กรณีที่กำไรพลิกจากขาดทุนเป็นกำไร ระบบจะบอกเป็นคำว่า `พลิกจากติดลบเป็นบวก` แทนการคิดอัตราทบต้นซึ่งไม่มีความหมายเมื่อฐานติดลบ

**สรุปการตัดสินใจ** ใช้ checklist เดียวกับในหลักสูตร: ต้องผ่านคุณภาพครบทุกด่านก่อน แล้วจึงดูราคา

| ผลลัพธ์ | เงื่อนไข |
| --- | --- |
| `บริษัทดี ราคาดี - เข้าเงื่อนไขซื้อ` | ผ่านครบ 4 ด่าน และ Margin of Safety ตั้งแต่ 20% ขึ้นไป |
| `บริษัทดี แต่แพง - รอ` | ผ่านครบ 4 ด่าน แต่ส่วนลดยังไม่ถึง 20% |
| `ยังไม่ผ่านคุณภาพ - ข้าม` | ตกด่านใดด่านหนึ่ง ระบบจะระบุชื่อด่านที่ตกไว้ด้วย |

ตกด่านเดียวก็ถือว่ายังไม่ผ่าน ตามหลักที่ว่าราคาถูกไม่ใช่เหตุผลให้ซื้อธุรกิจที่คุณภาพยังไม่ถึง

## Paper Trade Journal

แท็บ `Paper Trade` เก็บทุกไม้ที่ตัดสินใจจากระบบ พร้อมแผนที่วางไว้ตอนเข้า (จุดเข้า, จุดตัดขาดทุน, เป้าหมาย, grade, pattern) เมื่อปิดไม้ ระบบจะคำนวณผลตอบแทนสุทธิหลังหักต้นทุน 30 bps และค่า R เทียบกับความเสี่ยงที่วางไว้จริง ข้อมูลอยู่ใน `storage/fastdeep_trade_journal.json`

## Liquidity และ Risk Plan

- สภาพคล่องคำนวณจากมูลค่าซื้อขายกลาง (median ของ `close x volume`) 60 วัน แปลงเป็น USD ก่อนให้คะแนน หุ้นที่ซื้อขายต่ำกว่า 1 ล้าน USD ต่อวันจะมีคำเตือนเรื่องขนาดไม้
- จุดตัดขาดทุนใช้แนวรับจริง แต่ถูกล็อกไว้ในกรอบ 1.4 ถึง 3.0 ATR เพื่อไม่ให้ได้แผนที่ต้องรับความเสี่ยง 25% ต่อไม้ ถ้าความเสี่ยงยังเกิน 12% ระบบจะเตือนให้ลดขนาดไม้

หุ้นสหรัฐใช้ SEC EDGAR XBRL เป็นแหล่งทางการหลักและใช้ Yahoo เป็น fallback เท่านั้น ส่วน Yahoo Finance fundamentals timeseries ยังเป็นแหล่งเริ่มต้นของหุ้นจีนและไทย ซึ่งโดยทั่วไปเปิดให้รายปีเต็ม 4 ปีและงบรายไตรมาสล่าสุดประมาณ 5-9 งวด หน้า dashboard จะแสดงเฉพาะงวดที่ผู้ให้บริการส่งกลับและไม่สร้างตัวเลขย้อนหลังขึ้นเอง เป้าหมายไทยและจีนครบ 5 ปีพร้อม Q1-Q4 จึงยังต้องมีบริการที่ได้รับสิทธิ์ใช้งานและเผยแพร่

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

- ต่อผู้ให้บริการงบการเงินที่มี SLA เพื่อดัน coverage จากรายงาน `fastdeep_financial_coverage.json` ให้ครบ universe
- ทดสอบ out-of-sample แยกช่วงเวลา เพื่อยืนยันว่า edge ของ retest/breakout ราย W และ M ไม่ได้มาจากช่วงตลาดเดียว
- เพิ่ม Telegram alert
- เพิ่ม ingestion เอกสาร 56-1 / 10-K เพื่อส่งต่อ NotebookLM
- ย้าย frontend เป็น Next.js ถ้าต้องการ authentication, database, และ deploy แบบ startup จริง
