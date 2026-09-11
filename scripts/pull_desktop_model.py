import httpx,json,time
last=0
with httpx.Client(timeout=None,trust_env=False) as client:
    with client.stream('POST','http://127.0.0.1:11434/api/pull',json={'model':'qwen3.5:4b','stream':True}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            data=json.loads(line)
            if data.get('error'):raise RuntimeError(data['error'])
            if time.monotonic()-last>15 or data.get('status')=='success':
                print(data.get('status'),round(data.get('completed',0)/max(1,data.get('total',1))*100),'%',flush=True);last=time.monotonic()
