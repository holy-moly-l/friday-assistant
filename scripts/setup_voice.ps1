$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$python=Join-Path $root '.venv-tts/Scripts/python.exe'
& $python -m pip install --disable-pip-version-check torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
& $python -m pip install --disable-pip-version-check qwen-tts==0.1.1 faster-qwen3-tts==0.2.6 transformers==4.57.3 fastapi==0.116.1 uvicorn==0.35.0 soundfile
exit $LASTEXITCODE
