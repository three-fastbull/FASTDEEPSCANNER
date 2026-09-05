@echo off
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if errorlevel 1 pause & exit /b 1
echo กำลังดึงราคาล่าสุดจาก Yahoo Finance...
"%FASTDEEP_PYTHON%" -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 5y --interval 1d --pause 0.05 --min-success-ratio 0.97 --workers 6 --request-timeout 12
if errorlevel 1 (
  echo.
  echo ดึงราคาไม่สำเร็จ - ตรวจอินเทอร์เน็ต หรือรอสักครู่แล้วลองใหม่
  echo ถ้าค้างนาน ให้กด Ctrl+C แล้วรันไฟล์นี้อีกครั้ง
  pause
  exit /b 1
)
echo.
echo กำลังเปิด FastDeep Scanner...
call "%~dp0OPEN_FASTDEEP_SCANNER.bat"