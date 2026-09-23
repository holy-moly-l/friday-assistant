import {useEffect,useRef,useState} from 'react';
import {Camera,CameraOff,Hand,Monitor,Play,RefreshCw,ShieldCheck,Square,Move,Maximize,ArrowLeftRight,ChevronDown} from 'lucide-react';
import {GestureRecognizer,type GestureAction,type Mode} from './gestures';
import {drawHands} from './handSkeleton';
import './camera.css';

type Api=(path:string,options?:RequestInit)=>Promise<any>;
type Targets={windows:{hwnd:number;title:string;process:string}[];monitors:{index:number}[];media:{id:string;title:string;seek:boolean;ambiguous:boolean}[];media_error?:string};
const emptyTargets:Targets={windows:[],monitors:[],media:[]};
const post=(body?:object):RequestInit=>({method:'POST',body:body?JSON.stringify(body):undefined});
const cameraError=(error:unknown)=>{
  const name=(error as Error).name;
  return name==='NotAllowedError'?'Доступ к камере запрещён. Разрешите камеру для Пятницы в параметрах Windows.':name==='NotFoundError'?'Камера не найдена. Подключите её и обновите список.':name==='NotReadableError'?'Камера занята другим приложением или отключена. Закройте другую видеосвязь и повторите.':(error as Error).message||'Не удалось включить камеру.';
};

export function CameraHands({api}:{api:Api}){
  const [status,setStatus]=useState<'off'|'loading'|'ready'>('off');const [error,setError]=useState('');
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]);const [device,setDevice]=useState(()=>localStorage.getItem('friday-camera')||'');
  const [mode,setMode]=useState<Mode>('windows');const [leading,setLeading]=useState('Right');
  const [targets,setTargets]=useState<Targets>(emptyTargets);const [hwnd,setHwnd]=useState(0);const [mediaId,setMediaId]=useState('');
  const [armed,setArmed]=useState(false);const [arming,setArming]=useState(false);const [overlay,setOverlay]=useState(true);
  const [stats,setStats]=useState({hands:0,fps:0,latency:0});const [hint,setHint]=useState('Включите камеру — увидите себя и обе руки');
  const [lastAction,setLastAction]=useState('');
  const video=useRef<HTMLVideoElement>(null),canvas=useRef<HTMLCanvasElement>(null);
  const stream=useRef<MediaStream|null>(null),worker=useRef<Worker|null>(null),generation=useRef(0);
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null),modelTimeout=useRef<ReturnType<typeof setTimeout>|null>(null);
  const session=useRef(''),sequence=useRef(0),inFlight=useRef(false),releasePending=useRef(false);
  const tracker=useRef(new GestureRecognizer()),showOverlay=useRef(overlay);
  const mounted=useRef(true),armGeneration=useRef(0);showOverlay.current=overlay;

  async function refreshDevices(){const all=await navigator.mediaDevices.enumerateDevices();if(mounted.current)setDevices(all.filter(d=>d.kind==='videoinput'));}
  async function refreshTargets(){
    try{const t:Targets=await api('/gestures/targets');if(mounted.current){setTargets(t);setHwnd(old=>t.windows.some(w=>w.hwnd===old)?old:0);setMediaId(old=>t.media.some(m=>m.id===old)?old:'');}}
    catch(e){if(mounted.current)setError((e as Error).message);}
  }
  function disarm(message='Управление остановлено'){
    armGeneration.current++;session.current='';releasePending.current=false;tracker.current.reset();
    if(mounted.current){setArmed(false);setArming(false);setLastAction(message);}
    void api('/gestures/stop',post()).catch(()=>{});
  }
  function shutdown(){
    generation.current++;disarm();worker.current?.terminate();worker.current=null;
    if(timer.current)clearTimeout(timer.current);if(modelTimeout.current)clearTimeout(modelTimeout.current);
    stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;
    if(video.current)video.current.srcObject=null;
    if(canvas.current)canvas.current.getContext('2d')?.clearRect(0,0,canvas.current.width,canvas.current.height);
    if(mounted.current){setStatus('off');setStats({hands:0,fps:0,latency:0});setHint('Камера выключена');}
  }
  async function sendAction(action:GestureAction){
    if(action.kind==='stop'){disarm('Остановлено жестом');return;}
    const token=session.current;if(!token)return;
    if(inFlight.current){if(action.kind==='release')releasePending.current=true;else if(action.kind!=='drag_move')tracker.current.reset();return;}
    inFlight.current=true;
    try{
      const result=await api('/gestures/action',{...post({token,sequence:++sequence.current,...action}),signal:AbortSignal.timeout(6500)});
      if(session.current===token && mounted.current)setLastAction(result.message);
    }catch(e){if(session.current===token){setError((e as Error).message);disarm();}}
    finally{
      inFlight.current=false;
      if(releasePending.current && session.current===token){releasePending.current=false;void sendAction({kind:'release'});}
    }
  }
  async function enable(){
    if(!video.current)return;
    shutdown();setStatus('loading');setError('');setHint('Подключаю камеру и локальную модель…');
    const gen=generation.current;
    try{
      const capture=await navigator.mediaDevices.getUserMedia({audio:false,video:{deviceId:device?{exact:device}:undefined,width:{ideal:1280},height:{ideal:720},frameRate:{ideal:30,max:30}}});
      if(gen!==generation.current){capture.getTracks().forEach(t=>t.stop());return;}
      stream.current=capture;capture.getVideoTracks()[0].onended=()=>{shutdown();setError('Камера отключилась. Подключите её снова.');};
      video.current!.srcObject=capture;await video.current!.play();await refreshDevices();
      if(gen!==generation.current)return;
      localStorage.setItem('friday-camera',device);
      const w=new Worker(new URL('./hands.worker.ts',import.meta.url),{type:'module'});worker.current=w;
      let sent=0,received=0,frameBusy=false,previousVideoTime=-1,lastResult=performance.now(),fpsStart=performance.now(),frames=0,fps=0;
      const fail=(message:string)=>{if(gen!==generation.current)return;shutdown();setError(message);};
      const frame=async()=>{
        if(gen!==generation.current)return;
        const v=video.current;
        if(performance.now()-lastResult>2500){fail('Отслеживание перестало отвечать. Управление остановлено.');return;}
        if(v && v.readyState>=2 && !frameBusy && v.currentTime!==previousVideoTime){
          frameBusy=true;previousVideoTime=v.currentTime;sent=performance.now();
          try{
            // Full-resolution preview, smaller inference frames; one frame in flight, no backlog.
            const bitmap=await createImageBitmap(v,{resizeWidth:Math.min(640,v.videoWidth),resizeQuality:'medium'});
            if(gen!==generation.current){bitmap.close();return;}
            w.postMessage({type:'frame',frame:bitmap,time:sent},[bitmap]);
          }catch{fail('Не удалось прочитать кадр камеры.');return;}
        }
        timer.current=setTimeout(()=>void frame(),45);
      };
      modelTimeout.current=setTimeout(()=>fail('Модель рук не загрузилась за 25 секунд. Повторите включение камеры.'),25000);
      w.onerror=()=>fail('Ошибка локальной модели рук. Попробуйте включить камеру снова.');
      w.onmessage=event=>{
        if(gen!==generation.current)return;
        const data=event.data;
        if(data.type==='ready'){
          if(modelTimeout.current)clearTimeout(modelTimeout.current);
          setStatus('ready');lastResult=performance.now();fpsStart=lastResult;frames=0;void frame();
        }else if(data.type==='error'){fail(data.message);}
        else if(data.type==='hands'){
          frameBusy=false;const now=performance.now();lastResult=now;
          frames++;if(now-fpsStart>=1000){fps=Math.round(frames*1000/(now-fpsStart));fpsStart=now;frames=0;}
          const events=tracker.current.update(data.hands,now);
          if(session.current){for(const action of events)void sendAction(action);}
          else tracker.current.reset();
          if(canvas.current && video.current)drawHands(canvas.current,showOverlay.current?data.hands:[],video.current.videoWidth,video.current.videoHeight,session.current?tracker.current.progress:0,tracker.current.hand);
          if(now-received>200){setStats({hands:data.hands.length,fps,latency:Math.round(data.latency)});setHint(session.current?tracker.current.hint:data.hands.length?'Руки видны. Выберите окно или видео для управления':'Покажите руки в кадре');received=now;}
        }
      };
      w.postMessage({type:'init',base:location.origin});void refreshTargets();
    }catch(e){if(gen===generation.current){shutdown();setError(cameraError(e));}}
  }
  async function arm(){
    const gen=++armGeneration.current;setArming(true);setError('');
    try{
      const response=await api('/gestures/arm',post({mode,hwnd,media:mediaId}));
      if(gen!==armGeneration.current || !mounted.current){void api('/gestures/stop',post()).catch(()=>{});return;}
      tracker.current=new GestureRecognizer(mode,leading);session.current=response.token;sequence.current=0;setArmed(true);setLastAction('Управление включено');
    }catch(e){if(gen===armGeneration.current)setError((e as Error).message);}
    finally{if(gen===armGeneration.current)setArming(false);}
  }
  useEffect(()=>{
    mounted.current=true;void refreshDevices().catch(()=>{});void refreshTargets();
    const changed=()=>void refreshDevices().catch(()=>{});
    navigator.mediaDevices.addEventListener('devicechange',changed);
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')disarm();};
    const hidden=()=>{if(document.hidden)shutdown();};
    window.addEventListener('keydown',key);document.addEventListener('visibilitychange',hidden);
    window.addEventListener('friday-camera-suspend',shutdown);
    const heartbeat=setInterval(()=>{
      const token=session.current;if(!token)return;
      void api('/gestures/heartbeat',{...post({token}),signal:AbortSignal.timeout(1200)}).catch(()=>{if(session.current===token)disarm('Остановлено: связь с Windows прервалась');});
    },500);
    return()=>{mounted.current=false;shutdown();clearInterval(heartbeat);window.removeEventListener('keydown',key);window.removeEventListener('friday-camera-suspend',shutdown);document.removeEventListener('visibilitychange',hidden);navigator.mediaDevices.removeEventListener('devicechange',changed);};
  },[]);
  useEffect(()=>{tracker.current=new GestureRecognizer(mode,leading);},[mode,leading]);

  const guides=mode==='windows'?[
    {icon:Move,name:'Щипок и движение',text:'Соедините большой и указательный пальцы. Ведите руку — окно движется следом. Разожмите, чтобы отпустить.'},
    {icon:Maximize,name:'V — развернуть',text:'Указательный и средний вверх. Удерживайте 0,9 с; повторите, чтобы вернуть размер.'},
    {icon:ArrowLeftRight,name:'Ладонь в сторону',text:'Покажите открытую ладонь на 0,3 с, затем сдвиньте влево или вправо — на соседний монитор.'},
  ]:[
    {icon:Play,name:'Щипок — пауза',text:'Соедините большой и указательный на 0,6 с. Разожмите перед повтором.'},
    {icon:ArrowLeftRight,name:'Ладонь — ±5 секунд',text:'Удержите открытую ладонь 0,3 с, затем сдвиньте вправо или влево для перемотки.'},
  ];
  return <section className="camera-page">
    <div className="camera-intro"><span>Движение вместо мыши</span><p><ShieldCheck size={14}/> Камера обрабатывается на этом компьютере</p></div>
    <div className="camera-layout">
      <div className="camera-main">
        <div className={'camera-stage '+(armed?'is-armed':'')}>
          <video ref={video} muted playsInline aria-label="Превью веб-камеры"/>
          <canvas ref={canvas} className="hand-overlay" aria-label="Скелет обеих рук"/>
          {status==='off'&&<div className="camera-placeholder"><div className="camera-glyph"><Hand size={56} strokeWidth={1}/><span/></div><h2>Ваши руки. Ваше пространство.</h2><p>Включите камеру, чтобы увидеть движения</p><button className="primary-button" onClick={()=>void enable()}><Camera size={17}/>Включить камеру</button></div>}
          {status==='loading'&&<div className="camera-loading"><RefreshCw className="spinning" size={22}/><span>Подключаю камеру и отслеживание…</span><button onClick={shutdown}>Отмена</button></div>}
          {status==='ready'&&<><div className="camera-badges"><span className="camera-live"><i/>LIVE</span><span>{stats.hands} / 2 руки</span><span>{stats.fps} fps · {stats.latency} мс</span></div><div className="camera-hint"><Hand size={16}/><span>{hint}</span></div></>}
        </div>
        <div className="camera-toolbar"><label>Камера<select aria-label="Выбор камеры" value={device} disabled={status!=='off'} onChange={e=>{setDevice(e.target.value);localStorage.setItem('friday-camera',e.target.value);}}><option value="">Системная камера</option>{devices.map((d,i)=><option value={d.deviceId} key={d.deviceId}>{d.label||`Камера ${i+1}`}</option>)}</select></label><button className="icon-button" aria-label="Обновить камеры" onClick={()=>void refreshDevices().catch(e=>setError(cameraError(e)))}><RefreshCw size={16}/></button><button className={'control-chip '+(overlay?'enabled':'')} role="switch" aria-checked={overlay} aria-label="Показывать скелет" onClick={()=>setOverlay(!overlay)}><Hand size={16}/>Скелет</button>{status!=='off'&&<button className="camera-off" onClick={shutdown}><CameraOff size={16}/>Выключить</button>}</div>
        {error&&<div className="camera-error" role="alert">{error}</div>}
        <details className="gesture-guide" open><summary>Жесты одной рукой<ChevronDown size={16}/></summary><div className="gesture-cards">{guides.map(g=><article key={g.name}><g.icon size={22}/><h3>{g.name}</h3><p>{g.text}</p></article>)}</div><p className="gesture-stop">Кулак на 1 секунду, Esc или «Пятница, стоп» — остановить управление.</p></details>
      </div>
      <aside className="gesture-panel"><div className="gesture-panel-heading"><span className={'gesture-status-dot '+(armed?'active':'')}/><h2>{armed?'Управление включено':'Управление жестами'}</h2></div>
        <div className="gesture-modes" role="group" aria-label="Режим жестов">{(['windows','media'] as const).map(m=><button key={m} aria-pressed={mode===m} disabled={armed||arming} onClick={()=>{setMode(m);setError('');}}>{m==='windows'?<Monitor size={16}/>:<Play size={16}/>} {m==='windows'?'Окна':'Видео'}</button>)}</div>
        <label className="gesture-field">Ведущая рука<select value={leading} disabled={armed||arming} onChange={e=>setLeading(e.target.value)}><option value="Right">Правая</option><option value="Left">Левая</option></select></label>
        {mode==='windows'?<label className="gesture-field">Какое окно перемещать<select aria-label="Окно для жестов" value={hwnd} disabled={armed||arming} onChange={e=>setHwnd(Number(e.target.value))}><option value={0}>Выберите окно</option>{targets.windows.map(w=><option value={w.hwnd} key={w.hwnd}>{w.title}</option>)}</select></label>:<label className="gesture-field">Плеер<select aria-label="Плеер для жестов" value={mediaId} disabled={armed||arming} onChange={e=>setMediaId(e.target.value)}><option value="">Выберите видео или музыку</option>{targets.media.map((m,i)=><option value={m.id} key={m.id+i} disabled={m.ambiguous}>{m.title||m.id}{m.ambiguous?' — несколько сессий':''}</option>)}</select></label>}
        <button className="gesture-refresh" disabled={armed||arming} onClick={()=>void refreshTargets()}><RefreshCw size={14}/>Обновить список</button>
        {mode==='media'&&<p className="gesture-note">{targets.media_error||(!targets.media.length?'Запустите видео в браузере или плеере и обновите список.':'Перемотка доступна, если её поддерживает плеер Windows. Прямые эфиры не перематываются.')}</p>}
        {mode==='windows'&&<div className="gesture-monitors"><Monitor size={15}/>{targets.monitors.length?`Мониторы: ${targets.monitors.map(m=>m.index).join(', ')}`:'Мониторы не найдены'}</div>}
        <button className={armed?'gesture-disarm':'primary-button gesture-arm'} disabled={!armed&&(status!=='ready'||arming||(mode==='windows'?!hwnd:!mediaId))} onClick={()=>armed?disarm():void arm()}>{armed?<Square size={16}/>:<Hand size={17}/>} {armed?'Остановить управление':arming?'Подключаю…':'Включить управление'}</button>
        <div className="gesture-feedback" role="status">{lastAction||'Превью само по себе не управляет компьютером'}</div>
        <div className="gesture-tip"><span>01</span><p>Держите руку целиком в кадре, примерно в полуметре от камеры.</p></div><div className="gesture-tip"><span>02</span><p>Сначала раскройте ладонь. Между командами отпускайте жест.</p></div><div className="gesture-tip"><span>03</span><p>Вторая рука свободна. При выходе из вкладки или сворачивании камера выключается.</p></div>
      </aside>
    </div>
  </section>;
}
