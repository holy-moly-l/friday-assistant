@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установи Python 3.11 или 3.12 с python.org и отметь Add Python to PATH.
  pause
  exit /b 1
)
if not exist .venv (
  py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Ошибка установки зависимостей.
  pause
  exit /b 1
)
echo.
echo Готово. Теперь запускай run.bat
pause
