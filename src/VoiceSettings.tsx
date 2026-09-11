import { LoaderCircle, Square, Volume2 } from 'lucide-react';
export const PREVIEW_TEXT='Привет! Я Пятница. Чем могу помочь?';
export function VoiceSettings({speaker,voice,speed,phase,elapsed,modelStatus,onSpeaker,onVoice,onSpeed,onPreview,onStop,disabled}:{
  speaker:string;voice:boolean;speed:number;phase:string;elapsed:number;modelStatus?:string;
  onSpeaker:(value:string)=>void;onVoice:()=>void;onSpeed:(value:number)=>void;onPreview:()=>void;onStop:()=>void;disabled:boolean;
}){
  const busy=phase==='synthesizing'||phase==='speaking';
  return <section className="settings-card voice-card"><div className="settings-card-heading"><Volume2 size={20}/><h2>Голос Пятницы</h2></div>
    <div className="settings-row"><div><strong>Озвучивать ответы</strong><p>{voice?'Пятница отвечает текстом и голосом':'Выключено — ответы на команды будут только текстом'}</p></div><button className={'toggle '+(voice?'on':'')} role="switch" aria-checked={voice} aria-label="Озвучивать ответы" onClick={onVoice}><span/></button></div>
    <div className="settings-row"><div><strong>Тембр голоса</strong><p>{speaker.startsWith('qwen-')?'Qwen3-TTS · выразительный голос':'Silero · быстрые ответы · 48 кГц'}</p></div><select aria-label="Тембр голоса" value={speaker} onChange={e=>onSpeaker(e.target.value)}><optgroup label="Выразительные · Qwen3-TTS"><option value="qwen-serena">Серена — тёплый</option><option value="qwen-sohee">Сохи — эмоциональный</option><option value="qwen-anna">Анна — лёгкий</option></optgroup><optgroup label="Быстрые · Silero"><option value="xenia">Ксения</option><option value="baya">Бая</option><option value="kseniya">Ксения II</option></optgroup></select></div>
    {speaker.startsWith('qwen-')&&<p className="mic-hint">Первый голосовой ответ требует загрузки модели. Образец можно послушать сразу.</p>}
    <div className="settings-row"><div><strong>Скорость речи</strong><p>{speed.toFixed(1)}× · {speed===1?'Естественный темп':speed>1?'Быстрее обычного':'Медленнее обычного'}</p></div><input aria-label="Скорость речи" type="range" min="0.8" max="1.3" step="0.1" value={speed} onChange={e=>onSpeed(Number(e.target.value))}/></div>
    <button className="outline-button" disabled={disabled||busy} onClick={onPreview}>{phase==='synthesizing'?<LoaderCircle size={16}/>:<Volume2 size={16}/>}Послушать голос</button>
    {busy&&<><button className="outline-button" onClick={onStop}><Square size={14}/>Остановить</button><p role="status" className="mic-hint voice-progress">{phase==='speaking'?'Воспроизведение голоса':modelStatus==='loading'?'Загружаю голосовую модель…':'Создаю голосовую запись…'} · {elapsed} с</p></>}
  </section>;
}
