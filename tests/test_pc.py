from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import pc
import pytest

@pytest.mark.parametrize('phrase,result',[
    ('Пятница, можешь открыть мне проводник, пожалуйста?',('pc_app','explorer')),
    ('Открой браузер',('pc_app','browser')),
    ('Открой настройки Windows',('pc_settings','ms-settings:')),
    ('Покажи папку загрузки',('pc_folder','Downloads')),
    ('Открой Google Chrome',('pc_app','chrome')),
    ('Открой YouTube',('pc_url','https://www.youtube.com')),
    ('Установи громкость на 50 процентов',('pc_volume',50)),
    ('Сделай тише',('pc_volume_delta',-10)),
    ('Выключи звук',('pc_mute',True)),
    ('Следующий трек',('pc_media','next')),
    ('Покажи рабочий стол',('pc_desktop',None)),
    ('Восстанови окна',('pc_restore',None)),
    ('Сделай снимок экрана',('pc_screenshot',None)),
    ('Найди файл отчёт',('pc_find_file','отчёт')),
    ('Найди в интернете погоду',('pc_web_search','погоду')),
    ('Создай папку на рабочем столе Проекты',('pc_create_folder','Проекты')),
])
def test_natural_commands(phrase,result):
    assert pc.resolve_pc_command(phrase)==result

def test_explorer_actual_location():
    path=pc.app_path('explorer')
    assert path==pc.windows_dir()/'explorer.exe'
    assert path.is_file()
    with patch.object(pc.subprocess,'Popen') as popen:
        pc.open_app('explorer')
        assert popen.call_args.args[0]==[str(path)]
        assert popen.call_args.kwargs['shell'] is False

def test_missing_application_is_actionable():
    with pytest.raises(pc.CommandError,match='Не нашла установленное'):
        pc.open_app('friday-unit-test-nonexistent-application')

def test_reject_shell_operators():
    for text in ['Открой calc.exe & del C:\\','Открой проводник; shutdown /s','Открой $(whoami)','Открой a|b']:
        assert pc.resolve_pc_command(text) is None

def test_no_action_for_questions_or_negation():
    for text in ['Как открыть проводник?', 'Не открывай браузер', 'Что такое калькулятор?', 'Расскажи, как сделать скриншот']:
        assert pc.resolve_pc_command(text) is None

def test_folder_creation_stays_on_desktop(tmp_path):
    with patch.object(pc,'desktop_path',return_value=tmp_path):
        text,_=pc.run_pc(('pc_create_folder','Проекты'),tmp_path)
        assert (tmp_path/'Проекты').is_dir()
        for name in ['../outside','C:\\outside','CON','AUX.txt','folder.']:
            with pytest.raises(pc.CommandError): pc.run_pc(('pc_create_folder',name),tmp_path)

def test_volume_bounds():
    with patch.object(pc,'get_volume') as get:
        get.return_value.GetMasterVolumeLevelScalar.return_value=.5
        with pytest.raises(pc.CommandError):pc.adjust_volume('pc_volume',101)
        get.return_value.SetMasterVolumeLevelScalar.assert_not_called()

def test_settings_only_open_catalogued_pages():
    with patch.object(pc.os,'startfile') as launch:
        pc.run_pc(('pc_settings','ms-settings:display'),Path('.'))
        launch.assert_called_once_with('ms-settings:display')
        with pytest.raises(pc.CommandError):pc.run_pc(('pc_settings','file:///C:/Windows/cmd.exe'),Path('.'))
        assert launch.call_count==1

def test_relative_volume_has_a_bounded_step():
    for delta in [0,101,-101]:
        with pytest.raises(pc.CommandError):pc.adjust_volume('pc_volume_delta',delta)

def test_every_catalog_command_has_an_action():
    import json
    import app
    catalog=json.loads((Path(__file__).parents[1]/'shared/commands.json').read_text(encoding='utf-8'))
    assert len(catalog)>=90
    for entry in catalog:assert app.resolve_command(entry['prompt']) is not None,entry['prompt']
