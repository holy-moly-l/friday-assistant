@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Сначала запусти install.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pyinstaller
pyinstaller --noconfirm --clean --windowed --name FridayVoiceRecorder ^
  --add-data "corpus.json.gz;." ^
  app.py
if errorlevel 1 (
  echo Сборка завершилась с ошибкой.
  pause
  exit /b 1
)
echo.
echo Готово: dist\FridayVoiceRecorder\FridayVoiceRecorder.exe
pause
