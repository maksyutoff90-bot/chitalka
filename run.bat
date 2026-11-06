@echo off
chcp 65001 >nul
setlocal enableextensions
cd /d "%~dp0"
title Chitalka

rem 1. Ready build - no Python needed.
if exist "dist\Chitalka\Chitalka.exe" (
    start "" "dist\Chitalka\Chitalka.exe"
    exit /b 0
)

rem 2. Find Python 3.
set "PY="
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PY=py -3"
    )
)
if not defined PY (
    echo.
    echo   Python not found.
    echo   Install Python 3.10+ from python.org with "Add python.exe to PATH"
    echo   or run the ready build: dist\Chitalka\Chitalka.exe
    echo.
    pause
    exit /b 1
)

rem 3. Check dependencies and install them on first run.
%PY% -c "import PIL, pymupdf, lxml" >nul 2>nul
if errorlevel 1 (
    echo   First run: installing dependencies...
    %PY% -m pip install --disable-pip-version-check --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   Could not install dependencies.
        echo   Try manually:  %PY% -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
)

rem 4. Start without a console window.
if /i "%PY%"=="python" (
    where pythonw >nul 2>nul
    if not errorlevel 1 (
        start "" pythonw "main.py"
        exit /b 0
    )
    python "main.py"
    if errorlevel 1 pause
    exit /b 0
)

start "" pyw -3 "main.py"
if errorlevel 1 (
    py -3 "main.py"
    if errorlevel 1 pause
)
exit /b 0
