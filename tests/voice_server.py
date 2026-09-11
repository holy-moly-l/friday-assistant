"""Real models, isolated database and port for speech regression tests."""
import json, os, sys, tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['FRIDAY_PORT']=os.environ.get('VOICE_TEST_PORT','17840')
sys.path.insert(0,str(root/'backend'))
import app as friday
import uvicorn
with tempfile.TemporaryDirectory(prefix='friday-voice-test-') as temp:
    friday.DATA=Path(temp)
    friday.DB=Path(temp)/'test.db'
    (root/'data/voice-test-runtime.json').write_text(json.dumps({'port':friday.PORT,'token':friday.TOKEN}),encoding='utf8')
    if os.environ.get('VOICE_NATIVE_TEST')=='1':
        (root/'data/runtime.json').write_text(json.dumps({'port':friday.PORT,'token':friday.TOKEN,'pid':os.getpid()}),encoding='utf8')
    uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,log_level='warning',ws='websockets-sansio')
