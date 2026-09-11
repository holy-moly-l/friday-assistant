import { useEffect, useRef, useState } from 'react';
type Props={device:string;disabled:boolean;onTestingChange:(value:boolean)=>void;api:(path:string,options?:RequestInit)=>Promise<any>};
export function RecognitionTest({device,disabled,onTestingChange,api}:Props){
  const [phase,setPhase]=useState<'idle'|'recording'|'transcribing'>('idle'),[text,setText]=useState(''),[warning,setWarning]=useState(''),[name,setName]=useState(''),[url,setURL]=useState('');
  const source=useRef<MediaStream|undefined>(undefined),recorder=useRef<MediaRecorder|undefined>(undefined),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),generation=useRef(0),audioURL=useRef(''),abort=useRef<AbortController|undefined>(undefined);
  function clear(){generation.current++;abort.current?.abort();clearTimeout(timer.current);if(recorder.current?.state==='recording'){recorder.current.onstop=null;recorder.current.stop();}source.current?.getTracks().forEach(t=>t.stop());onTestingChange(false);if(audioURL.current)URL.revokeObjectURL(audioURL.current);audioURL.current='';}
  useEffect(()=>()=>clear(),[]);
  useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){clear();setPhase('idle');setURL('');}};window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape);},[]);
  useEffect(()=>{clear();setPhase('idle');setURL('');setText('');},[device]);
  async function record(){
    clear();setURL('');setText('');setWarning('');onTestingChange(true);setPhase('recording');const current=generation.current;
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:device?{exact:device}:undefined,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
      if(current!==generation.current){stream.getTracks().forEach(t=>t.stop());return;}source.current=stream;setName(stream.getAudioTracks()[0].label);
      const chunks:BlobPart[]=[];const rec=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus',audioBitsPerSecond:128000});recorder.current=rec;
      rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      rec.onstop=async()=>{
        clearTimeout(timer.current);stream.getTracks().forEach(t=>t.stop());if(current!==generation.current)return;
        const blob=new Blob(chunks,{type:rec.mimeType});const audio=URL.createObjectURL(blob);audioURL.current=audio;setURL(audio);setPhase('transcribing');
        const form=new FormData();form.append('audio',blob,'recognition-test.webm');const controller=new AbortController();abort.current=controller;
        try{const result=await api('/transcribe',{method:'POST',body:form,signal:controller.signal});if(current!==generation.current)return;setText(result.text||'Речь не обнаружена');setWarning(result.warning||(result.uncertain?'Результат неуверенный. Попробуйте говорить ближе к микрофону.':''));}
        catch(e){if(current===generation.current)setWarning((e as Error).message);}
        finally{if(current===generation.current){setPhase('idle');onTestingChange(false);}}
      };
      rec.start(200);timer.current=setTimeout(()=>{if(rec.state==='recording')rec.stop();},10000);
    }catch{if(current===generation.current){clear();setPhase('idle');setWarning('Не удалось включить выбранный микрофон.');}}
  }
  return <section className="settings-card"><div className="settings-card-heading"><div><h2>Проверка распознавания</h2><p>Произнесите фразу. Она появится здесь, команда не выполнится.</p></div></div>
    <button className="primary-button" disabled={disabled||phase==='transcribing'} onClick={()=>{if(phase!=='recording'){void record();return;}if(recorder.current?.state==='recording')recorder.current.stop();else{clear();setPhase('idle');}}}>{phase==='recording'?'Закончить запись':phase==='transcribing'?'Распознаю…':'Проверить распознавание'}</button>
    {phase==='recording'&&<p className="mic-hint" role="status">Говорите — запись до 10 секунд. {name}</p>}
    {text&&<p style={{marginTop:16,whiteSpace:'pre-wrap'}} aria-label="Результат распознавания">{text}</p>}
    {warning&&<p className="mic-error" role="status">{warning}</p>}
    {url&&<audio style={{marginTop:12,width:'100%'}} controls onPlay={()=>onTestingChange(true)} onPause={()=>onTestingChange(phase!=='idle')} onEnded={()=>onTestingChange(phase!=='idle')} src={url} aria-label="Прослушать запись микрофона"/>}
  </section>;
}
