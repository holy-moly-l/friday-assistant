"""Telegram Desktop adapter. Text and chat contents stay in memory, never in logs.

UIA Value/Invoke patterns have priority. The only global shortcut is Telegram's
documented Ctrl+0 for Saved Messages, guarded by foreground and process identity.
No coordinate clicks, clipboard, Bot API, or macro interpretation of user text.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import re
import sys
import threading
import time
from _ctypes import COMError
import uiautomation as auto
import desktop_native as native
from lifecycle import follow_parent
from telegram_language import key
from pc import CommandError

auto.SetGlobalSearchTimeout(.3)


def identity(control):
    return hashlib.sha256(str(list(control.GetRuntimeId())).encode()).hexdigest()[:24]


def value(control):
    pattern = control.GetPattern(auto.PatternId.ValuePattern)
    return pattern.Value if pattern else None


def cells(row, wanted):
    result = {}
    for child in row.GetChildren():
        if child.ControlTypeName == 'DataItemControl' and child.Name in wanted:
            result[child.Name] = value(child)
    return result


def chat_title(title):
    # Telegram puts its numeric title prefix BEFORE its bidi marker; a contact
    # whose actual name begins '(2)' remains intact after the marker.
    title = re.sub(r'^\(\d+\)\s*(?=[\u200e\u200f])', '', title)
    title = re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', title)
    title = re.sub(r'\s+[–—-]\s+(?:Telegram(?:\s*\(\d+\))?|\(\d+\))$', '', title).strip()
    return title


class TelegramUI:
    def __init__(self, window, check=lambda: None):
        self.window = window
        self.check = check
        self.guard()
        self.root = auto.ControlFromHandle(window['hwnd'])

    def guard(self):
        self.check()
        fresh = native.same(self.window)
        if fresh['process'].casefold() != 'telegram.exe':
            raise ValueError('Нужен Telegram Desktop, а не другое приложение.')
        return fresh

    def controls(self):
        # Lists contain thousands of message cells. Discover containers first;
        # enumerate only the relevant list separately, with an explicit bound.
        result = []; stack = [(self.root, 0)]; end = time.monotonic() + 5
        while stack:
            self.check()
            control, depth = stack.pop()
            if time.monotonic() > end or len(result) > 600:
                raise ValueError('Интерфейс Telegram слишком большой для надёжного чтения.')
            try:
                if control.IsOffscreen: continue
                result.append(control)
                if depth < 16 and control.ControlTypeName not in ('ListControl', 'ListItemControl'):
                    stack.extend((child, depth + 1) for child in reversed(control.GetChildren()))
            except COMError:
                # Animated panes can remove a provider during traversal.
                continue
        return result

    def one(self, predicate, label):
        found = []
        for control in self.controls():
            try:
                if predicate(control): found.append(control)
            except COMError: continue
        if len(found) != 1: raise ValueError('Не удалось однозначно найти ' + label + ' через UI Automation Telegram.')
        return found[0]

    def search_field(self):
        return self.one(lambda c: c.ControlTypeName == 'EditControl'
            and c.ClassName == 'class Ui::InputField::Inner'
            and 'Dialogs::Widget' in c.AutomationId, 'общий поиск')

    def composer(self):
        return self.one(lambda c: c.ControlTypeName == 'EditControl'
            and c.ClassName == 'class Ui::InputField::Inner'
            and key(c.Name) in ('сообщение', 'сообщение…', 'message', 'message…')
            and 'HistoryWidget' in c.AutomationId, 'поле сообщения')

    def history(self):
        return self.one(lambda c: c.ControlTypeName == 'ListControl'
            and c.ClassName == 'class HistoryInner', 'историю сообщений')

    def chat_list(self):
        return self.one(lambda c: c.ControlTypeName == 'ListControl'
            and c.ClassName == 'class Dialogs::InnerWidget'
            and 'Dialogs::Widget' in c.AutomationId, 'список чатов')

    def set_value(self, control, text):
        self.guard()
        pattern = control.GetPattern(auto.PatternId.ValuePattern)
        if control.IsPassword or not control.IsEnabled or not pattern or pattern.IsReadOnly:
            raise ValueError('Поле Telegram не поддерживает безопасный ввод текста.')
        pattern.SetValue(text, waitTime=0)
        time.sleep(.15)
        if pattern.Value != text: raise ValueError('Telegram не подтвердил введённый текст.')

    def invoke(self, control):
        self.guard()
        if not control.IsEnabled: raise ValueError('Элемент Telegram сейчас отключён.')
        pattern = control.GetPattern(auto.PatternId.InvokePattern)
        if pattern: pattern.Invoke(waitTime=0); return
        # Accessibility fallback, still addressing the exact control, no pixels.
        pattern = control.GetPattern(auto.PatternId.LegacyIAccessiblePattern)
        if pattern and pattern.DefaultAction:
            self.guard(); pattern.DoDefaultAction(waitTime=0); return
        raise ValueError('Элемент Telegram не поддерживает нажатие через accessibility.')

    def wait_title(self, title):
        for _ in range(30):
            if key(chat_title(self.guard()['title'])) == key(title): return
            time.sleep(.1)
        raise ValueError('Заголовок чата не совпал с получателем.')

    def profile(self, expected):
        self.state(expected)
        def profiles():
            return [c for c in self.controls() if c.ClassName == 'class Info::Profile::Widget']
        def toggle():
            button = self.one(lambda c: c.ControlTypeName == 'ButtonControl'
                and key(c.Name) in ('информация','info') and 'HistoryView::TopBarWidget' in c.AutomationId, 'информацию о чате')
            self.invoke(button)
        # Always reopen from the bound current chat, not a possibly stale sidebar.
        if profiles():
            toggle()
            for _ in range(25):
                if not profiles(): break
                self.check(); time.sleep(.1)
            else: raise ValueError('Не удалось обновить профиль получателя.')
        toggle()
        for _ in range(25):
            found = profiles()
            if len(found) == 1: break
            self.check(); time.sleep(.1)
        else: raise ValueError('Telegram не открыл профиль получателя.')
        time.sleep(.25)
        try:
            names = set(); labels = []; count = 0; end = time.monotonic()+5
            for control, depth in auto.WalkControl(found[0], maxDepth=24):
                self.check(); count += 1
                if count > 500 or time.monotonic() > end: raise ValueError('Профиль Telegram недоступен для проверки.')
                if control.IsOffscreen: continue
                if control.ClassName == 'class Ui::MarqueeLabel': names.add(key(control.Name))
                if control.ControlTypeName == 'TextControl' and key(control.Name) in ('имя пользователя','username'):
                    labels.append(control)
            if key(expected['title']) not in names or len(labels) != 1:
                raise ValueError('Не удалось проверить имя пользователя в профиле Telegram.')
            usernames = []
            for sibling in labels[0].GetParentControl().GetChildren():
                if sibling.ControlTypeName == 'TextControl' and re.fullmatch(r'@[a-zA-Z0-9_]{5,32}', sibling.Name.strip()):
                    usernames.append(sibling.Name.strip().casefold())
            self.state(expected)
            return usernames
        finally:
            toggle()
            for _ in range(25):
                if not profiles(): break
                self.check(); time.sleep(.1)

    def candidates(self):
        lists = [c for c in self.controls() if c.ControlTypeName == 'ListControl'
            and c.ClassName == 'class Dialogs::InnerWidget' and 'Dialogs::Widget' in c.AutomationId]
        if not lists: return []
        if len(lists) != 1: raise ValueError('Список результатов Telegram неоднозначен.')
        rows = lists[0].GetChildren()
        if len(rows) > 500: raise ValueError('Слишком много результатов. Укажите полное имя получателя.')
        result = []
        for row in rows:
            self.check()
            data = cells(row, {'Название', 'Name', 'Тип', 'Type'})
            title = data.get('Название', data.get('Name'))
            kind = key(data.get('Тип', data.get('Type')) or '')
            # Message-search and global peer hits without identity cells are not
            # chat identity evidence. Archive/folders are not recipients either.
            if not title or kind in ('архив', 'archive', 'папка', 'folder'): continue
            result.append(dict(id=identity(row), title=title, kind=kind))
        return result

    def state(self, expected=None):
        for attempt in range(4):
            try: return self.read_state(expected)
            except COMError:
                if attempt == 3: raise
                self.check(); time.sleep(.15)

    def read_state(self, expected=None):
        fresh = self.guard()
        title = chat_title(fresh['title'])
        if not title or key(title).startswith('telegram'):
            raise ValueError('Telegram не показывает заголовок открытого чата.')
        if expected and key(title) != key(expected['title']):
            raise ValueError('Открыт другой чат. Отправка отменена.')
        composer = self.composer(); history = self.history()
        stamp = dict(title=title, composer=identity(composer), history=identity(history))
        if expected and any(stamp[k] != expected[k] for k in ('composer', 'history')):
            raise ValueError('Чат или поле ввода изменились. Отправка отменена.')
        return stamp, composer, history

    def matching(self, history, text, saved=False):
        rows = history.GetChildren()
        # Only current loaded history; never scroll/read all personal messages.
        if len(rows) > 500: raise ValueError('История Telegram слишком велика для проверки отправки.')
        result = []
        for row in rows:
            self.check()
            data = cells(row, {'Сообщение', 'Message', 'Получение', 'Delivery', 'Переслать', 'Forwarded'})
            if data.get('Сообщение', data.get('Message')) == text:
                receipt = key(data.get('Получение', data.get('Delivery')) or '')
                sent = receipt in ('отправлено', 'sent')
                # Telegram marks messages to one's own Saved Messages as
                # received, not outgoing. Accept that only in the verified self
                # chat and never for a forwarded message or another recipient.
                if saved and not data.get('Переслать', data.get('Forwarded')):
                    sent = sent or receipt in ('получено', 'received')
                result.append(dict(id=identity(row), sent=sent))
        return result

    def run(self, op, data):
        if op == 'search':
            field = self.search_field()
            current = value(field)
            if current and current != data['query']:
                raise ValueError('В поиске Telegram уже введён текст. Очистите поиск и повторите команду.')
            self.set_value(field, data['query'])
            # Wait for two stable result samples after Telegram's search debounce.
            time.sleep(1.1)
            previous = None
            for _ in range(8):
                self.guard()
                if value(self.search_field()) != data['query']:
                    raise ValueError('Поиск изменился во время выбора получателя.')
                found = self.candidates()
                if found == previous: return dict(candidates=found, query=data['query'])
                previous = found; time.sleep(.35)
            raise ValueError('Результаты поиска ещё меняются. Повторите команду.')
        if op == 'clear_search':
            field = self.search_field()
            if value(field) == data['query']: self.set_value(field, '')
            if not value(field):
                # Emptying the edit alone leaves Telegram in search mode. Its
                # accessible Cancel Search button restores the chat list without
                # global Escape/focus, even when Windows denies foreground.
                buttons = [c for c in self.controls() if c.ControlTypeName == 'ButtonControl'
                    and 'Dialogs::Widget' in c.AutomationId and key(c.Name) in ('отменить поиск','cancel search')]
                if len(buttons) == 1: self.invoke(buttons[0]); time.sleep(.2)
            return dict(cleared=True)
        if op == 'open':
            candidate = data['candidate']
            if value(self.search_field()) != data['query']:
                raise ValueError('Поисковый запрос Telegram изменился.')
            matches = [r for r in self.chat_list().GetChildren() if identity(r) == candidate['id']]
            if len(matches) != 1: raise ValueError('Выбранный результат поиска исчез.')
            title = cells(matches[0], {'Название', 'Name'})
            if title.get('Название', title.get('Name')) != candidate['title']:
                raise ValueError('Получатель в результате поиска изменился.')
            self.invoke(matches[0]); self.wait_title(candidate['title']); time.sleep(.15)
            stamp, _, _ = self.state()
            if key(stamp['title']) != key(candidate['title']): raise ValueError('Заголовок чата не совпал с получателем.')
            return dict(chat=stamp)
        if op == 'self':
            saved = []
            try:
                for row in self.chat_list().GetChildren():
                    data_row = cells(row, {'Тип','Type'})
                    if key(data_row.get('Тип',data_row.get('Type')) or '') in ('избранное','saved messages'):
                        saved.append(row)
            except (ValueError,COMError): pass
            if len(saved) == 1:
                # The semantic Type cell proves this is the account's self chat;
                # its Name cell may contain the account name, not 'Избранное'.
                self.invoke(saved[0])
            else:
                native.focus(self.window, threading.Event())
                self.guard()
                if native.u.GetForegroundWindow() != self.window['hwnd']: raise ValueError('Не удалось выбрать Telegram для горячей клавиши.')
                auto.SendKeys('{Ctrl}0', waitTime=0)
            for _ in range(30):
                if key(chat_title(self.guard()['title'])) in ('избранное', 'saved messages'): break
                time.sleep(.1)
            time.sleep(.4)
            stamp, _, _ = self.state()
            if key(stamp['title']) not in ('избранное', 'saved messages'):
                raise ValueError('Telegram не подтвердил открытие «Избранного».')
            stamp['self_chat'] = True
            return dict(chat=stamp)
        if op == 'inspect':
            stamp, composer, history = self.state()
            return dict(chat=stamp, draft_length=len(value(composer) or ''), history_count=len(history.GetChildren()))
        if op == 'profile':
            return dict(usernames=self.profile(data['chat']))
        if op == 'prepare':
            stamp, composer, history = self.state(data['chat'])
            if value(composer): raise ValueError('В этом чате уже есть черновик. Не буду его перезаписывать; очистите поле и повторите команду.')
            baseline = self.matching(history, data['text'])
            self.set_value(composer, data['text'])
            return dict(chat=stamp, baseline=[r['id'] for r in baseline], drafted=True)
        if op == 'cleanup':
            _, composer, _ = self.state(data['chat'])
            if value(composer) == data['text']:
                self.set_value(composer, ''); return dict(cleared=True)
            return dict(cleared=not bool(value(composer)))
        if op == 'send':
            if data.get('confirmed') is not True: raise ValueError('Отправка требует подтверждения.')
            _, composer, history = self.state(data['chat'])
            if value(composer) != data['text']: raise ValueError('Черновик изменился. Нужно новое подтверждение.')
            send = self.one(lambda c: c.ControlTypeName == 'ButtonControl'
                and key(c.Name) in ('отправить', 'send', 'send message', 'отправить сообщение')
                and 'HistoryWidget' in c.AutomationId, 'кнопку отправки')
            # Recheck immediately before the single irreversible UIA invocation.
            self.state(data['chat'])
            if value(composer) != data['text']: raise ValueError('Черновик изменился. Отправка отменена.')
            self.guard(); self.invoke(send)
            return dict(requested=True)
        if op == 'verify':
            _, composer, history = self.state(data['chat'])
            saved = data['chat'].get('self_chat') is True
            matches = self.matching(history, data['text'], saved=saved)
            verified = not value(composer) and any(r['sent'] and r['id'] not in data['baseline'] for r in matches)
            return dict(verified=bool(verified))
        raise ValueError('Неизвестное действие Telegram.')


def main(data):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    event = kernel.OpenEventW(0x100000, False, data['cancel_event'])
    if not event: raise ValueError('Сигнал остановки Telegram недоступен.')
    def check():
        if kernel.WaitForSingleObject(event, 0) == 0: raise ValueError('Остановлено.')
    try: return TelegramUI(data['window'], check).run(data['op'], data)
    finally: kernel.CloseHandle(event)


if __name__ == '__main__':
    follow_parent(os.environ.get('FRIDAY_UIA_PARENT_PID'))
    try: result = main(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except (ValueError,CommandError) as exc: result = dict(error=str(exc))
    except Exception: result = dict(error='Telegram не предоставил надёжные данные UI Automation. Отправку не повторяю.')
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
