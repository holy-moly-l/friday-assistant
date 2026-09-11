import asyncio,json
from pathlib import Path
import soundfile as sf
from websockets.asyncio.client import connect
root=Path(__file__).resolve().parents[1]
runtime=json.loads((root/'data/wake-test-runtime.json').read_text(encoding='utf8'))
async def scenario(names,expected):
    async with connect(f"ws://127.0.0.1:{runtime['port']}/api/wake",origin=f"http://127.0.0.1:{runtime['port']}") as socket:
        await socket.send(json.dumps({'token':runtime['token'],'sample_rate':16000}))
        assert json.loads(await socket.recv())['type']=='ready'
        events=[]
        for name in names:
            samples,sr=sf.read(root/f'data/wake-{name}.wav',dtype='int16');assert sr==16000
            pcm=samples.tobytes()
            for i in range(0,len(pcm),3200):await socket.send(pcm[i:i+3200])
            while True:
                event=json.loads(await asyncio.wait_for(socket.recv(),12));events.append(event)
                if event['type'] in ('listening','command','cancelled'):break
        assert events[-1]['type']==expected,events
        if expected=='command':assert 'час' in events[-1]['text'].lower(),events
        print(names,[e['type'] for e in events],flush=True)
async def main():
    await scenario(['wake','plain'],'command')
    await scenario(['wake','cancel'],'cancelled')
asyncio.run(main())
