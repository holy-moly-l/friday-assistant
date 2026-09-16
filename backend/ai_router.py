"""Small provider router and progressive screenshots; no desktop execution here."""
import asyncio
import base64
from dataclasses import dataclass
import io
import json
import re
import time
from PIL import Image
from ai_providers import CodexProvider,LocalOllamaProvider,ProviderError,OBSERVER,CLOUD_MODELS
from desktop_trace import trace

AI_MODES=('local','hybrid','codex_vision')
INSPECTION_SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'reply':{'type':'string','maxLength':2000},'needs_crop':{'type':'boolean'},
    'crop':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4}},
    'required':['reply','needs_crop','crop']}

@dataclass
class PreparedImage:
    encoded:str
    original:tuple
    sent:tuple
    size_kb:float
    preprocess_ms:float

def decode(image):
    im=Image.open(io.BytesIO(base64.b64decode(image,validate=True)))
    if im.width*im.height>64000000:raise ProviderError('invalid_response','Снимок слишком большой.')
    return im.convert('RGB')

def encode(im):
    buf=io.BytesIO();im.save(buf,format='PNG');return base64.b64encode(buf.getvalue()).decode('ascii')

def prepare_image(image,optimize=True):
    start=time.perf_counter();im=decode(image);original=im.size
    if optimize:im.thumbnail((1440,1440),Image.Resampling.LANCZOS)
    result=encode(im)
    if optimize and len(result)>350000:
        buf=io.BytesIO();im.save(buf,format='JPEG',quality=90,subsampling=0)
        jpeg=base64.b64encode(buf.getvalue()).decode('ascii')
        if len(jpeg)<len(result)*.8:result=jpeg
    return PreparedImage(result,original,im.size,round(len(base64.b64decode(result))/1024,1),round((time.perf_counter()-start)*1000,1))

def crop_image(image,box,*,pad=0):
    """0..1000 coordinates in original image; return exact normalized crop rect."""
    if len(box)!=4 or any(type(v) not in (int,float) or not 0<=v<=1000 for v in box):raise ValueError('Invalid crop')
    x0,y0,x1,y1=box
    if x1<=x0 or y1<=y0:raise ValueError('Empty crop')
    im=decode(image);w,h=im.size
    rect=(max(0,int(x0*w/1000-pad)),max(0,int(y0*h/1000-pad)),
          min(w,int(x1*w/1000+pad+.999)),min(h,int(y1*h/1000+pad+.999)))
    if rect[2]-rect[0]<24 or rect[3]-rect[1]<24:raise ValueError('Tiny crop')
    return encode(im.crop(rect)),[rect[0]/w,rect[1]/h,rect[2]/w,rect[3]/h]

def map_box(box,rect):
    return [round((rect[axis%2]+value/1000*(rect[axis%2+2]-rect[axis%2]))*1000) for axis,value in enumerate(box)]

def complex_planning(text):
    # Deterministic commands have already been handled before this routing point.
    return bool(re.search(r'разберись|спланируй|пошагов|сначала.+(?:потом|затем|после)|(?:,| и ).+(?:,| и )',text,re.I))

class ModelRouter:
    def __init__(self,local_model='qwen3.5:4b',before_model=None,*,mode='hybrid',cloud_model=CLOUD_MODELS[0],fallback=True,optimize=True,vision_provider='ollama'):
        self.local=LocalOllamaProvider(local_model,before_model);self.codex=CodexProvider(cloud_model)
        self.mode=mode;self.fallback=fallback;self.optimize=optimize;self.vision_provider=vision_provider;self.capture={};self.last_result=None
    def cancel(self):self.codex.cancel();self.local.cancel()
    def settings(self):
        return dict(ai_mode=self.mode,cloud_model=self.codex.model,local_fallback=self.fallback,image_optimization=self.optimize,vision_provider=self.vision_provider,
            codex=dict(status=self.codex.status,authenticated=bool(self.codex._auth),version=self.codex.version))
    def cloud_for(self,*,image=False,task=''):
        if self.mode=='local':return False
        if image:return self.mode=='codex_vision' or self.vision_provider=='codex'
        return complex_planning(task)
    async def _call(self,method,args,kwargs,cloud):
        started=time.perf_counter();fallback_ms=0
        if cloud:
            try:result=await getattr(self.codex,method)(*args,**kwargs)
            except ProviderError as exc:
                trace('CODEX',status=exc.status)
                if not self.fallback:raise
                trace('FALLBACK',provider='ollama',model=self.local.model,status='requested')
                fallback_ms=round((time.perf_counter()-started)*1000)
                try:result=await getattr(self.local,method)(*args,**kwargs)
                except ProviderError as local_error:
                    raise ProviderError(local_error.status,'Codex и локальная Ollama сейчас недоступны. Простые команды Windows продолжают работать.') from local_error
        else:result=await getattr(self.local,method)(*args,**kwargs)
        result.metrics['fallback_ms']=fallback_ms
        result.metrics['chain_ms']=round((time.perf_counter()-started)*1000)
        self.last_result=result;return result
    async def plan(self,task,context,*,schema,system):
        return await self._call('plan',(task,context),dict(schema=schema,system=system),self.cloud_for(task=task))
    async def analyze_image(self,image,prompt,*,schema=None,system=None):
        started=time.perf_counter()
        originals=image if isinstance(image,list) else [image]
        prepared=await asyncio.to_thread(lambda:[prepare_image(im,self.optimize) for im in originals])
        result=await self._call('analyze_image',([p.encoded for p in prepared],prompt),dict(schema=schema,system=system),self.cloud_for(image=True))
        metrics=result.metrics
        metrics.update(capture_ms=self.capture.get('capture_ms',0),preprocess_ms=round(sum(p.preprocess_ms for p in prepared),1),
            total_ms=round((time.perf_counter()-started)*1000+self.capture.get('capture_ms',0)))
        for p in prepared:trace('VISION',provider=result.provider,model=result.model,scope=self.capture.get('scope','window'),
            original_size=list(p.original),size=list(p.sent),size_kb=p.size_kb,**metrics)
        return result
    async def describe(self,prompt,image):
        start=time.perf_counter()
        result=await self.analyze_image(image,prompt,schema=INSPECTION_SCHEMA,system=OBSERVER+
            ' Опиши наблюдаемое. Если для вопроса нужен неразборчивый мелкий текст, поставь needs_crop=true '
            'и crop=[left,top,right,bottom] интересующей области в координатах 0..1000. '
            'Иначе needs_crop=false и crop=[0,0,0,0]. Не запрашивай crop ради подробного описания всего экрана.')
        try:
            data=json.loads(result.content)
            if type(data.get('reply')) is not str or type(data.get('needs_crop')) is not bool:raise ValueError()
        except (ValueError,AttributeError) as exc:raise ProviderError('invalid_response','Модель вернула некорректный ответ на изображение.') from exc
        if data['needs_crop']:
            try:
                area=(data['crop'][2]-data['crop'][0])*(data['crop'][3]-data['crop'][1])/1000000
                if not .001<=area<=.85:raise ValueError()
                crop,_=await asyncio.to_thread(crop_image,image,data['crop'],pad=24)
            except (ValueError,KeyError,TypeError,IndexError):return data['reply']+' Мелкий текст не удалось надёжно прочитать.'
            detail=await self.analyze_image(crop,prompt+'\nЭто увеличенный фрагмент исходного снимка. Ответь по этому фрагменту.',system=OBSERVER)
            try:data['reply']=json.loads(detail.content)['reply']
            except (ValueError,KeyError,TypeError) as exc:raise ProviderError('invalid_response','Не удалось прочитать фрагмент изображения.') from exc
        trace('VISION CHAIN',total_ms=round((time.perf_counter()-start)*1000+self.capture.get('capture_ms',0)))
        return data['reply'][:4000]
