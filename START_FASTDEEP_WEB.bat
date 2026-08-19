@echo off
cd /d "%~dp0"
echo Starting FastDeep Scanner at http://127.0.0.1:8765
start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"
"C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m fastdeep_scanner serve --host 127.0.0.1 --port 8765
pause
