import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Mic, RefreshCw, Square } from 'lucide-react';

type Props = { device: string; onChange: (device: string) => void; autoStop: boolean; onAutoStop: () => void; disabled: boolean; onTestingChange?: (value:boolean)=>void };
export function MicrophoneSettings({device,onChange,autoStop,onAutoStop,disabled,onTestingChange}:Props) {
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]);
  const [loading,setLoading]=useState(false), [testing,setTesting]=useState(false), [level,setLevel]=useState(0), [error,setError]=useState('');
  const [activeName,setActiveName]=useState('');
  const stream=useRef<MediaStream|null>(null), ctx=useRef<AudioContext|null>(null), frame=useRef(0), generation=useRef(0);
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  function stop(){generation.current++;stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;if(ctx.current){void ctx.current.close();ctx.current=null;}cancelAnimationFrame(frame.current);if(timer.current)clearTimeout(timer.current);setTesting(false);setLevel(0);onTestingChange?.(false);}
  async function refresh(requestPermission=false){
    setLoading(true);setError('');
    try{
      if(requestPermission){const sample=await navigator.mediaDevices.getUserMedia({audio:true,video:false});sample.getTracks().forEach(t=>t.stop());}
      const list=await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter(x=>x.kind==='audioinput'&&x.deviceId&&x.deviceId!=='communications'));
    }catch(e){setError((e as Error).name==='NotAllowedError'?'Разрешите доступ к микрофону в настройках конфиденциальности Windows.':'Не удалось получить список микрофонов. Проверьте подключение устройства.');}
    finally{setLoading(false);}
  }
  useEffect(()=>{void refresh();const change=()=>void refresh();navigator.mediaDevices.addEventListener('devicechange',change);return()=>{stop();navigator.mediaDevices.removeEventListener('devicechange',change);};},[]);
  useEffect(()=>{stop();},[device]);
  useEffect(()=>{if(disabled)stop();},[disabled]);
  useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')stop();};window.addEventListener('keydown',escape);return()=>window.removeEventListener('keydown',escape);},[]);
  async function test(){
    if(testing){stop();return;}stop();onTestingChange?.(true);setError('');const current=generation.current;
    try{
      const source=await navigator.mediaDevices.getUserMedia({audio:{deviceId:device?{exact:device}:undefined,echoCancellation:true,noiseSuppression:true},video:false});
      if(current!==generation.current){source.getTracks().forEach(t=>t.stop());return;}
      stream.current=source;setActiveName(source.getAudioTracks()[0].label||'Системный микрофон');setTesting(true);void refresh();
      const ac=new AudioContext();ctx.current=ac;const analyser=ac.createAnalyser();analyser.fftSize=512;ac.createMediaStreamSource(source).connect(analyser);const data=new Uint8Array(analyser.fftSize);
      const draw=()=>{analyser.getByteTimeDomainData(data);const rms=Math.sqrt(data.reduce((n,v)=>n+((v-128)/128)**2,0)/data.length);setLevel(Math.min(100,rms*600));frame.current=requestAnimationFrame(draw);};draw();
      timer.current=setTimeout(stop,20000);
    }catch(e){stop();setError((e as Error).name==='OverconstrainedError'?'Выбранный микрофон отключён. Выберите другое устройство.':'Не удалось включить микрофон. Проверьте доступ и подключение.');}
  }
  const unavailable=device&&!devices.some(d=>d.deviceId===device);
  return <section className="settings-card microphone-card">
    <div className="settings-card-heading"><Mic size={22}/><h2>Микрофон</h2></div>
    <div className="microphone-select-row"><div className="microphone-select"><label htmlFor="friday-microphone">Устройство ввода</label><select id="friday-microphone" aria-label="Устройство ввода" value={device} disabled={disabled} onChange={e=>onChange(e.target.value)}><option value="">Системный микрофон (по умолчанию)</option>{unavailable&&<option value={device}>Сохранённый микрофон — не подключён</option>}{devices.filter(d=>d.deviceId!=='default').map((d,i)=><option key={d.deviceId} value={d.deviceId}>{d.label||`Микрофон ${i+1}`}</option>)}</select></div><button className="outline-button" disabled={loading||disabled||testing} onClick={()=>refresh(true)}>{loading?<LoaderCircle className="spinning" size={16}/>:<RefreshCw size={16}/>}Обновить список</button><button className={'primary-button '+(testing?'testing':'')} disabled={disabled||!!unavailable} onClick={test}>{testing?<Square size={14}/>:<Mic size={16}/>} {testing?'Остановить проверку':'Проверить микрофон'}</button></div>
    {!devices.some(d=>d.label)&&<p className="mic-hint">Нажмите «Обновить список», чтобы разрешить доступ и увидеть названия подключённых микрофонов.</p>}
    {error&&<p className="mic-error" role="alert">{error}</p>}
    {testing&&<div className="mic-test-panel listening"><span><Mic size={16}/></span><div><strong>Говорите — индикатор должен двигаться</strong><p>{activeName}</p></div><div className="mic-meter" role="meter" aria-label="Уровень микрофона" aria-valuenow={Math.round(level)} aria-valuemin={0} aria-valuemax={100}>{Array.from({length:28},(_,i)=><i key={i} className={level>i*100/28?'lit':''}/>)}</div></div>}
    <div className="settings-row"><div><strong>Отправлять команду после паузы</strong><p>Запись завершится через 2 секунды тишины. Можно остановить её кнопкой.</p></div><button className={'toggle '+(autoStop?'on':'')} role="switch" aria-checked={autoStop} aria-label="Отправлять после паузы" onClick={onAutoStop}><span/></button></div>
  </section>;
}
