"""Cancellation of an actual local Ollama image request, without touching user windows."""
import asyncio
import base64
import io
from pathlib import Path
import sys
import tempfile
import time
from PIL import Image
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from desktop_agent import DesktopAgent
from desktop_native import Stopped


async def main():
    with tempfile.TemporaryDirectory() as folder:
        agent=DesktopAgent(folder);buf=io.BytesIO();Image.new('RGB',(640,480),'navy').save(buf,format='PNG')
        agent.ai.mode='local'
        image=base64.b64encode(buf.getvalue()).decode()
        task=asyncio.create_task(agent.cancellable(agent.describe('Подробно опиши изображение и его цвета.',image)))
        await asyncio.sleep(.1);started=time.monotonic();agent.stop()
        try:await asyncio.wait_for(task,1)
        except Stopped:pass
        else:raise AssertionError('Expected cancellation of the running model operation')
        print('REAL_OLLAMA_IMAGE_STOP_PASS',round(time.monotonic()-started,3),'seconds',flush=True)


if __name__=='__main__':asyncio.run(main())
