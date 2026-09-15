"""Opt-in local diagnostics. Never log image bytes, credentials or full requests."""
import json
import os
import re
import sys

# Closed field allowlist: new callers cannot accidentally log a field value or model answer.
NUMERIC={'length','hwnd','elements','images','monitor','count','verified','uncertain','image_attached',
         'changed_ratio','target_difference','displacement','restored','fallback','redacted','non_fatal'}
ENUMS={
    'route':{'deterministic','vision','model'},
    'operation':{'inspect','click','press_key','type_text','scroll'},
    'scope':{'window','monitor','all_screens'},
    'method':{'PrintWindow','MonitorCropFallback','ImageGrab'},
    'tool':{'open_app','window','volume','click','type_text','press_key','scroll','click_point','list_windows','get_active_window','list_monitors','window_monitor'},
    'kind':{'exe','shortcut','shell'},
    'intent':{'open_app','window','volume','click','type_text','press_key','scroll','click_point','list_windows','get_active_window','list_monitors','window_monitor','vision','stop','conversation','unknown'},
    'status':{'success','error','cancelled','unavailable','requested'},
}


def trace(stage, message='', **fields):
    if os.environ.get('FRIDAY_DEBUG', '').lower() not in ('1', 'true', 'yes'):
        return
    safe={}
    if message:safe['length']=len(str(message))
    target=fields.get('target')
    if isinstance(target,dict):
        for key in ('hwnd','monitor'):
            if type(target.get(key))==int:safe[key]=target[key]
    for key,value in fields.items():
        if key in NUMERIC and type(value) in (int,float,bool):safe[key]=value
        elif key in ENUMS and isinstance(value,str) and value in ENUMS[key]:safe[key]=value
        elif key=='model' and isinstance(value,str) and re.fullmatch(r'qwen3\.5:(?:0\.8|2|4|9)b',value):safe[key]=value
        elif key in ('size','original_size','rect') and isinstance(value,(list,tuple)) and all(type(v)==int for v in value):safe[key]=value
    if message or len(safe)<len(fields):safe['redacted']=True
    print(f'[{stage}] '+json.dumps(safe,ensure_ascii=False),file=sys.stderr,flush=True)
