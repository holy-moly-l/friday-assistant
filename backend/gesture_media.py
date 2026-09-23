"""Local Windows media sessions. Never inject player shortcuts into unrelated windows."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from pc import CommandError
from desktop_native import check


async def manager():
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        return await asyncio.wait_for(GlobalSystemMediaTransportControlsSessionManager.request_async(), 3)
    except (ImportError, OSError, RuntimeError, asyncio.TimeoutError) as exc:
        raise CommandError('Медиасессии Windows недоступны. Откройте видео в совместимом плеере.') from exc


async def sessions():
    mgr = await manager()
    result = []
    for session in mgr.get_sessions():
        try:
            info = session.get_playback_info()
            props = await asyncio.wait_for(session.try_get_media_properties_async(), 1)
            result.append(dict(id=session.source_app_user_model_id, title=props.title if props else '',
                playing=int(info.playback_status)==4, seek=info.controls.is_playback_position_enabled,
                toggle=info.controls.is_play_pause_toggle_enabled))
        except (OSError, RuntimeError, asyncio.TimeoutError):
            continue
    # Duplicate app IDs cannot be safely distinguished by a subsequent request.
    for item in result:
        item['ambiguous'] = sum(s['id']==item['id'] for s in result)>1
    return result


def position(session):
    timeline = session.get_timeline_properties()
    value = timeline.position.total_seconds()
    if int(session.get_playback_info().playback_status)==4:
        elapsed = (datetime.now(timezone.utc)-timeline.last_updated_time).total_seconds()
        value += max(0, min(60, elapsed))
    return value, timeline


async def perform(source, action, cancel):
    check(cancel)
    mgr = await manager()
    matches = [s for s in mgr.get_sessions() if s.source_app_user_model_id==source]
    if len(matches)!=1:
        raise CommandError('Выберите медиаплеер заново: сессия закрылась или найдено несколько совпадений.')
    session = matches[0]
    info = session.get_playback_info()
    check(cancel)
    if action=='play_pause':
        if not info.controls.is_play_pause_toggle_enabled:
            raise CommandError('Этот плеер не поддерживает паузу через Windows.')
        was_playing = int(info.playback_status)==4
        ok = await asyncio.wait_for(session.try_toggle_play_pause_async(), 2)
        expected = 5 if was_playing else 4
        verify = lambda: int(session.get_playback_info().playback_status)==expected
        message = 'Пауза' if was_playing else 'Воспроизведение'
    else:
        if action not in ('seek_forward','seek_backward'):raise CommandError('Неизвестное действие.')
        if not info.controls.is_playback_position_enabled:
            raise CommandError('Этот плеер не разрешает перемотку через Windows. Выберите другой плеер; прямой эфир перематывать нельзя.')
        old, timeline = position(session)
        end = timeline.max_seek_time.total_seconds()
        start = timeline.min_seek_time.total_seconds()
        if end<=start:raise CommandError('Перемотка пока недоступна: у видео нет доступной временной шкалы.')
        target = max(start, min(end, old+(5 if action=='seek_forward' else -5)))
        if abs(target-old)<1:raise CommandError('Достигнут край видео.')
        ok = await asyncio.wait_for(session.try_change_playback_position_async(round(target*10_000_000)), 2)
        verify = lambda: abs(position(session)[0]-target)<2
        message = 'Вперёд на 5 секунд' if action=='seek_forward' else 'Назад на 5 секунд'
    if not ok:raise CommandError('Плеер отклонил действие.')
    for _ in range(15):
        check(cancel)
        if verify():return message
        await asyncio.sleep(.08)
    raise CommandError('Команда передана, но плеер не подтвердил изменение.')
