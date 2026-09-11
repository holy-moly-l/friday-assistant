"""Isolated UI fixture: actual command endpoints, temporary DB, no model loading."""
import json
import os
from pathlib import Path
import sys
import tempfile
os.environ['FRIDAY_PORT']='17839'
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
import app as friday
import uvicorn
with tempfile.TemporaryDirectory(prefix='friday-catalog-test-') as temp:
    friday.DB=Path(temp)/'test.db'
    friday.init_db()
    for service in ('llm','stt','tts'):friday.state[service]='ready'
    (root/'data/catalog-test-runtime.json').write_text(json.dumps({'port':friday.PORT,'token':friday.TOKEN}),encoding='utf8')
    uvicorn.run(friday.app,host='127.0.0.1',port=friday.PORT,lifespan='off',log_level='warning')
