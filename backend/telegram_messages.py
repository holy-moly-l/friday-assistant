"""Deterministic Telegram messaging state machine, independent of Ollama.

The single Send call is reachable only after an expiring one-use UI confirmation.
No retry follows a send attempt, even on timeout, cancellation, or lost UI state.
"""
import asyncio
import anyio
from dataclasses import dataclass, field
import secrets
import threading
import time
import desktop_native as native
import telegram_uia
from desktop_trace import trace
from pc import CommandError
from command_language import request_text
from telegram_language import message_intent, recipient_name, recipient_matches, key, SELF, PRONOUNS, CANCEL


@dataclass
class PendingMessage:
    recipient: str = ''
    text: str | None = None
    verified_chat: dict | None = None
    confirmation_required: bool = True
    status: str = 'awaiting_text'
    window: dict | None = None
    username: str = ''
    expires: float = field(default_factory=lambda: time.monotonic() + 600)


class TelegramMessages:
    def __init__(self, adapter=telegram_uia.call, launch=native.launch):
        self.adapter = adapter
        self.launch = launch
        self.pending_messages = {}
        self.context = {}

    def prune(self):
        now = time.monotonic()
        for sid, item in list(self.pending_messages.items()):
            if now > item.expires: self.pending_messages.pop(sid, None)
        for sid, item in list(self.context.items()):
            if now > item.expires: self.context.pop(sid, None)
        for mapping in (self.pending_messages, self.context):
            while len(mapping) > 100: mapping.pop(next(iter(mapping)))

    def stop(self):
        self.pending_messages.clear()

    def cancelling(self, text, session):
        return session in self.pending_messages and key(request_text(text)) in CANCEL

    def handles(self, text, session):
        self.prune()
        return session in self.pending_messages or message_intent(text) is not None

    async def call(self, item, op, cancel, **args):
        native.check(cancel)
        return await asyncio.to_thread(self.adapter, item.window, op, cancel, **args)

    async def cleanup(self, item, drafted, query):
        # Cleanup may outlive cancellation, but only clears our exact unchanged
        # draft in the same verified chat. It never focuses a window or sends keys.
        clear = True
        if item.window and drafted and item.verified_chat:
            try:
                result = await asyncio.to_thread(self.adapter, item.window, 'cleanup', threading.Event(),
                    chat=item.verified_chat, text=item.text)
                clear = result.get('cleared', False)
            except Exception: clear = False
        if item.window and query:
            try: await asyncio.to_thread(self.adapter, item.window, 'clear_search', threading.Event(), query=query)
            except Exception: pass
        return clear

    async def run(self, agent, text, session):
        self.prune()
        if self.cancelling(text, session):
            self.pending_messages.pop(session, None)
            yield dict(type='delta', text='Отменено. Сообщение не отправляла.'); return
        intent = message_intent(text)
        item = self.pending_messages.get(session)
        if intent:
            if intent.error:
                self.pending_messages.pop(session, None)
                yield dict(type='delta', text=intent.error); return
            item = PendingMessage(recipient=intent.recipient, text=intent.text)
            previous = self.context.get(session)
            if key(item.recipient) in PRONOUNS:
                item.recipient = previous.recipient if previous else ''
            if previous and key(item.recipient) == key(previous.recipient):
                item.username = previous.username
        elif item and item.status == 'awaiting_recipient':
            item.recipient = recipient_name(text)
            item.username = ''
        elif item and item.status == 'awaiting_text':
            # This is literal message content: never strip greetings or split
            # conjunctions/commands inside a dictated message.
            item.text = text.strip()
        else: return
        self.pending_messages[session] = item
        if not item.recipient:
            item.status = 'awaiting_recipient'
            yield dict(type='delta', text='Кому написать в Telegram? Назовите получателя.'); return
        if not item.text:
            item.status = 'awaiting_text'
            yield dict(type='delta', text='Что написать '+recipient_name(item.recipient, 'datv')+'?'); return
        if len(item.recipient) > 100 or len(item.text) > 4000 or '\x00' in item.text:
            self.pending_messages.pop(session, None)
            yield dict(type='delta', text='Имя получателя — до 100 символов, сообщение — до 4000.'); return
        trace('ROUTER', route='deterministic', intent='telegram_send_message')
        trace('TELEGRAM', message_length=len(item.text), status='requested')
        drafted = False; send_attempted = False; query = None; keep_pending = False; cleaned = False
        try:
            item.status = 'finding_chat'
            yield dict(type='agent_plan', steps=['Подготовить сообщение в Telegram', 'Подтвердить и отправить'])
            yield dict(type='agent_step', index=0, status='running')
            item.window = await asyncio.to_thread(self.launch, 'telegram', agent.cancel)
            agent.context[session] = item.window
            if key(item.recipient) in SELF and not item.username:
                result = await self.call(item, 'self', agent.cancel)
            else:
                query = item.username or item.recipient
                result = await self.call(item, 'search', agent.cancel, query=query)
                by_username = query.startswith('@')
                # Never collapse duplicate display names or provider IDs into a
                # supposedly unique recipient. Ambiguity must remain visible.
                matches = [c for c in result['candidates'] if by_username or recipient_matches(item.recipient, c['title'])]
                selected_result = None
                if by_username and len(matches) == 1:
                    opened = await self.call(item, 'open', agent.cancel, query=query, candidate=matches[0])
                    profile = await self.call(item, 'profile', agent.cancel, chat=opened['chat'])
                    if query.casefold() in profile['usernames']:
                        selected_result = opened; item.username = query.casefold()
                    else: matches = []
                if len(matches) != 1:
                    item.status = 'awaiting_recipient'; keep_pending = True
                    if not matches:
                        reply = 'Не нашла однозначно подходящий чат. Назовите полное имя или @username получателя. Текст сообщения сохранён до уточнения.'
                    else:
                        titles = list(dict.fromkeys(c['title'] for c in matches))[:6]
                        reply = 'Нашла несколько похожих чатов: '+', '.join(titles)+'. Уточните полное имя или @username получателя.'
                    yield dict(type='agent_step', index=0, status='stopped')
                    yield dict(type='delta', text=reply); return
                # Opening a chat clears Telegram's search. Reuse the already
                # verified chat instead of clicking a now-stale result again.
                result = selected_result or await self.call(item, 'open', agent.cancel, query=query, candidate=matches[0])
            item.verified_chat = result['chat']
            # Store only verified chat context, never an LLM-inferred recipient.
            item.recipient = item.verified_chat['title']
            self.context[session] = PendingMessage(recipient=item.recipient, verified_chat=item.verified_chat, window=item.window, username=item.username, status='verified')
            item.status = 'drafting'
            prepared = await self.call(item, 'prepare', agent.cancel, chat=item.verified_chat, text=item.text)
            drafted = True
            item.status = 'awaiting_confirmation'
            yield dict(type='agent_step', index=0, status='done')
            yield dict(type='agent_step', index=1, status='waiting')
            agent.pending = dict(nonce=secrets.token_urlsafe(24), decision=None, expires=time.monotonic()+120, kind='telegram_message')
            yield dict(type='approval', kind='telegram_message', nonce=agent.pending['nonce'],
                label='Отправить '+recipient_name(item.recipient, 'datv')+'?', window='Telegram · '+item.recipient+(' · '+item.username if item.username else ''),
                reason='Сообщение подготовлено. Отправлю только после подтверждения.', text=item.text)
            while agent.pending['decision'] is None and time.monotonic() < agent.pending['expires']:
                native.check(agent.cancel); await asyncio.sleep(.06)
            allowed = agent.pending['decision']; agent.pending = None
            yield dict(type='approval_closed')
            native.check(agent.cancel)
            if not allowed: raise native.Stopped('Отменено. Сообщение не отправляла.')
            item.confirmation_required = False
            item.status = 'sending'
            yield dict(type='agent_step', index=1, status='running')
            # Any failure from this point is uncertain: never auto-repeat Send.
            native.check(agent.cancel); send_attempted = True
            await self.call(item, 'send', agent.cancel, chat=item.verified_chat, text=item.text, confirmed=True)
            item.status = 'verifying'
            for _ in range(10):
                result = await self.call(item, 'verify', agent.cancel, chat=item.verified_chat,
                    text=item.text, baseline=prepared['baseline'])
                if result.get('verified'): break
                await asyncio.sleep(.35)
            else: raise CommandError('Сообщение пока не подтверждено историей Telegram.')
            item.status = 'sent'; drafted = False
            trace('TELEGRAM', status='success', message_length=len(item.text), verified=True)
            yield dict(type='agent_step', index=1, status='done')
            yield dict(type='delta', text='Отправила '+recipient_name(item.recipient, 'datv')+'.')
        except (Exception, asyncio.CancelledError) as exc:
            if isinstance(exc, asyncio.CancelledError):
                # A disconnected/aborted stream must stop the IPC worker before
                # cleanup; cancelling asyncio.to_thread alone cannot stop it.
                agent.stop()
            if send_attempted:
                item.status = 'uncertain'
                message = 'Отправка была запрошена, но её результат не подтверждён. Проверьте чат Telegram; повторно сообщение не отправляла.'
            else:
                item.status = 'cancelled' if isinstance(exc, (native.Stopped, asyncio.CancelledError)) else 'failed'
                message = 'Отменено. Сообщение не отправляла.' if item.status == 'cancelled' else str(exc) if isinstance(exc, CommandError) else 'Не удалось подготовить сообщение через интерфейс Telegram.'
            if isinstance(exc, asyncio.CancelledError): raise
            cleared = await self.cleanup(item, drafted and not send_attempted, query)
            cleaned = True
            if drafted and not send_attempted and not cleared:
                message += ' Черновик не удалось безопасно очистить — проверьте поле ввода Telegram.'
            elif item.status == 'failed' and not drafted:
                message += ' Отправка не выполнялась.'
            yield dict(type='agent_stopped', message=message)
            yield dict(type='delta', text=message)
        finally:
            agent.pending = None
            if not keep_pending: self.pending_messages.pop(session, None)
            # After Send, preserve uncertain state in Telegram for user review.
            if not cleaned:
                # Starlette cancels the entire response task group on browser
                # abort. Keep bounded draft cleanup outside that cancel scope.
                with anyio.CancelScope(shield=True):
                    cleared = await self.cleanup(item, drafted and not send_attempted, query)
            trace('TELEGRAM', status='success' if item.status == 'sent' else 'cancelled' if item.status == 'cancelled' else 'error', message_length=len(item.text or ''))
            if drafted and not send_attempted and not cleared:
                # The stream may already have been aborted; the UI remains the
                # source of truth, and an untouched draft is safer than erasing it.
                trace('TELEGRAM', status='error', draft_remaining=True)
