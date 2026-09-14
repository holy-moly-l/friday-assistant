"""Force the packaged-app resolver on real Windows Calculator, without an EXE path."""
from pathlib import Path
import sys
import threading
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
import desktop_native as n
import pc


def main():
    if any(n.matches(win,'calculator') for win in n.windows()):
        raise RuntimeError('Close Calculator before this isolated packaged-app launch test')
    cancel=threading.Event();window=None
    try:
        with patch.object(pc,'app_path',side_effect=pc.AppNotFound('EXE deliberately unavailable')):
            resolved=pc.resolve_application('calculator')
            assert resolved['kind']=='shell' and 'WindowsCalculator' in resolved['value']
            window=n.launch('calculator',cancel)
            assert n.same(window) and window['launch_status']=='started'
            print('PACKAGED_SHELL_PASS',resolved['value'],'verified HWND',window['hwnd'],flush=True)
    finally:
        if window and n.info(window['hwnd']):n.window_action(window,'close',1,cancel)


if __name__=='__main__':main()
