"""Tolerant scene and target comparisons; no full-frame pixel equality."""
import base64
import io
import math
import numpy as np
from PIL import Image,ImageFilter
from pc import CommandError

MAX_SCENE_CHANGE=.28
MAX_TARGET_MOVEMENT=.18


def decode(image):return Image.open(io.BytesIO(base64.b64decode(image))).convert('RGB')


def changed_ratio(before,after,boxes=None):
    a,b=decode(before),decode(after)
    if boxes:
        def crop(im,box):return im.crop(tuple(round(v*(im.width if i%2==0 else im.height)) for i,v in enumerate(box)))
        a,b=crop(a,boxes[0]),crop(b,boxes[1])
    else:
        # Ignore window frame activation changes.
        a=a.crop((10,36,max(11,a.width-10),max(37,a.height-10)))
        b=b.crop((10,36,max(11,b.width-10),max(37,b.height-10)))
    size=(160,80) if boxes else (480,320)
    a=np.asarray(a.resize(size).filter(ImageFilter.GaussianBlur(1)),dtype=np.int16)
    b=np.asarray(b.resize(size).filter(ImageFilter.GaussianBlur(1)),dtype=np.int16)
    return float(np.mean(np.max(np.abs(a-b),axis=2)>24))


def scene_stable(before,after):
    ratio=changed_ratio(before,after)
    if ratio>MAX_SCENE_CHANGE:raise CommandError('Интерфейс заметно изменился после подтверждения. Повторите команду.')
    return ratio


def target_stable(before,after,old,new):
    move=math.hypot(new.x-old.x,new.y-old.y)
    if move>MAX_TARGET_MOVEMENT:raise CommandError('Кнопка переместилась слишком далеко. Нужно новое подтверждение.')
    # The model's two boxes can differ by several pixels. Track the original patch near the
    # fresh model location using normalized correlation (insensitive to active-button colour).
    a,b=decode(before),decode(after)
    size=(480,max(100,round(480*a.height/a.width)))
    a=np.asarray(a.convert('L').resize(size).filter(ImageFilter.GaussianBlur(.6)),dtype=np.float32)
    b=np.asarray(b.convert('L').resize(size).filter(ImageFilter.GaussianBlur(.6)),dtype=np.float32)
    width,height=size
    box=old.box or [max(0,old.x-.07),max(0,old.y-.045),min(1,old.x+.07),min(1,old.y+.045)]
    left,top,right,bottom=[round(v*(width if i%2==0 else height)) for i,v in enumerate(box)]
    right=min(right,left+140);bottom=min(bottom,top+80)
    template=a[top:bottom,left:right]
    if min(template.shape,default=0)<4:raise CommandError('Кнопка слишком мала для надёжной проверки.')
    template=template-template.mean();energy=float(np.sum(template*template))
    if energy<100:raise CommandError('Не удалось различить детали кнопки. Нужно новое подтверждение.')
    dx=round((new.x-old.x)*width);dy=round((new.y-old.y)*height)
    x0=max(0,left+dx-35);y0=max(0,top+dy-35)
    x1=min(width,right+dx+35);y1=min(height,bottom+dy+35)
    region=b[y0:y1,x0:x1]
    if region.shape[0]<template.shape[0] or region.shape[1]<template.shape[1]:raise CommandError('Кнопка ушла за пределы снимка.')
    candidates=np.lib.stride_tricks.sliding_window_view(region,template.shape)
    count=template.size
    sums=candidates.sum(axis=(-2,-1));squares=np.einsum('ijkl,ijkl->ij',candidates,candidates,optimize=True)
    numerator=np.einsum('ijkl,kl->ij',candidates,template,optimize=True)
    denominator=np.sqrt(np.maximum(0,squares-sums*sums/count)*energy)
    scores=np.divide(numerator,denominator,out=np.zeros_like(numerator),where=denominator>1)
    iy,ix=np.unravel_index(np.argmax(scores),scores.shape);score=float(scores[iy,ix])
    if score<.65:raise CommandError('Найденная кнопка выглядит иначе. Нужно новое подтверждение.')
    shift_x=(x0+ix-left)/width;shift_y=(y0+iy-top)/height
    if math.hypot(shift_x,shift_y)>MAX_TARGET_MOVEMENT:
        raise CommandError('Кнопка переместилась слишком далеко. Нужно новое подтверждение.')
    x,y=old.x+shift_x,old.y+shift_y
    if not (0<x<1 and 0<y<1) or math.hypot(x-new.x,y-new.y)>.10:
        raise CommandError('Модель и проверка изображения не согласны с положением кнопки.')
    new.x=x;new.y=y
    new.box=[max(0,min(1,v+(shift_x if i%2==0 else shift_y))) for i,v in enumerate(box)]
    return 1-score,math.hypot(shift_x,shift_y)
