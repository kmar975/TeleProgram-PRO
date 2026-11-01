@echo off
title Program TV - teleman.pl
cd /d "%~dp0"

echo ========================================================
echo       Uruchamianie aplikacji Program TV (teleman.pl)
echo ========================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [BLAD] Nie znaleziono Pythona w PATH!
    echo Zainstaluj Python ze strony https://www.python.org/
    echo.
    pause
    exit /b 1
)

python main.py

if errorlevel 1 (
    echo.
    echo [INFO] Aplikacja zakonczyla dzialanie z bledem.
    pause
)
