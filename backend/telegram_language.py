"""Deterministic Russian messaging grammar. Message bodies are never normalized."""
from dataclasses import dataclass
from functools import lru_cache
import re
from command_language import request_text

APP=r'(?:telegram|телеграм(?:е|м|ме)?|телег[аеу])'
PRONOUNS={'ей','ему','им','туда','ей же','ему же'}
SELF={'избранное','избранному','избранном','saved messages','себе','мне'}
CANCEL={'отмена','отмени','нет','не надо','не нужно','не отправляй','не отправляй сообщение'}
VERBATIM=r'(?:дословно|слово\s+в\s+слово|именно\s+так|как\s+есть)'


def message_body(text,*,follow_up=False):
    """Strip command delimiters only; never normalize a verbatim payload."""
    body=text.strip() if follow_up else re.sub(r'^\s*,?\s*(?:сообщение\b\s*:?\s*)?', '', text, count=1, flags=re.I)
    literal=re.match(r'^'+VERBATIM+r'\b\s*:?\s*',body,re.I)
    if literal:return body[literal.end():].strip(),True
    if follow_up:return body,False
    return re.sub(r'^что\s+','',body,flags=re.I).strip(),False


def key(text):
    text=re.sub('[\u200e\u200f\u202a-\u202e\u2066-\u2069]','',text)
    return re.sub(r'\s+',' ',text.casefold().replace('ё','е')).strip(' .!?«»"')


@lru_cache(maxsize=1)
def morph():
    import pymorphy3
    return pymorphy3.MorphAnalyzer()


def person_parse(word):
    return next((p for p in morph().parse(word) if p.tag.grammemes & {'Name','Surn','Patr'}),None)


def recipient_name(text,case='nomn'):
    text=text.strip(' «»"')
    if key(text) in SELF:return 'Избранное'
    if text.startswith('@') or key(text) in PRONOUNS:return text
    def inflect(match):
        word=match[0];parsed=person_parse(word)
        if not parsed:return word
        form=parsed.inflect({case})
        return form.word.capitalize() if form else word
    return re.sub(r'[А-Яа-яЁё]+',inflect,text)


def recipient_matches(requested,title):
    wanted=key(recipient_name(requested));actual=key(recipient_name(title))
    if wanted in {key(x) for x in SELF}:return actual in SELF
    # Whole name/token prefix only. Never edit distance or a match in a message preview.
    return actual==wanted or (not wanted.startswith('@') and actual.startswith(wanted+' '))


@dataclass(frozen=True)
class MessageIntent:
    recipient:str=''
    text:str|None=None
    error:str=''
    verbatim:bool=False
    mode:str='statement'


def message_intent(text):
    raw=request_text(text)
    match=re.match(r'^(?:(?:в|через)\s+'+APP+r'\s+)?(напиши|отправь|ответь|скинь|скажи|передай|спроси)\b\s*(.*)$',raw,re.I|re.S)
    if not match:return None
    verb,body=match.groups();explicit=bool(re.match(r'^(?:в|через)\s+',raw,re.I))
    app=re.match(r'^(?:в|через)\s+'+APP+r'\b\s*',body,re.I)
    if app:body=body[app.end():];explicit=True
    body=re.sub(r'^в\s+(избранное)\b',r'\1',body,flags=re.I)
    before=re.match(r'^сообщение\s+',body,re.I)
    if before:body=body[before.end():];explicit=True
    # Recipient omitted: only a verified per-conversation chat may supply it.
    if re.match(r'^(?:'+VERBATIM+r'\b|что\s|чтобы\s)',body,re.I):
        payload,literal=message_body(body)
        return MessageIntent('ей',payload or None,verbatim=literal,mode='question' if verb.lower()=='спроси' else 'statement')
    if not body:return MessageIntent() if explicit or verb.lower()!='напиши' else None
    # A quoted display name or the text before ':' / ', что' may contain spaces.
    match=re.match(r'^[«"]([^»"]+)[»"]\s*[:,]?\s*(.*)$',body,re.S)
    if match:recipient,payload=match.groups()
    else:
        match=re.match(r'^(.{1,100}?)(?:\s*:\s*|,\s*|\s+(?=что\s+))(.+)$',body,re.I|re.S)
        candidate=match[1].strip() if match else ''
        # A colon inside the message is not a recipient delimiter.
        is_name=key(candidate) in SELF|PRONOUNS or candidate.startswith('@') or bool(candidate and all(person_parse(w) for w in candidate.split()))
        if match and is_name:recipient,payload=match.groups()
        else:
            recipient,_,payload=body.partition(' ')
    recipient=recipient.strip(' ,:«»"')
    app=re.search(r'\s+(?:в|через)\s+'+APP+r'$',recipient,re.I)
    if app:recipient=recipient[:app.start()];explicit=True
    if not explicit and verb.lower() in {'напиши','скажи','передай','спроси'}:
        first=recipient.split()[0] if recipient else ''
        if key(recipient) not in SELF|PRONOUNS and not first.startswith('@') and not person_parse(first):return None
    if key(recipient) in {'файл','фото','картинку','документ','голосовое'}:
        return MessageIntent(error='Пока могу подготовить только текстовое сообщение в Telegram.')
    if not recipient or len(recipient)>100 or any(c in recipient for c in '\n\r\x00'):
        return MessageIntent(error='Назовите получателя или его @username.')
    payload,literal=message_body(payload)
    if len(payload)>4000:return MessageIntent(error='Сообщение слишком длинное: максимум 4000 символов.')
    return MessageIntent(recipient_name(recipient),payload or None,verbatim=literal,mode='question' if verb.lower()=='спроси' else 'statement')
