@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title ติดตั้ง FastDeep Scanner

echo.
echo   ============================================
echo      ติดตั้ง FastDeep Scanner
echo   ============================================
echo.
echo   ใช้เวลาประมาณ 20-25 นาที และใช้พื้นที่ราว 620 MB
echo   ระหว่างนี้เปิดค้างไว้ได้ ไม่ต้องเฝ้า
echo.
echo   ใส่อีเมลมาเลยก็ได้:  setup.bat you@example.com
echo.

echo   [1/5] ค้นหา Python...
call "%~dp0_find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
rem Reading the version through for /f is brittle when the interpreter path is
rem quoted, and step 5 prints it anyway, so just confirm one was found.
echo         พบแล้ว: %FASTDEEP_PYTHON%
echo.

echo   [2/5] ตั้งค่าอีเมลสำหรับดึงงบการเงิน...
if exist ".env" (
  echo         มีไฟล์ .env อยู่แล้ว ข้ามขั้นตอนนี้
) else (
  echo.
  echo         SEC EDGAR ซึ่งเป็นแหล่งงบการเงินทางการของสหรัฐ
  echo         บังคับให้ระบุอีเมลที่ติดต่อกลับได้จริงในทุกคำขอ
  echo         ใช้อีเมลของตัวเองเท่านั้น ห้ามใช้ร่วมกับเพื่อน
  echo.
  rem Accepting the address as an argument lets a class run this unattended and
  rem makes the step testable; typing it stays the default for one student.
  set "STUDENT_EMAIL=%~1"
  if "!STUDENT_EMAIL!"=="" set /p STUDENT_EMAIL="         พิมพ์อีเมลของคุณแล้วกด Enter: "
  if "!STUDENT_EMAIL!"=="" (
    echo.
    echo         ยังไม่ได้ใส่อีเมล - ยกเลิกการติดตั้ง
    pause
    exit /b 1
  )
  > ".env" echo FASTDEEP_SEC_CONTACT=!STUDENT_EMAIL!
  >> ".env" echo ANTHROPIC_API_KEY=
  echo         บันทึกลงไฟล์ .env แล้ว
)
echo.

echo   [3/5] ดึงราคาหุ้น 1,458 ตัว ย้อนหลัง 5 ปี (ประมาณ 2-5 นาที)...
"%FASTDEEP_PYTHON%" -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 5y --interval 1d --pause 0.05 --min-success-ratio 0.90 --workers 6 --request-timeout 12 --deadline-seconds 1200
if errorlevel 1 (
  echo.
  echo         ดึงราคาไม่สำเร็จ
  echo         สาเหตุที่พบบ่อยคือผู้ให้บริการจำกัดอัตราชั่วคราว
  echo         ให้รอสัก 10 นาที แล้วรันไฟล์นี้ใหม่ ระบบจะทำต่อจากเดิม
  pause
  exit /b 1
)
echo.

echo   [4/5] ดึงงบการเงินจาก SEC EDGAR (ประมาณ 15 นาที)...
"%FASTDEEP_PYTHON%" -m fastdeep_scanner update-sec-financials --universe data\fastdeep_universe.csv --cache-dir data\financial_cache --groups SP500,NASDAQ100,SP400 --pause 0.20 --request-timeout 30 --cache-max-age-hours 168 --retries 2 --coverage-out data\fastdeep_financial_coverage.json --ticker-cache data\sec_company_tickers.json
if errorlevel 1 (
  echo.
  echo         ดึงงบไม่ครบ แต่ส่วนที่ได้มาใช้งานได้แล้ว
  echo         รันไฟล์นี้ใหม่ภายหลังเพื่อเก็บส่วนที่ขาด
)
echo.

echo   [5/5] ตรวจความพร้อม...
"%FASTDEEP_PYTHON%" -m fastdeep_scanner doctor
if errorlevel 1 (
  echo.
  echo   ยังติดตั้งไม่ครบ - อ่านวิธีแก้ด้านบนแล้วรันไฟล์นี้ใหม่
  pause
  exit /b 1
)

echo.
echo   ============================================
echo      ติดตั้งเสร็จแล้ว
echo   ============================================
echo.
echo   เปิดโปรแกรมด้วยไฟล์  OPEN_FASTDEEP_SCANNER.bat
echo   หรือกด Enter เพื่อเปิดตอนนี้เลย
echo.
pause >nul
call "%~dp0OPEN_FASTDEEP_SCANNER.bat"