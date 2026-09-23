"""Camera/worker test host: real API, disposable Win32 window, isolated history."""
import asyncio,json,os,sys,tempfile,subprocess,time
from contextlib import asynccontextmanager
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['FRIDAY_PORT']='17843'
sys.path.insert(0,str(root/'backend'))
import app as friday
import desktop_native as native
import uvicorn
from fastapi.responses import FileResponse

with tempfile.TemporaryDirectory(prefix='friday-gestures-') as folder:
    temp=Path(folder);friday.DB=temp/'test.db';friday.init_db()
    fixture=subprocess.Popen([sys.executable,str(root/'tests/desktop_fixture.py'),str(temp/'window.json')],creationflags=subprocess.CREATE_NO_WINDOW,env={**os.environ,'FRIDAY_TEST_PARENT_PID':str(os.getpid())})
    try:
        for _ in range(100):
            if (temp/'window.json').exists():break
            time.sleep(.05)
        window=native.info(json.loads((temp/'window.json').read_text())['hwnd'])
        native.windows=lambda:[native.same(window)]
        for service in ('llm','stt','tts'):friday.state[service]='ready'
        @friday.app.get('/test-hands.jpg')
        def test_image():return FileResponse(root/'data/right_hands.jpg')
        friday.app.router.routes.insert(0,friday.app.router.routes.pop())
        @asynccontextmanager
        async def lifespan(app):
            watch=asyncio.create_task(friday.gestures.watchdog())
            yield
            watch.cancel();friday.gestures.stop()
        friday.app.router.lifespan_context=lifespan
        (root/'data/gesture-runtime.json').write_text(json.dumps(dict(port=friday.PORT,token=friday.TOKEN,hwnd=window['hwnd'])),encoding='utf-8')
        uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,log_level='warning')
    finally:
        fixture.terminate();fixture.wait(timeout=5)
