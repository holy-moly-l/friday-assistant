import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from command_language import CATALOG, resolve, calculate, number
import pytest

@pytest.mark.parametrize('entry',CATALOG,ids=lambda e:e['id'])
def test_all_documented_phrases_and_polite_forms(entry):
    expected=tuple(entry['action'])
    for phrase in entry['phrases']:
        for prefix in ['', 'Пятница, ', 'Пятница, пожалуйста, ', 'Не могла бы ты ', 'Будь добра, ']:
            actual=resolve(prefix+phrase)
            if expected[0]=='calculate':
                assert actual and actual[0]=='calculate',prefix+phrase
                assert calculate(actual[1])==calculate(expected[1]),prefix+phrase
            else:assert actual==expected,(prefix+phrase,actual,expected)
        assert resolve('Не '+phrase) is None,phrase
        assert resolve('Как выполнить команду '+phrase) is None,phrase

@pytest.mark.parametrize('phrase,expected',[
    ('Открой, пожалуйста, проводник.',('pc_app','explorer')),
    ('Пятница, можешь ли ты открыть мне программу Chrome?',('pc_app','chrome')),
    ('Установи громкость на пятидесяти процентах',('pc_volume',50)),
    ('Сделай громче на двадцать один процент',('pc_volume_delta',21)),
    ('Установи громкость на максимум',('pc_volume',100)),
    ('Громкость ноль процентов',('pc_volume',0)),
    ('Создай папку Мой Проект на рабочем столе',('pc_create_folder','Мой Проект')),
    ('Запиши заметку: Позвонить маме, мне нужен её Отчёт!',('note','Позвонить маме, мне нужен её Отчёт!')),
    ('Пятница, запомни: Не открывай браузер; Купи Чай.',('note','Не открывай браузер; Купи Чай.')),
    ('Найди файл Мой Отчёт.PDF',('pc_find_file','Мой Отчёт.PDF')),
    ('Погугли Книга «Мир»',('pc_web_search','Книга «Мир»')),
    ('Открой сайт https://example.com/Guide?Doc=AbC&Page=2',('pc_url','https://example.com/Guide?Doc=AbC&Page=2')),
])
def test_parameterized_commands(phrase,expected):assert resolve(phrase)==expected

@pytest.mark.parametrize('phrase',[
    'Не открывай браузер','Не надо открывать калькулятор','Расскажи, как открыть проводник',
    'Как мне открыть загрузки?','Открой проводник; shutdown /s','Открой calc.exe & whoami',
    'Открой браузер и удали документы','Запусти powershell','Открой C:\\Windows\\cmd.exe',
    'Запиши заметку:', 'Громкость пять десять', 'Если я скажу открой браузер, что будет?',
    'Не могла бы ты не открывать браузер',
])
def test_no_accidental_actions(phrase):assert resolve(phrase) is None

@pytest.mark.parametrize('expression,expected',[
    ('25 * 4','100'),('(25 + 5) / 2','15'),('двадцать пять умножить на четыре','100'),
    ('два плюс два','4'),('-3 + 8','5'),('12,5 / 2','6,25'),('100 минус семь','93'),
])
def test_arithmetic(expression,expected):assert calculate(expression)==expected

@pytest.mark.parametrize('expression',['__import__("os")','2 ** 1000','1/0','float("nan")','9'*100,'(1).real','[]'])
def test_arithmetic_rejects_code_and_unbounded_values(expression):
    with pytest.raises((ValueError,SyntaxError,ZeroDivisionError)):calculate(expression)

def test_russian_numbers_are_grammatical():
    assert number('двадцать пять')==25
    assert number('двадцати пяти')==25
    assert number('двадцать пятнадцать') is None
    assert number('сто один') is None
