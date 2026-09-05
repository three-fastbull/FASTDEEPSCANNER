@echo off
rem Locate a usable Python and leave it in FASTDEEP_PYTHON for the caller.
rem Every entry point calls this instead of hard-coding a path, because a path
rem that exists on the author's machine does not exist on a student's.
rem Sets ERRORLEVEL 1 and prints Thai guidance when nothing suitable is found.

set "FASTDEEP_PYTHON="

rem 1. An explicit override always wins, for machines with several Pythons.
if defined FASTDEEP_PYTHON_OVERRIDE (
  if exist "%FASTDEEP_PYTHON_OVERRIDE%" (
    call :check "%FASTDEEP_PYTHON_OVERRIDE%"
    if not errorlevel 1 goto :found
  )
)

rem 2. The py launcher ships with the official installer and picks the newest.
for %%V in (3.13 3.12 3.11) do (
  py -%%V -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do (
      call :check "%%P"
      if not errorlevel 1 goto :found
    )
  )
)

rem 3. Whatever "python" resolves to on PATH.
for /f "delims=" %%P in ('where python 2^>nul') do (
  call :check "%%P"
  if not errorlevel 1 goto :found
)

rem 4. The bundled runtime, so the author's own machine keeps working.
set "BUNDLED=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED%" (
  call :check "%BUNDLED%"
  if not errorlevel 1 goto :found
)

echo.
echo [ไม่พบ Python 3.11 ขึ้นไปบนเครื่องนี้]
echo.
echo   วิธีแก้: ติดตั้ง Python 3.12 จาก https://www.python.org/downloads/
echo   ตอนติดตั้ง ต้องติ๊กช่อง "Add Python to PATH" ด้วย
echo   ติดตั้งเสร็จแล้วให้ปิดหน้าต่างนี้ แล้วเปิดใหม่อีกครั้ง
echo.
exit /b 1

:found
exit /b 0

:check
rem datetime.UTC is used across the scanner, so 3.11 is the real floor.
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "FASTDEEP_PYTHON=%~1"
exit /b 0
