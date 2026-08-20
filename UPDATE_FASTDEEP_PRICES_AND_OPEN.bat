@echo off
cd /d "%~dp0"
echo Updating real prices from Yahoo Finance...
"C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m fastdeep_scanner update-prices --universe data\fastdeep_universe.csv --out data\fastdeep_prices.csv --range 2y --interval 1d --pause 0.05
if errorlevel 1 (
  echo.
  echo Price update failed. Check your internet connection or symbol list.
  pause
  exit /b 1
)
echo.
echo Opening FastDeep Scanner live dashboard...
call "%~dp0OPEN_FASTDEEP_SCANNER.bat"
