"""One-shot UIA worker: a broken application provider cannot hang the assistant."""
import hashlib
import json
import os
import sys
import time
from lifecycle import follow_parent
follow_parent(os.environ.get('FRIDAY_UIA_PARENT_PID'))
import uiautomation as auto

auto.SetGlobalSearchTimeout(.5)

def inspect(hwnd):
    root=auto.ControlFromHandle(hwnd)
    if not root:raise ValueError('Окно недоступно для UI Automation.')
    rows=[];controls={};end=time.monotonic()+2
    for control,depth in auto.WalkControl(root,includeTop=True,maxDepth=7):
        if len(rows)>=180 or time.monotonic()>end:break
        try:
            if control.IsOffscreen or control.IsPassword:continue
            key=hashlib.sha256(str(list(control.GetRuntimeId())).encode()).hexdigest()[:16]
            row=dict(id=key,name=control.Name[:240],type=control.ControlTypeName,
                     enabled=control.IsEnabled,focused=control.HasKeyboardFocus)
            if row['type'] in ('ButtonControl','MenuItemControl','HyperlinkControl','CheckBoxControl','RadioButtonControl','TabItemControl','ListItemControl','ComboBoxControl'):
                row['clickable']=any(control.GetPattern(pattern) is not None for pattern in
                    (auto.PatternId.InvokePattern,auto.PatternId.SelectionItemPattern,auto.PatternId.TogglePattern,auto.PatternId.ExpandCollapsePattern))
            expand=control.GetPattern(auto.PatternId.ExpandCollapsePattern)
            if expand:row['expanded']=expand.ExpandCollapseState
            value=control.GetPattern(auto.PatternId.ValuePattern)
            if value:row['value']=value.Value[:1000]
            toggle=control.GetPattern(auto.PatternId.TogglePattern)
            if toggle:row['toggle']=toggle.ToggleState
            selection=control.GetPattern(auto.PatternId.SelectionItemPattern)
            if selection:row['selected']=selection.IsSelected
            scroll=control.GetPattern(auto.PatternId.ScrollPattern)
            if scroll:row['scroll']=[scroll.HorizontalScrollPercent,scroll.VerticalScrollPercent]
            rows.append(row);controls[key]=control
        except Exception:continue
    return rows,controls

def main(data):
    from desktop_native import same
    same(data['window']);hwnd=data['window']['hwnd']
    rows,controls=inspect(hwnd)
    if data['op']=='inspect':return {'elements':rows}
    if data['op']=='press_key':
        from desktop_native import u,focus
        import threading
        focus(data['window'],threading.Event())
        keys={'escape':'{Esc}','enter':'{Enter}','tab':'{Tab}','shift+tab':'{Shift}{Tab}',
              'ctrl+a':'{Ctrl}a','ctrl+c':'{Ctrl}c','ctrl+v':'{Ctrl}v','ctrl+s':'{Ctrl}s',
              'delete':'{Delete}','up':'{Up}','down':'{Down}','left':'{Left}','right':'{Right}',
              'pageup':'{PageUp}','pagedown':'{PageDown}'}
        key=keys.get(data.get('key'))
        if not key:raise ValueError('Клавиша не разрешена.')
        focused=auto.GetFocusedControl()
        if focused and focused.IsPassword:raise ValueError('Ввод в поле пароля запрещён.')
        if u.GetForegroundWindow()!=hwnd:raise ValueError('Фокус окна изменился.')
        auto.SendKeys(key,waitTime=0)
        time.sleep(.3);after,_=inspect(hwnd)
        return {'verified':after!=rows,'elements':after}
    element=data.get('element',{})
    selected=next((row for row in rows if row['id']==element.get('id') and row['name']==element.get('name') and row['type']==element.get('type')),None)
    if not selected or not selected['enabled']:raise ValueError('Элемент исчез, изменился или недоступен. Повторите запрос.')
    control=controls[selected['id']]
    if data['op']=='click':
        selection=control.GetPattern(auto.PatternId.SelectionItemPattern)
        expand=control.GetPattern(auto.PatternId.ExpandCollapsePattern)
        if expand and expand.ExpandCollapseState==3:expand=None
        if selected['type'] in ('TabItemControl','ListItemControl') and selection:
            if selection.IsSelected:return {'verified':True,'elements':rows}
            selection.Select(waitTime=0)
            pattern=None
        elif expand:
            if expand.ExpandCollapseState==0:expand.Expand(waitTime=0)
            else:expand.Collapse(waitTime=0)
            pattern=None
        else:pattern=control.GetPattern(auto.PatternId.InvokePattern)
        if pattern:pattern.Invoke(waitTime=0)
        elif not (selection and selected['type'] in ('TabItemControl','ListItemControl') or expand):
            pattern=control.GetPattern(auto.PatternId.SelectionItemPattern)
            if pattern:pattern.Select(waitTime=0)
            else:
                pattern=control.GetPattern(auto.PatternId.TogglePattern)
                if pattern:pattern.Toggle(waitTime=0)
                else:raise ValueError('У элемента нет безопасного действия UI Automation.')
    elif data['op']=='type_text':
        if control.IsPassword:raise ValueError('Ввод пароля запрещён.')
        pattern=control.GetPattern(auto.PatternId.ValuePattern)
        if not pattern or pattern.IsReadOnly:raise ValueError('Поле не поддерживает ввод через UI Automation.')
        pattern.SetValue(data['text'],waitTime=0)
        return {'verified':pattern.Value==data['text'],'elements':rows}
    elif data['op']=='scroll':
        pattern=control.GetPattern(auto.PatternId.ScrollPattern)
        if not pattern:raise ValueError('Элемент не поддерживает прокрутку UI Automation.')
        pattern.Scroll(auto.ScrollAmount.NoAmount,auto.ScrollAmount.LargeDecrement if data['direction']=='up' else auto.ScrollAmount.LargeIncrement,waitTime=0)
    else:raise ValueError('Действие не разрешено.')
    stable=lambda items:[{k:v for k,v in item.items() if k!='focused'} for item in items]
    before=json.dumps(stable(rows),ensure_ascii=False,sort_keys=True)
    for _ in range(8):
        time.sleep(.1)
        try:after,_=inspect(hwnd)
        except Exception:
            from desktop_native import info
            return {'verified':info(hwnd) is None,'elements':[]}
        if json.dumps(stable(after),ensure_ascii=False,sort_keys=True)!=before:return {'verified':True,'elements':after}
    return {'verified':False,'elements':rows}

if __name__=='__main__':
    try:result=main(json.loads(sys.stdin.buffer.read().decode('utf-8')))
    except Exception as exc:result={'error':str(exc)}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
