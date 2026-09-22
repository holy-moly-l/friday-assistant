"""Isolated browser fixture: real workflow/API, fake Telegram only."""
import json
import os
from pathlib import Path
import sys
import tempfile
os.environ['FRIDAY_PORT'] = '17841'
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'backend'),str(root/'tests')]
import app as friday
from desktop_agent import DesktopAgent
from telegram_messages import TelegramMessages
from test_telegram_messages import FakeTelegram, FakeComposer
from message_composer import ComposedMessage
import uvicorn

class UIComposer(FakeComposer):
    async def compose_message(self,raw_text,*args,**kwargs):
        if raw_text=='пусть приедет сегодня в 12 часов':return ComposedMessage('Приезжай сегодня в 12 часов.')
        return await super().compose_message(raw_text,*args,**kwargs)

with tempfile.TemporaryDirectory(prefix='friday-telegram-ui-') as folder:
    friday.DB = Path(folder)/'history.db'; friday.init_db()
    friday.desktop = DesktopAgent(folder)
    fake = FakeTelegram()
    friday.desktop.telegram = TelegramMessages(fake.call,fake.launch,UIComposer())
    for service in ('llm','stt','tts'): friday.state[service] = 'ready'
    @friday.app.get('/api/test-telegram')
    def state(): return dict(sent=fake.sent,draft_length=len(fake.draft),pending=bool(friday.desktop.pending))
    # Route before the frontend catch-all mount. This endpoint exists only here.
    friday.app.router.routes.insert(0,friday.app.router.routes.pop())
    (root/'data/telegram-ui-runtime.json').write_text(json.dumps(dict(port=friday.PORT,token=friday.TOKEN)),encoding='utf-8')
    uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,lifespan='off',log_level='warning')
