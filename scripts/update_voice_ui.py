from pathlib import Path
p=Path('src/main.tsx');s=p.read_text(encoding='utf-8-sig')
s=s.replace("import { commands } from './commandCatalog';", "import { commands } from './commandCatalog';\nimport { splitSpeech } from './speech';")
s=s.replace('autoStop: boolean };','autoStop: boolean; voiceVersion?: number };')
s=s.replace("const [prefs,setPrefs] = useState<Prefs>(()=> {try{return {voice:true,speaker:'xenia',speed:1,device:'',autoStop:true,...JSON.parse(localStorage.getItem('friday-prefs')||'{}')}}catch{return {voice:true,speaker:'xenia',speed:1,device:'',autoStop:true}}});", "const [prefs,setPrefs] = useState<Prefs>(()=> {const defaults={voice:true,speaker:'qwen-serena',speed:1,device:'',autoStop:true,voiceVersion:2};try{const saved=JSON.parse(localStorage.getItem('friday-prefs')||'{}');return {...defaults,...saved,...(saved.voiceVersion===2?{}:{speaker:'qwen-serena',voiceVersion:2})};}catch{return defaults;}});")
start=s.index('  async function speak(text:string) {')
end=s.index('\n  async function send(text:string)',start)
s=s[:start]+'''  async function speak(text:string) {
    stopSpeech();const generation=speechGeneration.current;const controller=new AbortController();speechAbort.current=controller;transition('synthesizing');
    const selected=prefsRef.current.speaker;
    const parts=selected.startsWith('qwen-')?splitSpeech(text.slice(0,5000)):[text.slice(0,5000)];
    const prepare=async(part:string):Promise<{blob:Blob}|{error:Error}>=>{
      try{const response=await api('/speech',{method:'POST',body:JSON.stringify({text:part,speaker:selected}),signal:controller.signal});return {blob:await response.blob()};}
      catch(e){return {error:e as Error};}
    };
    try {
      let next=prepare(parts[0]||text);
      for(let i=0;i<parts.length;i++){
        const prepared=await next;if(generation!==speechGeneration.current)return;if('error' in prepared)throw prepared.error;
        if(i+1<parts.length)next=prepare(parts[i+1]);
        const url=URL.createObjectURL(prepared.blob);audioURL.current=url;const player=new Audio(url);audio.current=player;player.playbackRate=prefsRef.current.speed;
        await new Promise<void>((resolve,reject)=>{
          const finish=(err?:Error)=>{controller.signal.removeEventListener('abort',cancel);player.onended=null;player.onerror=null;URL.revokeObjectURL(url);if(audioURL.current===url)audioURL.current='';err?reject(err):resolve();};
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
''' + s[end:]
s=s.replace('<option value="xenia">Ксения — основной</option><option value="baya">Бая — мягкий</option><option value="kseniya">Ксения II — спокойный</option>', '<optgroup label="Выразительные · Qwen3-TTS"><option value="qwen-serena">Серена — тёплый</option><option value="qwen-sohee">Сохи — эмоциональный</option><option value="qwen-anna">Анна — лёгкий</option></optgroup><optgroup label="Быстрые · Silero"><option value="xenia">Ксения</option><option value="baya">Бая</option><option value="kseniya">Ксения II</option></optgroup>')
s=s.replace('<p>Silero TTS · 48 кГц</p>', '<p>{prefs.speaker.startsWith(\'qwen-\')?\'Qwen3-TTS · выразительнее, требует больше времени\':\'Silero · быстрые ответы · 48 кГц\'}</p>')
s=s.replace("value:'Silero · '+({xenia:'Ксения',baya:'Бая',kseniya:'Ксения II'}[prefs.speaker]||'Ксения')", "value:({'qwen-serena':'Qwen · Серена','qwen-sohee':'Qwen · Сохи','qwen-anna':'Qwen · Анна',xenia:'Silero · Ксения',baya:'Silero · Бая',kseniya:'Silero · Ксения II'}[prefs.speaker]||'Qwen · Серена')")
s=s.replace("{id:'tts',name:'Silero v4 RU',desc:'Женский русский голос · CPU'}", "{id:'tts',name:prefs.speaker.startsWith('qwen-')?'Qwen3-TTS 0.6B':'Silero v4 RU',desc:prefs.speaker.startsWith('qwen-')?'Выразительная речь · NVIDIA GPU · загрузка при первом ответе':'Быстрый русский голос · CPU'}")
s=s.replace('V 1.0','V 1.1')
p.write_text(s,encoding='utf-8')

p=Path('backend/app.py');s=p.read_text(encoding='utf-8')
start=s.index("SYSTEM_PROMPT = '''")
end=s.index("'''",start+19)+3
s=s[:start]+"""SYSTEM_PROMPT = '''Ты Пятница — личная голосовая помощница пользователя. Говори о себе в женском роде. Отвечай по-русски, дружелюбно, естественно и кратко: обычно 2–4 предложения. Твои ответы озвучиваются: избегай эмодзи, markdown, таблиц и специальных символов. Приложение умеет открывать установленные программы (название из меню Пуск), браузер, сайты, проводник и стандартные папки; менять громкость и звук; управлять воспроизведением музыки; сворачивать и восстанавливать окна; сохранять скриншоты; искать файлы по названию на рабочем столе, в документах и загрузках; создавать папки на рабочем столе; сохранять заметки; сообщать время, дату, состояние системы и место на диске. Примеры: «Пятница, можешь открыть проводник», «Открой Telegram», «Установи громкость на 50 процентов», «Поставь музыку на паузу», «Сделай скриншот», «Найди файл отчёт», «Создай папку на рабочем столе Проекты», «Запиши заметку: текст». Эти команды исполняет отдельный обработчик. Если ты отвечаешь на сообщение, обработчик ещё не выполнил действие. Никогда не утверждай, что что-то открыла, сохранила или изменила, если это не подтверждено. Если пользователь просит действие, предложи точную короткую команду из поддерживаемых. Ты не исполняешь произвольный код, не удаляешь файлы, не отправляешь сообщения и не видишь экран. Поиск в интернете открывает браузер, но ты не читаешь результаты. Текущая дата: '''"""+s[end:]
p.write_text(s,encoding='utf-8')
