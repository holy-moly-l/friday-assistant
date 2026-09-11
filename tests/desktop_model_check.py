"""Real installed Ollama model, synthetic observations only; no actions executed."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
from desktop_agent import DesktopAgent
async def main():
    with tempfile.TemporaryDirectory() as temp:
        agent=DesktopAgent(temp)
        examples=[
            ('Перекинь вот это окошко на второй экран, пожалуйста',{'window':{'title':'Калькулятор'},'monitors':[{'index':1},{'index':2}]},None),
            ('С музыкой перебор, убавь немного громкость',{},None),
            ('Что за ошибка вылезла?',{'window':{'title':'Тест'},'elements':[{'name':'Ошибка 810: тестовый документ не найден','type':'TextControl'}]},None),
        ]
        im=Image.new('RGB',(900,500),'#182534');d=ImageDraw.Draw(im);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',30)
        d.text((50,80),'Ошибка 810',font=font,fill='white');d.text((50,145),'Документ не найден',font=font,fill='white');d.rectangle((50,270,290,340),fill='#238dcc');d.text((75,285),'Продолжить',font=font,fill='white')
        buf=io.BytesIO();im.save(buf,format='JPEG');picture=base64.b64encode(buf.getvalue()).decode()
        examples.append(('Что за ошибка вылезла?',{'window':{'title':'Тест'},'elements':[]},picture))
        results=[]
        for text,observation,image in examples:
            start=time.monotonic();plan=await agent.plan(text,[{'role':'user','content':text}],observation,image)
            print(json.dumps({'request':text,'seconds':round(time.monotonic()-start,1),'plan':plan.model_dump()},ensure_ascii=False),flush=True);results.append(plan)
        assert results[0].steps[0].tool=='window' and results[0].steps[0].monitor==2
        assert results[1].steps[0].tool=='volume' and results[1].steps[0].value<0
        assert not results[2].steps and '810' in results[2].reply
        assert not results[3].steps and '810' in results[3].reply
        unchanged=await agent.verify_visual('Закрой ошибку',picture,picture)
        assert not unchanged.verified
        cleared=Image.new('RGB',(900,500),'#182534');draw=ImageDraw.Draw(cleared);draw.text((50,80),'Документ открыт. Ошибок нет.',font=font,fill='white')
        buf=io.BytesIO();cleared.save(buf,format='JPEG');after=base64.b64encode(buf.getvalue()).decode()
        changed=await agent.verify_visual('Закрой ошибку',picture,after)
        assert changed.verified
        print('VISUAL_VERIFICATION_OK',changed.explanation,flush=True)
        print('LOCAL_MODEL_AND_VISION_OK',flush=True)
asyncio.run(main())
