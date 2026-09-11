"""Native app test backend: temporary history/settings and disposable UI fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
root=Path(__file__).resolve().parents[1]
os.environ['FRIDAY_PORT']='17835'
sys.path.insert(0,str(root/'backend'))
import app as friday
import uvicorn
with tempfile.TemporaryDirectory(prefix='friday-desktop-ui-') as folder:
    temp=Path(folder);friday.DB=temp/'test.db';friday.init_db()
    friday.desktop.path=temp/'settings.json'
    friday.load_whisper();friday.warm_llm();friday.state['tts']='ready'
    fixture=subprocess.Popen([sys.executable,str(root/'tests/desktop_fixture.py'),str(temp/'window.json')],creationflags=subprocess.CREATE_NO_WINDOW,env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid())})
    try:
        for _ in range(100):
            if (temp/'window.json').exists():break
            time.sleep(.1)
        # Native UI tests are restricted to our disposable window even if the
        # test runner or the user switches foreground while they execute.
        import desktop_native as native
        fixture_window=native.info(json.loads((temp/'window.json').read_text())['hwnd'])
        friday.desktop.foreground.target=lambda name,context:native.same(fixture_window)
        runtime={'port':friday.PORT,'token':friday.TOKEN,'pid':os.getpid()}
        (root/'data/runtime.json').write_text(json.dumps(runtime),encoding='utf-8')
        (root/'data/desktop-test-runtime.json').write_text(json.dumps(runtime),encoding='utf-8')
        uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,lifespan='off',log_level='warning',ws='websockets-sansio')
    finally:
        friday.desktop.stop();friday.desktop.foreground.closed.set()
        if fixture.poll() is None:fixture.terminate()
        fixture.wait(timeout=5)
