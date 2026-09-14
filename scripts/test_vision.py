r"""Run with .venv\Scripts\python.exe scripts\test_vision.py (no Friday server needed)."""
__test__ = False
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def main():
    parser=argparse.ArgumentParser(description='One screenshot → local Ollama → raw model answer')
    parser.add_argument('--scope',choices=['window','monitor','all_screens'],default='monitor')
    parser.add_argument('--window',help='Installed app name or HWND (decimal / 0x...)')
    parser.add_argument('--monitor',type=int)
    parser.add_argument('--model',help='Default: current Friday setting, otherwise qwen3.5:4b')
    parser.add_argument('--question',default='Опиши, что видно на изображении')
    args=parser.parse_args()
    os.environ['FRIDAY_DEBUG']='1'
    import desktop_native as native
    from desktop_vision import image_query
    from pc import CommandError
    model='qwen3.5:4b'
    try:model=json.loads((ROOT/'data/desktop-settings.json').read_text('utf-8')).get('model',model)
    except (OSError,ValueError):pass
    cancel=threading.Event()
    try:
        if args.scope=='window':
            window=None
            if args.window:
                try:window=native.info(int(args.window,0))
                except ValueError:window=native.Foreground().target(args.window,None)
            else:window=native.info(native.u.GetForegroundWindow())
            if not window:raise CommandError('Окно не найдено. Укажите --window calculator или HWND.')
            shot=native.capture_window(window,cancel)
        elif args.scope=='all_screens':shot=native.capture_all_screens(cancel)
        else:shot=native.capture_screen(cancel,args.monitor)
        print(asyncio.run(image_query(args.model or model,args.question,shot['image'])),flush=True)
        return 0
    except KeyboardInterrupt:
        cancel.set();print('Остановлено.',file=sys.stderr);return 130
    except Exception as exc:
        print(f'VISION TEST FAILED: {exc}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
