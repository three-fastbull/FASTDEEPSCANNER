@echo off
cd /d "%~dp0"
"C:\Users\three\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m fastdeep_scanner export-static --out storage\fastdeep_static_dashboard.html
start "" "%~dp0storage\fastdeep_static_dashboard.html"
