import asyncio
import sys
import threading
import time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import gesture_control as g
import gesture_media as media
from pc import CommandError

WINDOW=dict(hwnd=123,pid=77,created=1,title='Fixture',process='fixture.exe',rect=[100,100,700,500],minimized=False,maximized=False)
SCREENS=[dict(index=2,device_id='left',rect=[-1920,0,0,1040],bounds=[-1920,0,0,1080]),dict(index=1,device_id='right',rect=[0,0,1920,1040],bounds=[0,0,1920,1080])]

@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(g.native,'windows',lambda:[WINDOW.copy()])
    monkeypatch.setattr(g.native,'same',lambda w:w.copy())
    monkeypatch.setattr(g.native,'monitors',lambda:SCREENS)
    monkeypatch.setattr(g.native,'window_monitor',lambda w:SCREENS[1])
    return g.GestureControl()

def run(coro):return asyncio.run(coro)

def test_explicit_target_and_stale_token(engine):
    with pytest.raises(CommandError):run(engine.arm('windows',999))
    token=run(engine.arm('windows',123))['token'];engine.stop()
    with pytest.raises(CommandError):run(engine.action(token,1,'maximize'))
    assert not engine.status()['armed']

def test_late_stop_cannot_cancel_new_session(engine):
    old=run(engine.arm('windows',123))['token']
    new=run(engine.arm('windows',123))['token']
    engine.stop_session(old)
    assert engine.heartbeat(new)['armed']
    engine.stop_session(new)
    assert not engine.status()['armed']

def test_wrong_stop_token_cannot_cancel_pending_arm(engine,monkeypatch):
    async def sessions():
        await asyncio.sleep(.02);return [dict(id='player',ambiguous=False)]
    monkeypatch.setattr(media,'sessions',sessions)
    async def task():
        pending=asyncio.create_task(engine.arm('media',media='player'))
        await asyncio.sleep(.01);engine.stop_session('old-session')
        new=(await pending)['token']
        assert engine.heartbeat(new)['armed']
        engine.stop_session(new)
    run(task())

def test_lease_expiry(engine):
    token=run(engine.arm('windows',123))['token'];engine.session['seen']-=2
    with pytest.raises(CommandError):engine.heartbeat(token)
    assert not engine.status()['armed']

def test_voice_command_disarms(engine):
    run(engine.arm('windows',123));engine.busy=lambda:True
    assert not engine.status()['armed']
    with pytest.raises(CommandError):run(engine.arm('windows',123))

def test_no_arbitrary_actions(engine):
    token=run(engine.arm('windows',123))['token']
    for kind in ['click','type','close','press_key','play_pause']:
        with pytest.raises(CommandError):run(engine.action(token,10+len(kind),kind))

def test_drag_requires_start_and_finite_points(engine):
    token=run(engine.arm('windows',123))['token']
    with pytest.raises(CommandError):run(engine.action(token,1,'drag_move'))
    assert not engine.status()['armed']
    token=run(engine.arm('windows',123))['token']
    for x in [float('nan'),float('inf'),-1,2]:
        with pytest.raises(CommandError):run(engine.action(token,2,'drag_start',x,.5))

def test_drag_release_identity_and_replayed_packet(engine,monkeypatch):
    calls=[];monkeypatch.setattr(g,'move_drag',lambda *a:calls.append(a))
    async def task():
        token=(await engine.arm('windows',123))['token']
        await engine.action(token,1,'drag_start',.4,.4)
        await engine.action(token,2,'drag_move',.5,.5)
        assert len(calls)==1 and calls[0][0]['pid']==77
        with pytest.raises(CommandError):await engine.action(token,2,'drag_move',.8,.5)
        await engine.action(token,3,'release')
        assert not engine.status()['dragging']
    run(task())

def test_physical_monitor_order_preserves_windows_id(engine,monkeypatch):
    calls=[];monkeypatch.setattr(g.native,'window_action',lambda *a:calls.append(a))
    token=run(engine.arm('windows',123))['token']
    run(engine.action(token,1,'monitor_left'))
    assert calls[0][2]==2

def test_monitor_missing_disarms(engine):
    token=run(engine.arm('windows',123))['token']
    with pytest.raises(CommandError):run(engine.action(token,1,'monitor_right'))
    assert not engine.status()['armed']

@pytest.mark.parametrize('dx,dy,expected',[(0,0,(100,100)),(1,1,(1320,640)),(-1,-1,(0,0))])
def test_drag_bounds(dx,dy,expected):assert g.drag_position(WINDOW['rect'],SCREENS[1]['rect'],dx,dy)==expected

def test_negative_monitor_bounds():assert g.drag_position([-1700,100,-1100,500],SCREENS[0]['rect'],-1,0)==(-1920,100)

def test_maximize_toggle_and_cooldown(engine,monkeypatch):
    calls=[];monkeypatch.setattr(g.native,'window_action',lambda *a:calls.append(a))
    token=run(engine.arm('windows',123))['token'];run(engine.action(token,1,'maximize'));run(engine.action(token,2,'maximize'))
    assert len(calls)==1 and calls[0][1]=='maximize'

def test_stop_cancels_inflight_media(engine,monkeypatch):
    async def sessions():return [dict(id='player',ambiguous=False)]
    cancelled=[]
    async def perform(*a):
        try:await asyncio.sleep(20)
        finally:cancelled.append(True)
    monkeypatch.setattr(media,'sessions',sessions);monkeypatch.setattr(media,'perform',perform)
    async def task():
        token=(await engine.arm('media',media='player'))['token']
        action=asyncio.create_task(engine.action(token,1,'play_pause'));await asyncio.sleep(.02);engine.stop()
        with pytest.raises(CommandError):await action
        assert cancelled and not engine.status()['armed']
    run(task())

def test_backend_failures_stop_lease(engine,monkeypatch):
    def failed(*a):raise OSError('test')
    monkeypatch.setattr(g.native,'window_action',failed)
    token=run(engine.arm('windows',123))['token']
    with pytest.raises(OSError):run(engine.action(token,1,'maximize'))
    assert not engine.status()['armed']

def test_stop_during_arm_cannot_reactivate(engine,monkeypatch):
    async def sessions():
        await asyncio.sleep(.05);return [dict(id='player',ambiguous=False)]
    monkeypatch.setattr(media,'sessions',sessions)
    async def task():
        pending=asyncio.create_task(engine.arm('media',media='player'))
        await asyncio.sleep(.01);engine.stop()
        with pytest.raises(CommandError):await pending
        assert not engine.status()['armed']
    run(task())

def test_media_unsupported_seek_never_sends(engine,monkeypatch):
    from types import SimpleNamespace as S
    class Session:
        source_app_user_model_id='own-player'
        def get_playback_info(self):return S(controls=S(is_playback_position_enabled=False))
        def try_change_playback_position_async(self,*a):raise AssertionError('Unsupported seek dispatched')
    async def manager():return S(get_sessions=lambda:[Session()])
    monkeypatch.setattr(media,'manager',manager)
    with pytest.raises(CommandError,match='не разрешает перемотку'):run(media.perform('own-player','seek_forward',threading.Event()))

def test_media_closed_target_does_not_fallback_to_another_player(monkeypatch):
    from types import SimpleNamespace as S
    async def manager():return S(get_sessions=lambda:[S(source_app_user_model_id='other-player')])
    monkeypatch.setattr(media,'manager',manager)
    with pytest.raises(CommandError,match='Выберите медиаплеер заново'):run(media.perform('own-player','play_pause',threading.Event()))
