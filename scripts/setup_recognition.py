"""Download the local multilingual Turbo recognizer used by faster-whisper."""
from pathlib import Path
from huggingface_hub import snapshot_download
root=Path(__file__).resolve().parents[1]
snapshot_download('mobiuslabsgmbh/faster-whisper-large-v3-turbo',
    local_dir=str(root/'models/whisper-large-v3-turbo'),allow_patterns=['*.json','*.bin','*.txt'])
print('Whisper large-v3-turbo installed',flush=True)
