import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AudioLines, ArrowUp, ArrowUpRight, Check, CheckCheck, ChevronRight, CircleHelp, Command, Copy, Cpu, Headphones, History, LayoutGrid, LoaderCircle, MessageSquare, Mic, Plus, Search, Settings2, ShieldCheck, Sparkles, Square, StickyNote, Trash2, Volume2, VolumeX, X } from 'lucide-react';
import './styles.css';
import './themes.css';
import { AppearanceSettings, themes, themeId, type ThemeId } from './AppearanceSettings';
import { MicrophoneSettings } from './MicrophoneSettings';
import { CommandLibrary } from './CommandLibrary';
import './catalog.css';
import './wake.css';
import { useWakeWord } from './useWakeWord';
import { WakeSettings, wakeLabels } from './WakeSettings';
import { Orb, type MotionMode } from './Orb';
import './refinement.css';
import { splitSpeech } from './speech';
import { VoiceSettings, PREVIEW_TEXT } from './VoiceSettings';
import { DesktopActivity, DesktopSettings, type Activity } from './DesktopControls';
import { RecognitionTest } from './RecognitionTest';
import { Camera } from 'lucide-react';
import { CameraHands } from './CameraHands';

type Message = { id: string; role: 'user' | 'assistant'; content: string; action?: string; elapsed?: number };
type Session = { id: string; title: string; created: string; count?: number };
type Note = { id: string; content: string; created: string };
type Health = {services: Record<string, string>; model: string; stt_model?:string; stt_device?: string; expressive_voice?: string};
type Phase = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'synthesizing' | 'speaking';
type Tab = 'assistant' | 'history' | 'commands' | 'notes' | 'settings' | 'camera';
type Prefs = { voice: boolean; speaker: string; speed: number; device: string; autoStop: boolean; voiceVersion?: number; theme: ThemeId; wake: boolean; motion: MotionMode };

const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.get('token')) { sessionStorage.setItem('friday-token', fragment.get('token')!); history.replaceState(null, '', location.pathname); }
const token = sessionStorage.getItem('friday-token') || '';
async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set('X-Friday-Token', token);
  if (typeof options.body === 'string') headers.set('Content-Type', 'application/json');
  const response = await fetch('/api' + path, {...options, headers});
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось выполнить запрос. Попробуйте ещё раз.');
  }
  return response;
}
const json = (path: string, options?: RequestInit) => api(path, options).then(r => r.json());
const titles: Record<Tab, string> = { assistant: 'Помощник', history: 'История разговоров', commands: 'Быстрые команды', notes: 'Мои заметки', settings: 'Настройки', camera:'Камера и жесты' };
const phaseText: Record<Phase, string> = { idle: 'Я рядом и готова помочь', listening: 'Слушаю вас…', transcribing: 'Распознаю вашу речь…', thinking: 'Думаю над ответом…', synthesizing: 'Готовлю голосовой ответ…', speaking: 'Пятница говорит…' };




function App() {
  const [tab,setTab] = useState<Tab>('assistant');
  const [settingsGroup,setSettingsGroup]=useState<'voice'|'appearance'|'system'>('voice');
  const [mode,setMode] = useState<'voice'|'chat'>('voice');
  const [messages,setMessages] = useState<Message[]>([]);
  const [activity,setActivity]=useState<Activity>({steps:[]});
  const [sessions,setSessions] = useState<Session[]>([]);
  const [notes,setNotes] = useState<Note[]>([]);
  const [sid,setSid] = useState(''); const sidRef = useRef('');
  const [input,setInput] = useState('');
  const [phase,setPhase] = useState<Phase>('idle'); const phaseRef=useRef<Phase>('idle');
  const [health,setHealth] = useState<Health|null>(null);
  const [metrics,setMetrics] = useState<{cpu:number;ram_used:number;ram_total:number}|null>(null);
  const [error,setError] = useState('');
  const [toast,setToast] = useState('');
  const [handsFree,setHandsFree] = useState(false);
  const [recognitionTesting,setRecognitionTesting]=useState(false);
  const [micTesting,setMicTesting] = useState(false);
  const [level,setLevel] = useState(0);
  const [recordSeconds,setRecordSeconds] = useState(0);
  const [search,setSearch] = useState('');
  const [deleteId,setDeleteId] = useState('');
  const [devices,setDevices] = useState<MediaDeviceInfo[]>([]);
  const [prefs,setPrefs] = useState<Prefs>(()=> {const defaults={voice:true,speaker:'xenia',speed:1,device:'',autoStop:true,theme:'neon' as ThemeId,wake:true,motion:'interactive' as MotionMode};try{const saved=JSON.parse(localStorage.getItem('friday-prefs')||'{}');return {...defaults,...saved,theme:themeId(saved.theme),motion:['interactive','ambient','still'].includes(saved.motion)?saved.motion:'interactive'};}catch{return defaults;}});
  useLayoutEffect(()=>{document.documentElement.dataset.theme=prefs.theme;document.querySelector('meta[name="theme-color"]')?.setAttribute('content',themes[prefs.theme].surface);},[prefs.theme]);
  const prefsRef = useRef(prefs); prefsRef.current=prefs;
  const rec = useRef<MediaRecorder|null>(null), media = useRef<MediaStream|null>(null), context=useRef<AudioContext|null>(null);
  const recordTimer=useRef<ReturnType<typeof setInterval>|null>(null), recordingCancelled=useRef(false);
  const abort = useRef<AbortController|null>(null), speechAbort=useRef<AbortController|null>(null);
  const requestGeneration = useRef(0);
  const audio = useRef<HTMLAudioElement|null>(null), audioURL=useRef(''), speechGeneration=useRef(0);
  const [speechElapsed,setSpeechElapsed]=useState(0);
  useEffect(()=>{
    if(!['synthesizing','speaking'].includes(phase)){setSpeechElapsed(0);return;}
    const started=Date.now();setSpeechElapsed(0);
    const timer=setInterval(()=>setSpeechElapsed(Math.floor((Date.now()-started)/1000)),1000);
    return()=>clearInterval(timer);
  },[phase]);
  const listEnd=useRef<HTMLDivElement>(null), inputEl=useRef<HTMLTextAreaElement>(null);
  const sendRef=useRef<(text:string)=>Promise<void>>(async()=>{});
  const wake=useWakeWord({enabled:prefs.wake,paused:!['idle','thinking'].includes(phase)||(handsFree&&phase!=='thinking')||micTesting||recognitionTesting||health?.services.stt!=='ready',stopOnly:phase==='thinking',onStop:stopConversation,onUncertain:(text,message)=>{setInput(text);setError(message);setTab('assistant');wake.retry();},device:prefs.device,token,onCommand:text=>{if(phaseRef.current==='idle')void sendRef.current(text);}});
  useEffect(()=>{document.title=prefs.wake?'Пятница — '+wakeLabels[wake.status]:'Пятница — персональный помощник';},[prefs.wake,wake.status]);
  const pending = ['thinking','transcribing'].includes(phase);
  const allReady=health && Object.values(health.services).every(s=>s==='ready');
  const activeSession=sessions.find(s=>s.id===sid);

  function transition(next:Phase) { phaseRef.current=next;setPhase(next); }
  function notice(message:string) {setToast(message);}
  function updatePref<K extends keyof Prefs>(key:K,value:Prefs[K]) {setPrefs(p=>({...p,[key]:value}));}
  async function refreshSessions() {setSessions(await json('/sessions'));}
  async function refreshHealth() {try{const [h,m]=await Promise.all([json('/health'),json('/system')]);setHealth(h);setMetrics(m);}catch{setHealth(null);}}
  useEffect(()=>{localStorage.setItem('friday-prefs',JSON.stringify(prefs));},[prefs]);
  useEffect(()=>{if(toast){const t=setTimeout(()=>setToast(''),3500);return()=>clearTimeout(t);}},[toast]);
  useEffect(()=>{
    refreshHealth();refreshSessions().catch(e=>setError(e.message));
    navigator.mediaDevices?.enumerateDevices().then(d=>setDevices(d.filter(x=>x.kind==='audioinput'))).catch(()=>{});
    const timer=setInterval(refreshHealth,5000);return()=>{clearInterval(timer);abort.current?.abort();speechAbort.current?.abort();media.current?.getTracks().forEach(t=>t.stop());audio.current?.pause();if(recordTimer.current)clearInterval(recordTimer.current);void context.current?.close();};
  },[]);
  useEffect(()=>{listEnd.current?.scrollIntoView({behavior:'smooth',block:'end'});},[messages,phase]);
  useEffect(()=>{if(tab==='notes')json('/notes').then(setNotes).catch(e=>setError(e.message));},[tab,messages]);
  useEffect(()=>{
    if(handsFree && phase==='idle' && tab==='assistant') {const t=setTimeout(()=>void startRecording(),650);return()=>clearTimeout(t);}
  },[handsFree,phase,tab]);

  function stopSpeech() {
    speechGeneration.current++;speechAbort.current?.abort();audio.current?.pause();audio.current=null;
    if(audioURL.current)URL.revokeObjectURL(audioURL.current);audioURL.current='';
    if(['speaking','synthesizing'].includes(phaseRef.current))transition('idle');
  }
  async function speak(text:string,preview=false) {
    wake.stop();stopSpeech();setError('');const generation=speechGeneration.current;const controller=new AbortController();speechAbort.current=controller;transition('synthesizing');
    const selected=prefsRef.current.speaker;
    const spokenText=text.replace(/[A-Za-z]:\\[^\n]+/g,'Путь к файлу показан в чате.').replace(/[\p{Extended_Pictographic}\uFE0F]/gu,'');
    const parts=selected.startsWith('qwen-')&&!preview?splitSpeech(spokenText.slice(0,5000)):[spokenText.slice(0,5000)];
    const prepare=async(part:string):Promise<{blob:Blob}|{error:Error}>=>{
      try{const response=await api('/speech',{method:'POST',body:JSON.stringify({text:part,speaker:selected,preview}),signal:AbortSignal.any([controller.signal,AbortSignal.timeout(155000)])});return {blob:await response.blob()};}
      catch(e){return {error:(e as Error).name==='TimeoutError'?new Error('Голос не ответил вовремя. Повторите попытку или выберите быстрый голос.'):e as Error};}
    };
    try {
      let next=prepare(parts[0]||text);
      for(let i=0;i<parts.length;i++){
        const prepared=await next;if(generation!==speechGeneration.current)return;if('error' in prepared)throw prepared.error;
        if(i+1<parts.length)next=prepare(parts[i+1]);
        const url=URL.createObjectURL(prepared.blob);audioURL.current=url;const player=new Audio(url);audio.current=player;player.playbackRate=prefsRef.current.speed;
        await new Promise<void>((resolve,reject)=>{
          const timer=setTimeout(()=>finish(new Error('Воспроизведение прервалось. Проверьте устройство вывода.')),180000);
          const finish=(err?:Error)=>{clearTimeout(timer);player.pause();controller.signal.removeEventListener('abort',cancel);player.onended=null;player.onerror=null;URL.revokeObjectURL(url);if(audioURL.current===url)audioURL.current='';err?reject(err):resolve();};
          const cancel=()=>{player.pause();finish(new DOMException('Stopped','AbortError'));};
          controller.signal.addEventListener('abort',cancel,{once:true});
          player.onended=()=>finish();player.onerror=()=>finish(new Error('Не удалось воспроизвести голос. Проверьте устройство вывода.'));
          player.play().then(()=>{if(generation===speechGeneration.current)transition('speaking');}).catch(finish);
        });
        if(generation!==speechGeneration.current)return;
        if(i+1<parts.length)transition('synthesizing');
      }
      if(generation===speechGeneration.current){audio.current=null;transition('idle');}
    }catch(e){if(generation===speechGeneration.current){if((e as Error).name!=='AbortError'){setError((e as Error).message);setHandsFree(false);}transition('idle');}}
  }

  async function send(text:string) {
    if(/^(?:пятница[, ]+)?(?:стоп|остановись)[.! ]*$/i.test(text.trim())){stopConversation();return;}
    if(!text.trim() || ['thinking','transcribing','listening'].includes(phaseRef.current))return;
    wake.stop();stopSpeech();setError('');setInput('');setActivity({steps:[]});setTab('assistant');transition('thinking');
    const generation=++requestGeneration.current;
    const controller=new AbortController();abort.current=controller;
    let answer='',assistantId=crypto.randomUUID();
    try {
      let sessionId=sidRef.current;
      if(!sessionId){const session=await json('/sessions',{method:'POST',signal:controller.signal});if(generation!==requestGeneration.current)return;sessionId=session.id;sidRef.current=sessionId;setSid(sessionId);}
      setMessages(m=>[...m,{id:crypto.randomUUID(),role:'user',content:text},{id:assistantId,role:'assistant',content:''}]);
      const response=await api('/chat',{method:'POST',body:JSON.stringify({session_id:sessionId,text}),signal:controller.signal});
      const reader=response.body!.getReader(), decoder=new TextDecoder();let buffer='';
      while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value,{stream:!done});const lines=buffer.split('\n');buffer=lines.pop()||'';
        for(const line of lines){if(generation!==requestGeneration.current)return;if(!line.trim())continue;const event=JSON.parse(line);
          if(event.type==='error')throw new Error(event.message);
          if(event.type==='agent_plan')setActivity({steps:event.steps.map((label:string)=>({label,status:'waiting'}))});
          if(event.type==='agent_step')setActivity(a=>({...a,steps:a.steps.map((s,i)=>i===event.index?{...s,status:event.status,evidence:event.evidence}:s)}));
          if(event.type==='approval')setActivity(a=>({...a,approval:event}));
          if(event.type==='approval_closed')setActivity(a=>({...a,approval:undefined}));
          if(event.type==='agent_observation')setActivity(a=>({...a,notice:event.text}));
          if(event.type==='agent_stopped')setActivity(a=>({...a,approval:undefined,notice:event.message,steps:a.steps.map(s=>s.status==='done'?s:{...s,status:'stopped'})}));
          if(event.type==='delta'){answer+=event.text;setMessages(m=>m.map(x=>x.id===assistantId?{...x,content:answer}:x));}
          if(event.type==='action')setMessages(m=>m.map(x=>x.id===assistantId?{...x,action:event.label}:x));
          if(event.type==='done')setMessages(m=>m.map(x=>x.id===assistantId?{...x,elapsed:event.elapsed}:x));
        }
        if(done)break;
      }
      if(generation!==requestGeneration.current)return;
      void refreshSessions();
      if(answer && prefsRef.current.voice && !controller.signal.aborted)await speak(answer);else transition('idle');
    }catch(e){
      if(generation!==requestGeneration.current)return;
      if((e as Error).name!=='AbortError'){setError((e as Error).message);setHandsFree(false);}
      setMessages(m=>m.filter(x=>x.id!==assistantId||x.content));transition('idle');void refreshSessions();
    }
  }
  sendRef.current=send;

  function cleanupRecording() {
    if(recordTimer.current)clearInterval(recordTimer.current);recordTimer.current=null;
    media.current?.getTracks().forEach(t=>t.stop());media.current=null;
    if(context.current){void context.current.close();context.current=null;}setLevel(0);
  }
  function stopRecording(cancel=false) {
    if (!rec.current) { recordingCancelled.current=true; cleanupRecording(); setHandsFree(false); transition('idle'); return; }
    recordingCancelled.current=cancel;if(cancel)setHandsFree(false);
    if(rec.current?.state==='recording')rec.current.stop();
    cleanupRecording();
  }
  async function startRecording() {
    if(['thinking','transcribing','listening'].includes(phaseRef.current))return;
    if(health?.services.stt!=='ready'){setError('Распознавание речи ещё загружается.');setHandsFree(false);return;}
    wake.stop();stopSpeech();setError('');transition('listening');setRecordSeconds(0);recordingCancelled.current=false;
    try {
      const stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:prefsRef.current.device?{exact:prefsRef.current.device}:undefined,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
      if(recordingCancelled.current||phaseRef.current!=='listening'){stream.getTracks().forEach(t=>t.stop());return;}
      media.current=stream;const mime=MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':'audio/webm';
      const recorder=new MediaRecorder(stream,{mimeType:mime,audioBitsPerSecond:128000});rec.current=recorder;const chunks:BlobPart[]=[];
      recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      recorder.onstop=async()=>{
        cleanupRecording();rec.current=null;
        if(recordingCancelled.current){transition('idle');return;}
        transition('transcribing');const generation=++requestGeneration.current;const form=new FormData();form.append('audio',new Blob(chunks,{type:mime}),'command.webm');
        const controller=new AbortController();abort.current=controller;
        try{const result=await json('/transcribe',{method:'POST',body:form,signal:controller.signal});if(generation!==requestGeneration.current)return;transition('idle');
          if(result.text&&result.uncertain){setInput(result.text);setHandsFree(false);setError('Распознано неуверенно. Проверьте текст и нажмите «Отправить».');}
          else if(result.text)await sendRef.current(result.text);else{setHandsFree(false);setError(result.warning||'Не расслышала речь. Подойдите ближе к микрофону и попробуйте ещё раз.');}
        }catch(e){if(generation!==requestGeneration.current)return;if((e as Error).name!=='AbortError')setError((e as Error).message);setHandsFree(false);transition('idle');}
      };
      recorder.onerror=()=>{recordingCancelled.current=true;cleanupRecording();setHandsFree(false);setError('Запись прервалась. Проверьте подключение микрофона.');transition('idle');};
      recorder.start(250);
      const ac=new AudioContext();context.current=ac;const analyser=ac.createAnalyser();analyser.fftSize=2048;ac.createMediaStreamSource(stream).connect(analyser);const values=new Float32Array(analyser.fftSize);
      const started=Date.now();let lastSpeech=started,heard=false;
      recordTimer.current=setInterval(()=>{
        analyser.getFloatTimeDomainData(values);const rms=Math.sqrt(values.reduce((s,x)=>s+x*x,0)/values.length);setLevel(Math.min(1,rms*9));
        const elapsed=(Date.now()-started)/1000;setRecordSeconds(Math.floor(elapsed));
        if(rms>.008){lastSpeech=Date.now();heard=true;}
        if(elapsed>=120||(prefsRef.current.autoStop&&heard&&elapsed>2&&Date.now()-lastSpeech>2000))stopRecording();
        else if(!heard&&elapsed>20){stopRecording(true);setError('Не слышу микрофон. Проверьте устройство в настройках.');}
      },80);
      navigator.mediaDevices.enumerateDevices().then(d=>setDevices(d.filter(x=>x.kind==='audioinput'))).catch(()=>{});
    }catch(e){cleanupRecording();transition('idle');setHandsFree(false);const name=(e as Error).name;setError(name==='NotAllowedError'?'Разрешите Пятнице доступ к микрофону в настройках конфиденциальности Windows.':name==='NotFoundError'?'Микрофон не найден. Подключите его и повторите.':'Не удалось включить микрофон. Проверьте выбранное устройство.');}
  }
  function stopAll() {wake.stop();updatePref('wake',false);stopConversation();}
  function stopConversation() {void json('/desktop/stop',{method:'POST'}).catch(()=>{});setActivity(a=>({...a,approval:undefined,steps:a.steps.map(s=>s.status==='done'?s:{...s,status:'stopped'})}));wake.stop();wake.retry();requestGeneration.current++;setHandsFree(false);abort.current?.abort();stopSpeech();if(phaseRef.current==='listening')stopRecording(true);setMessages(m=>m.filter(x=>x.role!=='assistant'||x.content));transition('idle');}
  async function newChat(){if(pending||phase==='listening')return;stopConversation();sidRef.current='';setSid('');setMessages([]);setInput('');setError('');setTab('assistant');}
  async function openSession(session:Session){if(pending||phase==='listening')return;stopConversation();try{const data=await json('/sessions/'+session.id);sidRef.current=session.id;setSid(session.id);setMessages(data.messages);setTab('assistant');setError('');}catch(e){setError((e as Error).message);}}
  async function removeSession(id:string){try{await json('/sessions/'+id,{method:'DELETE'});setDeleteId('');if(sid===id){sidRef.current='';setSid('');setMessages([]);}await refreshSessions();}catch(e){setError((e as Error).message);}}
  async function copy(text:string){try{await navigator.clipboard.writeText(text);notice('Скопировано');}catch{setError('Не удалось скопировать текст');}}
  useEffect(()=>{const key=(e:KeyboardEvent)=>{if(e.key==='Escape')stopAll();if(e.ctrlKey&&e.code==='Space'){e.preventDefault();if(phaseRef.current==='listening')stopRecording();else void startRecording();}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);});

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e=>{e.preventDefault();setTab('assistant');}}><span className="brand-mark"><img src="/friday.svg" alt="" width="40" height="40"/></span><span>пятница<span className="brand-dot">.</span></span></a>
      <button className="new-chat" onClick={newChat} disabled={pending||phase==='listening'}><Plus size={17}/>Новый разговор<span>↗</span></button>
      
      <nav>{([{id:'assistant',icon:AudioLines},{id:'camera',icon:Camera},{id:'history',icon:History},{id:'commands',icon:Command},{id:'notes',icon:StickyNote}] as const).map(item=><button key={item.id} aria-current={tab===item.id?'page':undefined} className={'nav-item '+(tab===item.id?'selected':'')} onClick={()=>{setTab(item.id);setSearch('');}}><item.icon size={18}/><span>{item.id==='history'?'История':item.id==='commands'?'Команды':titles[item.id]}</span>{tab===item.id&&<span className="nav-active"/>}</button>)}</nav>
      <div className="recent-heading"><span className="nav-label">НЕДАВНИЕ РАЗГОВОРЫ</span><History size={13}/></div>
      <div className="recent-list">{sessions.filter(s=>s.count).slice(0,4).map(s=><button key={s.id} onClick={()=>openSession(s)} disabled={pending||phase==='listening'}><MessageSquare size={14}/><span>{s.title}</span></button>)}{!sessions.some(s=>s.count)&&<p>Пока нет разговоров</p>}</div>
      <div className="sidebar-bottom"><button aria-current={tab==='settings'?'page':undefined} className={'nav-item '+(tab==='settings'?'selected':'')} onClick={()=>setTab('settings')}><Settings2 size={18}/><span>Настройки</span></button>
      <div className="sidebar-local"><ShieldCheck size={14}/><span>Голос обрабатывается локально</span></div></div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="breadcrumb">{tab==='assistant'?<strong>{titles[tab]}</strong>:<button className="back-to-chat" onClick={()=>setTab('assistant')}><ChevronRight size={14}/><span>К разговору</span></button>}</div><div className="topbar-status">{prefs.wake&&<span className={'wake-badge '+wake.status}><Mic size={13}/>{wakeLabels[wake.status]}<button aria-label="Выключить голосовую активацию" onClick={()=>{wake.stop();updatePref('wake',false);}}><X size={12}/></button></span>}{(!prefs.wake||!allReady)&&<span className="connection-status"><span className={'status-dot '+(allReady?'':'waiting')}/>{allReady?'Готова к работе':health?'Загрузка моделей…':'Подключение…'}</span>}</div></header>
      <main className={tab==='assistant'?'assistant-page':'standard-page'}>
        {tab==='assistant'?<>
          <div className="assistant-main">
            <div className="page-heading"><h1>{messages.length?'Наш разговор':'Чем могу помочь?'}</h1></div>
            <div className="mode-bar"><div className="segmented"><button className={mode==='voice'?'active':''} onClick={()=>setMode('voice')}><AudioLines size={15}/>С ядром</button><button className={mode==='chat'?'active':''} onClick={()=>setMode('chat')}><MessageSquare size={14}/>Только чат</button></div></div>
            <div className={'conversation '+(messages.length?'has-messages':'')+' '+(mode==='chat'?'chat-mode':'')}>
              {mode==='voice'&&<div className={'voice-stage '+(messages.length?'compact':'')}>
                
                <Orb motion={prefs.motion} onMotion={value=>updatePref('motion',value)} theme={prefs.theme} active={phase!=='idle'||wake.status==='listening'} level={level}/>
                {phase!=='idle'&&<div className="core-status" role="status"><span className={'status-dot '+(phase==='listening'?'pulsing':'')}/>{phaseText[phase]}{phase==='synthesizing'&&` · ${speechElapsed} с`}</div>}
                <div className="core-subtitle">{phase==='listening'?`Запись ${Math.floor(recordSeconds/60)}:${String(recordSeconds%60).padStart(2,'0')} · нажмите ещё раз, чтобы отправить`:phase==='idle'?'Напишите сообщение или нажмите на микрофон':'Esc — остановить'}</div>
                {phase==='listening'&&<div className="live-wave" aria-label="Уровень микрофона">{Array.from({length:25},(_,i)=><i key={i} style={{height:4+level*(12+Math.sin(i*1.5)**2*28)}}/>)}</div>}
              </div>}
              {messages.length>0?<div className="messages">{messages.map(m=><div key={m.id} className={'message '+m.role}><div className="message-avatar">{m.role==='assistant'?<AudioLines size={17}/>:<span>Вы</span>}</div><div className="message-body"><div className="message-meta">{m.role==='assistant'?'Пятница':'Вы'}{m.elapsed!==undefined&&<small>{m.elapsed.toFixed(1)} с</small>}</div>{m.action&&<div className="action-badge"><CheckCheck size={13}/>{m.action}</div>}<div className="message-text">{m.content||<span className="typing"><i/><i/><i/></span>}</div>{m.role==='assistant'&&m.content&&<div className="message-actions"><button title="Озвучить ответ" aria-label="Озвучить ответ" disabled={pending||phase==='listening'} onClick={()=>speak(m.content)}><Volume2 size={14}/></button><button title="Скопировать ответ" aria-label="Скопировать ответ" onClick={()=>copy(m.content)}><Copy size={13}/></button></div>}</div></div>)}<div ref={listEnd}/></div>:<div className="suggestions"><div className="suggestion-grid"><button onClick={()=>send('Привет, Пятница! Расскажи, что ты умеешь.')} disabled={pending}><Sparkles size={17}/><strong>Что ты умеешь?</strong></button><button onClick={()=>send('Помоги составить простой план продуктивного дня.')} disabled={pending}><LayoutGrid size={17}/><strong>План на день</strong></button><button onClick={()=>{setInput('Запиши заметку: ');inputEl.current?.focus();}}><StickyNote size={17}/><strong>Записать заметку</strong></button></div></div>}
            </div>
            <div className="composer-area">
              <DesktopActivity value={activity} onStop={stopConversation} onApprove={async(nonce,allow)=>{await json('/desktop/approve',{method:'POST',body:JSON.stringify({nonce,allow})});setActivity(a=>({...a,approval:undefined}));}}/>
              {error&&<div className="error-banner" role="alert"><CircleHelp size={17}/><span>{error}</span><button aria-label="Закрыть ошибку" onClick={()=>setError('')}><X size={15}/></button></div>}
              <div className={'composer '+(phase==='listening'?'recording':'')}><textarea ref={inputEl} rows={1} maxLength={8000} value={input} onChange={e=>setInput(e.target.value)} placeholder={phase==='listening'?'Я слушаю. Говорите…':'Сообщение или команда…'} aria-label="Сообщение Пятнице" disabled={phase==='listening'} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();void send(input);}}}/><span className="composer-divider"/><button className={'mic-button '+(phase==='listening'?'is-recording':'')} aria-label={phase==='listening'?'Закончить запись':'Начать запись'} title="Микрофон · Ctrl+Пробел" disabled={pending} onClick={()=>phase==='listening'?stopRecording():startRecording()}>{phase==='listening'?<Square size={17} fill="currentColor"/>:<Mic size={19}/>}</button>{pending||['speaking','synthesizing'].includes(phase)?<button className="send-button stop" title="Остановить" aria-label="Остановить" onClick={stopAll}><Square size={15} fill="currentColor"/></button>:<button className="send-button" aria-label="Отправить" disabled={!input.trim()||phase==='listening'} onClick={()=>send(input)}><ArrowUp size={20}/></button>}</div>
              <div className="composer-footer"><div className="conversation-controls"><button className={'control-chip '+(prefs.voice?'enabled':'')} role="switch" aria-label="Голосовые ответы" aria-checked={prefs.voice} onClick={()=>{updatePref('voice',!prefs.voice);if(prefs.voice)stopSpeech();}}>{prefs.voice?<Volume2 size={15}/>:<VolumeX size={15}/>}Озвучка</button><button className={'control-chip '+(handsFree?'enabled':'')} role="switch" aria-label="Свободный разговор" aria-checked={handsFree} title="Микрофон включается после каждого ответа" onClick={()=>{if(handsFree)stopConversation();else setHandsFree(true);}}><Headphones size={15}/>Свободный разговор</button></div><span className="composer-shortcut">Ctrl + пробел — микрофон</span></div>
            </div>
          </div>
          
        </>:<>
          <div className="page-heading"><h1>{titles[tab]}</h1>{tab==='commands'&&<p>Найдите действие и нажмите «Выполнить».</p>}</div>
          {tab==='camera'&&<CameraHands api={json}/>}
          {error&&<div className="error-banner" role="alert"><CircleHelp size={17}/><span>{error}</span><button aria-label="Закрыть ошибку" onClick={()=>setError('')}><X size={15}/></button></div>}
          {tab==='history'&&<><div className="search-field"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Найти разговор…" aria-label="Поиск разговоров"/></div><div className="history-list">{sessions.filter(s=>s.count&&s.title.toLowerCase().includes(search.toLowerCase())).map(s=><div className="history-row" key={s.id}><button className="history-open" onClick={()=>openSession(s)} disabled={pending||phase==='listening'}><span className="history-icon"><MessageSquare size={19}/></span><div><strong>{s.title}</strong><span>{new Date(s.created).toLocaleString('ru-RU',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'})} · {s.count} сообщ.</span></div><ArrowUpRight size={18}/></button>{deleteId===s.id?<div className="delete-confirm"><span>Удалить разговор?</span><button onClick={()=>removeSession(s.id)}>Удалить</button><button onClick={()=>setDeleteId('')} aria-label="Отмена"><X size={15}/></button></div>:<button className="icon-button" aria-label="Удалить разговор" disabled={pending||phase==='listening'} onClick={()=>setDeleteId(s.id)}><Trash2 size={16}/></button>}</div>)}</div>{!sessions.some(s=>s.count&&s.title.toLowerCase().includes(search.toLowerCase()))&&<div className="empty-state"><History size={35}/><h2>{search?'Ничего не найдено':'Пока нет разговоров'}</h2><p>{search?'Попробуйте другое название.':'Начните разговор — он автоматически сохранится здесь.'}</p><button className="primary-button" onClick={newChat}><Plus size={16}/>Новый разговор</button></div>}</>}
          {tab==='commands'&&<CommandLibrary disabled={pending||phase==='listening'} onRun={send} onInsert={text=>{setInput(text);setTab('assistant');setTimeout(()=>inputEl.current?.focus(),50);}}/>}
          {tab==='notes'&&<><div className="info-strip"><Mic size={19}/><div><strong>Новая заметка</strong></div><button className="primary-button" onClick={()=>{setTab('assistant');setInput('Запиши заметку: ');setTimeout(()=>inputEl.current?.focus(),50);}}><Plus size={15}/>Создать</button></div><div className="notes-grid">{notes.map(n=><article className="note-card" key={n.id}><StickyNote size={18}/><p>{n.content}</p><footer><span>{new Date(n.created).toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}</span><button aria-label="Скопировать заметку" onClick={()=>copy(n.content)}><Copy size={14}/></button></footer></article>)}</div>{!notes.length&&<div className="empty-state"><StickyNote size={35}/><h2>Пока нет заметок</h2><p>Нажмите «Создать», чтобы сохранить мысль.</p></div>}</>}
          {tab==='settings'&&<><div className="settings-navigation" role="tablist" aria-label="Раздел настроек">{([{id:'voice',label:'Голос и микрофон'},{id:'appearance',label:'Оформление'},{id:'system',label:'Система'}] as const).map(group=><button key={group.id} role="tab" id={'settings-tab-'+group.id} aria-controls={'settings-panel-'+group.id} aria-selected={settingsGroup===group.id} tabIndex={settingsGroup===group.id?0:-1} onKeyDown={event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]'));const index=tabs.indexOf(event.currentTarget);const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();tabs[next].click();}} onClick={()=>setSettingsGroup(group.id)}>{group.label}</button>)}</div><div className="settings-layout" role="tabpanel" id={'settings-panel-'+settingsGroup} aria-labelledby={'settings-tab-'+settingsGroup}>{settingsGroup==='appearance'&&<AppearanceSettings motion={prefs.motion} onMotion={value=>updatePref('motion',value)} value={prefs.theme} onChange={value=>updatePref('theme',value)}/>}{settingsGroup==='voice'&&<div className="voice-settings-group"><VoiceSettings speaker={prefs.speaker} voice={prefs.voice} speed={prefs.speed} phase={phase} elapsed={speechElapsed} modelStatus={health?.expressive_voice} onSpeaker={value=>{stopSpeech();updatePref('speaker',value);}} onVoice={()=>{updatePref('voice',!prefs.voice);if(prefs.voice)stopSpeech();}} onSpeed={value=>updatePref('speed',value)} onPreview={()=>speak(PREVIEW_TEXT,true)} onStop={stopSpeech} disabled={pending||phase==='listening'||(!prefs.speaker.startsWith('qwen-')&&health?.services.tts!=='ready')}/><RecognitionTest api={json} device={prefs.device} onTestingChange={setRecognitionTesting} disabled={pending||phase==='listening'||micTesting||health?.services.stt!=='ready'}/><MicrophoneSettings onTestingChange={setMicTesting} device={prefs.device} onChange={value=>updatePref('device',value)} autoStop={prefs.autoStop} onAutoStop={()=>updatePref('autoStop',!prefs.autoStop)} disabled={pending||phase==='listening'||recognitionTesting}/><WakeSettings enabled={prefs.wake} onChange={value=>{wake.stop();setHandsFree(false);updatePref('wake',value);}} status={wake.status} error={wake.error} retry={wake.retry}/>
          
          </div>}{settingsGroup==='system'&&<><DesktopSettings api={json}/><section className="settings-card models-card"><div className="settings-card-heading"><Cpu size={20}/><div><h2>Локальные модели</h2><p>Интернет для работы не требуется</p></div><button className="icon-button" aria-label="Обновить состояние моделей" onClick={async()=>{try{await json('/retry',{method:'POST'});await refreshHealth();}catch(e){setError((e as Error).message);}}}><History size={17}/></button></div>{[{id:'llm',name:health?.model||'Qwen 3.5 4B',desc:'Диалог, понимание команд и изображений · Ollama'},{id:'stt',name:health?.stt_model||'Whisper Large v3 Turbo',desc:health?.stt_device==='cuda'?'Распознавание русской речи · NVIDIA GPU':'Распознавание русской речи · CPU INT8'},{id:'tts',name:prefs.speaker.startsWith('qwen-')?'Qwen3-TTS 0.6B':'Silero v4 RU',desc:prefs.speaker.startsWith('qwen-')?'Выразительная речь · NVIDIA GPU · загрузка при первом ответе':'Быстрый русский голос · CPU'}].map(m=><div className="settings-row" key={m.id}><div><strong>{m.name}</strong><p>{m.desc}</p></div><span className={'model-status '+(health?.services[m.id]==='ready'?'ready':'')}>{health?.services[m.id]==='ready'?<Check size={14}/>:<LoaderCircle size={14}/>} {m.id==='tts'&&prefs.speaker.startsWith('qwen-')?(health?.expressive_voice==='ready'?'Готова':health?.expressive_voice==='synthesizing'?'Создаёт запись':health?.expressive_voice==='loading'?'Загружается':'Установлена'):health?.services[m.id]==='ready'?'Готова':health?.services[m.id]==='error'?'Ошибка загрузки':'Загружается'}</span></div>)}<div className="hardware-stats"><span>CPU <strong>{metrics?metrics.cpu.toFixed(0)+'%':'—'}</strong></span><span>ПАМЯТЬ <strong>{metrics?`${metrics.ram_used} / ${metrics.ram_total} ГБ`:'—'}</strong></span></div></section></>}</div></>}
        </>}
      </main>
    </div>
    {toast&&<div className="toast" role="status"><Check size={16}/>{toast}</div>}
    {tab!=='assistant'&&phase!=='idle'&&<div className="floating-status"><AudioLines size={18}/><span>{phaseText[phase]}</span><button onClick={()=>setTab('assistant')}>К разговору<ArrowUpRight size={14}/></button><button aria-label="Остановить" onClick={stopAll}><Square size={14}/></button></div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
