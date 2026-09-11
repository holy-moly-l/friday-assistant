"""Real Vosk + Whisper, temporary chat database, no microphone or cloud calls."""
import json,os,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['FRIDAY_PORT']=os.environ.get('WAKE_TEST_PORT','17839')
sys.path.insert(0,str(root/'backend'))
import app as friday
import uvicorn
with tempfile.TemporaryDirectory(prefix='friday-wake-') as temp:
    friday.DB=Path(temp)/'test.db';friday.init_db()
    friday.load_whisper()
    assert friday.state['stt']=='ready',friday.state
    friday.state.update(llm='ready',tts='ready')
    runtime={'port':friday.PORT,'token':friday.TOKEN,'pid':os.getpid()}
    (root/'data/wake-test-runtime.json').write_text(json.dumps(runtime),encoding='utf8')
    if os.environ.get('WAKE_NATIVE_TEST')=='1':(root/'data/runtime.json').write_text(json.dumps(runtime),encoding='utf8')
    uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,lifespan='off',log_level='warning',ws='websockets-sansio')
