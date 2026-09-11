"""Russian command grammar. The UI and recognizer share one catalogue.

Only explicit, complete commands resolve. Payloads keep their original spelling;
there is no fuzzy matching of arbitrary programs, files or user text.
"""
import json
from pathlib import Path
import re

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'shared/commands.json').read_text(encoding='utf8'))
PREFIX=re.compile(r'^(?:(?:эй|привет)[,\s]+|пятниц[ауы][,\s]+|пожалуйста[,\s]+|будь (?:добра|так добра|любезна)[,\s]+|(?:ты )?(?:можешь|можете|могла бы|не могла бы)(?: ли)?(?: ты)?[,\s]+|прошу(?: тебя)?[,\s]+|давай[,\s]+)',re.I)

def request_text(text):
    text=text.strip()
    for _ in range(12):
        updated=PREFIX.sub('',text,count=1)
        if updated==text:break
        text=updated.strip()
    text=re.sub(r'^(\w+),?\s+пожалуйста[,\s]+',r'\1 ',text,flags=re.I)
    return text

def normalize(text):
    text=request_text(text).casefold().replace('ё','е')
    text=re.sub(r'[,!?]+',' ',text)
    text=re.sub(r'\s+пожалуйста[\s.!]*$','',text)
    # Polite pronouns belong to the command prefix, never arbitrary payloads.
    text=re.sub(r'^(открой|открыть|запусти|запустить|покажи|показать|скажи|подскажи)\s+(?:мне|для меня)\s+',r'\1 ',text)
    return re.sub(r'\s+',' ',text).strip(' .')

PHRASES={}
TARGETS={}
for entry in CATALOG:
    action=tuple(entry['action'])
    if not entry.get('template'):
        for phrase in entry['phrases']:
            key=normalize(phrase)
            if key in PHRASES and PHRASES[key]!=action:raise ValueError('Ambiguous command: '+phrase)
            PHRASES[key]=action
    for target in entry.get('targets',[]):TARGETS[normalize(target)]=action

UNITS={'ноль':0,'нуль':0,'один':1,'одна':1,'два':2,'две':2,'три':3,'четыре':4,'пять':5,'шесть':6,'семь':7,'восемь':8,'девять':9}
TEENS={'десять':10,'одиннадцать':11,'двенадцать':12,'тринадцать':13,'четырнадцать':14,'пятнадцать':15,'шестнадцать':16,'семнадцать':17,'восемнадцать':18,'девятнадцать':19}
TENS={'двадцать':20,'тридцать':30,'сорок':40,'пятьдесят':50,'шестьдесят':60,'семьдесят':70,'восемьдесят':80,'девяносто':90,'сто':100}
CASES=dict(zip('одного одной двух трех четырех пяти шести семи восьми девяти десяти двадцати тридцати сорока пятидесяти шестидесяти семидесяти восьмидесяти девяноста ста'.split(),
               'один один два три четыре пять шесть семь восемь девять десять двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто'.split()))
def number(text):
    text=text.strip().lower().replace('ё','е')
    if re.fullmatch(r'\d{1,6}',text):return int(text)
    words=[CASES.get(w,w) for w in text.split()]
    if len(words)==1:return {**UNITS,**TEENS,**TENS}.get(words[0])
    if len(words)==2 and words[0] in TENS and 20<=TENS[words[0]]<=90 and words[1] in UNITS and UNITS[words[1]]>0:
        return TENS[words[0]]+UNITS[words[1]]
    return None

OPEN=r'(?:открой|открыть|откроешь|открывай|запусти|запустить|запустишь|запускай|покажи|показать)'
def resolve(text):
    raw=request_text(text)
    n=normalize(raw)
    if not n or len(n)>8000:return None
    # Negations and explanations are never converted into actions.
    if re.match(r'^(?:не\b|не надо\b|не нужно\b|как\s+(?:мне\s+)?(?:открыть|запустить|сделать|создать)|расскажи\s+как|объясни\b|если\b)',n):return None

    # Free text is captured BEFORE normalization: case, ё and punctuation matter.
    match=re.fullmatch(r'(?:запиши|записать|сохрани|сохранить|создай|создать|добавь|добавить)(?:\s+мне)?\s+(?:новую\s+)?(?:заметку|в заметки)\s*[:—,-]?\s*(.+)|запомни\s*[:—,-]?\s*(.+)',raw,re.I|re.S)
    if match:
        content=(match[1] or match[2]).strip()
        return ('note',content) if content.strip(':—,- ') else None

    # A complete web address can contain & in its query; it is never a shell command.
    m=re.fullmatch(r'(?:'+OPEN+r'|перейди на|зайди на)(?:\s+сайт)?\s+(https?://[^\s]+)',raw,re.I)
    if m:
        from urllib.parse import urlsplit
        try:
            url=m[1];parts=urlsplit(url)
            if parts.hostname and not parts.username and not re.search(r'[<>`\x00-\x20]',url):return ('pc_url',url)
        except ValueError:pass
        return None

    # Reject composite commands instead of silently executing just a prefix.
    if re.search(r'[;&|`$<>]|\s+(?:и|а затем|потом|затем)\s+(?:открой|запусти|выключи|удали|перезагрузи|сделай|создай)\b',n):return None
    if n in PHRASES:return PHRASES[n]

    volume=n.removesuffix(' пожалуйста')
    up=r'(?:прибавь|прибавить|увеличь|увеличить|добавь|повысь) (?:громкость|громкости|звук)|(?:сделай )?громче'
    down=r'(?:убавь|убавить|уменьши|уменьшить|понизь|снизь) (?:громкость|громкости|звук)|(?:сделай )?тише'
    for pattern,sign in [(up,1),(down,-1)]:
        m=re.fullmatch(r'(?:'+pattern+r') на (.+?)(?:\s*(?:%|процент|процента|процентов|процентах))?',volume)
        if m:
            amount=number(m[1])
            return ('pc_volume_delta',sign*amount) if amount is not None else None
    m=re.fullmatch(r'(?:(?:поставь|установи|установить|сделай|выстави|измени|изменить) )?(?:громкость|звук)(?: (?:на|до))? (.+?)(?:\s*(?:%|процент|процента|процентов|процентах))?',volume)
    if m:
        amount=number(m[1])
        if m[1] in ('максимум','максимальную','полную'):amount=100
        if m[1] in ('минимум','минимальную'):amount=0
        return ('pc_volume',amount) if amount is not None else None

    raw=raw.strip()
    m=re.fullmatch(r'(?:найди|найти|поищи|отыщи)(?:\s+мне)?\s+(?:файл|файлы)(?:\s+(?:с названием|под названием|по имени|по названию|с именем))?\s+(.+)|поиск\s+(?:файла|файлов)\s*:\s*(.+)',raw,re.I)
    if m:return ('pc_find_file',(m[1] or m[2]).strip(' «»"'))
    m=re.fullmatch(r'(?:найди|найти|поищи)(?:\s+мне)?\s+(?:в интернете|в браузере|в гугле|в сети)\s+(.+)|(?:погугли|загугли)\s+(.+)|(?:найди|поищи)\s+(.+?)\s+в интернете[.!?]*|поиск в интернете\s*:\s*(.+)',raw,re.I)
    if m:return ('pc_web_search',next(g for g in m.groups() if g).strip())
    m=re.fullmatch(r'(?:создай|создать|сделай|сделать)(?:\s+мне)?\s+(?:новую\s+)?папку(?:\s+на рабочем столе)?(?:\s+(?:с названием|под названием|с именем))?\s+(.+)',raw,re.I)
    if m:
        name=re.sub(r'\s+на рабочем столе[.!?]*$','',m[1],flags=re.I).strip(' «»"')
        return ('pc_create_folder',name)
    m=re.fullmatch(r'(?:посчитай|вычисли|рассчитай|сколько будет)\s+(.+?)[?!.]*',raw,re.I)
    if m:return ('calculate',m[1])

    m=re.fullmatch(r'(?:'+OPEN+r'|перейди (?:в|на|к)|зайди (?:в|на))(?:\s+(?:мне|для меня))?\s+(?:(?:приложение|программу|сайт)\s+)?(.+)',raw,re.I)
    if m:
        target=m[1].strip(' «»"!?')
        key=normalize(target)
        if key in TARGETS:return TARGETS[key]
        if re.fullmatch(r'(?:https?://)?[a-z0-9а-я][a-z0-9а-я.-]+\.[a-zа-я]{2,}(?:[/?#][^\s]*)?',target,re.I):
            return ('pc_url',target if re.match(r'https?://',target,re.I) else 'https://'+target)
        if re.search(r'[/\\:]|\.exe\b|\.bat\b|\.cmd\b|\.ps1\b',key) or key in ('powershell','cmd','pwsh','командную строку'):return None
        # Unknown names are resolved only against installed Start Menu entries.
        if len(key)>100:return None
        return ('pc_app',key)
    return None

def calculate(expression):
    """A small bounded arithmetic evaluator, with no eval(), calls or attributes."""
    import ast
    import math
    import operator
    expression=expression.lower().replace('ё','е').replace('×','*').replace('÷','/').replace('−','-').replace(',','.')
    for source,target in [('умножить на','*'),('разделить на','/'),('делить на','/'),('плюс','+'),('минус','-')]:expression=expression.replace(source,target)
    def replace_words(m):
        value=number(m[0].strip())
        if value is None:raise ValueError('Используйте числа и знаки +, −, ×, ÷.')
        return str(value)
    expression=re.sub(r'[а-я]+(?:\s+[а-я]+)*',replace_words,expression)
    if len(expression)>200 or re.search(r'[^\d\s.()+*/-]',expression):raise ValueError('Используйте числа и знаки +, −, ×, ÷.')
    tree=ast.parse(expression.strip(),mode='eval')
    if sum(1 for _ in ast.walk(tree))>60:raise ValueError('Выражение слишком длинное.')
    ops={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):value=node.value
        elif isinstance(node,ast.BinOp) and type(node.op) in ops:value=ops[type(node.op)](visit(node.left),visit(node.right))
        elif isinstance(node,ast.UnaryOp) and type(node.op) in (ast.UAdd,ast.USub):value=visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        else:raise ValueError('Поддерживаются только сложение, вычитание, умножение и деление.')
        if not math.isfinite(value) or abs(value)>1e15:raise ValueError('Слишком большое число: предел — 10¹⁵.')
        return value
    value=visit(tree.body)
    return f'{value:.12g}'.replace('.',',')
