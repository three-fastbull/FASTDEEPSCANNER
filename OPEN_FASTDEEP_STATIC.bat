@echo off
cd /d "%~dp0"
call "%~dp0_find_python.bat"
if errorlevel 1 pause & exit /b 1
"%FASTDEEP_PYTHON%" -m fastdeep_scanner export-static --out storage\fastdeep_static_dashboard.html
if errorlevel 1 (
  echo.
  echo สร้างไฟล์ไม่สำเร็จ - ตรวจว่าดึงข้อมูลราคาแล้วหรือยัง
  pause
  exit /b 1
)
start "" "%~dp0storage\fastdeep_static_dashboard.html"