"""Real, standalone subscription vision diagnostic; screenshots stay temporary.

  .venv\Scripts\python.exe scripts/test_codex_vision.py --compare --runs 3
  .venv\Scripts\python.exe scripts/test_codex_vision.py --monitor 2
  .venv\Scripts\python.exe scripts/test_codex_vision.py --window calculator

stdout includes the requested answer; the saved report contains timings only.
"""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import desktop_native as native
from ai_router import prepare_image
from ai_providers import CodexProvider,LocalOllamaProvider

async def main(args):
    cancel=threading.Event();started=time.perf_counter()
    if args.window:
        windows=[w for w in native.windows() if native.matches(w,args.window)]
        if len(windows)!=1:raise RuntimeError('Укажите одно открытое окно; найдено: '+str(len(windows)))
        capture=native.capture_window(windows[0],cancel)
    else:capture=native.capture_screen(cancel,args.monitor)
    capture_ms=round((time.perf_counter()-started)*1000)
    prepared=prepare_image(capture['image'],not args.no_optimize)
    codex=CodexProvider();health=await codex.health_check(force=True)
    print(json.dumps({'codex':health,'original':prepared.original,'sent':prepared.sent,'size_kb':prepared.size_kb,'capture_ms':capture_ms,'preprocess_ms':prepared.preprocess_ms},ensure_ascii=False),flush=True)
    providers=[codex]
    if args.compare:providers.append(LocalOllamaProvider())
    results=[]
    for run in range(args.runs):
        for provider in providers:
            started=time.perf_counter()
            result=await provider.analyze_image(prepared.encoded,'Кратко опиши, что видно на изображении. Одно-два предложения.')
            elapsed=round((time.perf_counter()-started)*1000)
            reply=json.loads(result.content)['reply']
            row={'run':run+1,'provider':result.provider,'model':result.model,'latency_ms':elapsed,
                 'answer_length':len(reply),**result.metrics}
            results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True);print(reply,flush=True)
    medians={name:{'latency_ms':statistics.median(r['latency_ms'] for r in results if r['provider']==name),
        'first_response_ms':statistics.median(r['first_response_ms'] for r in results if r['provider']==name),
        'answer_length':statistics.median(r['answer_length'] for r in results if r['provider']==name)} for name in {r['provider'] for r in results}}
    report={'auth':'chatgpt','version':health['version'],'scope':capture['scope'],
        'original':prepared.original,'sent':prepared.sent,'size_kb':prepared.size_kb,'capture_ms':capture_ms,
        'preprocess_ms':prepared.preprocess_ms,'runs':results,'median':medians,
        'note':'Identical screenshot and prompt. Sequential interleaved runs; caches are not cleared. CLI first_response is a complete agent message; Ollama first_response is the first content token.'}
    if args.compare:report['speedup']=round(medians['ollama']['latency_ms']/medians['codex']['latency_ms'],2)
    output=ROOT/'data/codex-vision-benchmark.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('MEDIAN',json.dumps(medians,ensure_ascii=False),'speedup',report.get('speedup'),flush=True)
    print('Timing report:',output,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare',action='store_true');parser.add_argument('--runs',type=int,choices=range(1,6),default=1)
    parser.add_argument('--monitor',type=int);parser.add_argument('--window');parser.add_argument('--no-optimize',action='store_true')
    asyncio.run(main(parser.parse_args()))
