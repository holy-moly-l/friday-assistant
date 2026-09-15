"""One display-number grammar for actions and observations."""
import re
from command_language import normalize
from pc import CommandError


def display_number(text):
    text=normalize(text)
    ordinal=r'(?:(?:перв|втор|четверт|пят|шест|седьм|восьм|девят|десят)(?:ый|ой|ая|ое|ые|ого|ому|ым|ом|ую|ых|ыми)|трет(?:ий|ья|ье|ьи|ьего|ьему|ьим|ьем|ью|ьей|ьих|ьими)|\d+(?:-?(?:й|ый|ой|ий|ом|му))?)'
    noun=r'(?:монитор\w*|экран\w*|диспле\w*)'
    matches=re.findall(r'\b('+ordinal+r')\s+'+noun+r'\b|\b'+noun+r'\s*(?:номер\s*|№\s*)?('+ordinal+r')\b',text)
    numbers=[]
    roots=('перв','втор','трет','четверт','пят','шест','седьм','восьм','девят','десят')
    for before,after in matches:
        word=before or after;digits=re.match(r'\d+',word)
        number=int(digits[0]) if digits else next(i+1 for i,root in enumerate(roots) if word.startswith(root))
        if number<1:raise CommandError('Номер дисплея должен быть больше нуля.')
        numbers.append(number)
    if len(set(numbers))>1:raise CommandError('Укажите один целевой дисплей для этого действия.')
    return numbers[0] if numbers else None
