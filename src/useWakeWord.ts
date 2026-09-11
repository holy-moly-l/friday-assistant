import { useCallback, useEffect, useRef, useState } from 'react';
export type WakeStatus='off'|'paused'|'starting'|'waiting'|'listening'|'transcribing'|'error';
type Options={enabled:boolean;paused:boolean;device:string;token:string;stopOnly?:boolean;onStop?:()=>void;onUncertain?:(text:string,message:string)=>void;onCommand:(text:string)=>void};
export function useWakeWord({enabled,paused,device,token,onCommand,stopOnly=false,onStop,onUncertain}:Options){
  const [status,setStatus]=useState<WakeStatus>('off'),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
  const callback=useRef(onCommand);callback.current=onCommand;
  const stopCallback=useRef(onStop);stopCallback.current=onStop;
  const uncertainCallback=useRef(onUncertain);uncertainCallback.current=onUncertain;
  const generation=useRef(0),resources=useRef<{stream?:MediaStream;ctx?:AudioContext;node?:AudioWorkletNode;socket?:WebSocket}>({});
  const stop=useCallback(()=>{
    generation.current++;
    const r=resources.current;resources.current={};
    if(r.node){r.node.port.onmessage=null;r.node.disconnect();}
    r.stream?.getTracks().forEach(t=>t.stop());
    if(r.ctx)void r.ctx.close().catch(()=>{});
    if(r.socket){r.socket.onclose=null;r.socket.onerror=null;r.socket.onmessage=null;r.socket.close();}
  },[]);
  useEffect(()=>{
    stop();setError('');
    if(!enabled||paused){setStatus(enabled?'paused':'off');return;}
    setStatus('starting');const current=generation.current;
    const alive=()=>current===generation.current;
    const fail=(message:string)=>{if(alive()){stop();setError(message);setStatus('error');}};
    // Allow the last TTS audio to finish ringing before listening again.
    const timer=setTimeout(()=>{void (async()=>{
      try{
        const stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:device?{exact:device}:undefined,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
        if(!alive()){stream.getTracks().forEach(t=>t.stop());return;}
        resources.current.stream=stream;
        stream.getAudioTracks().forEach(t=>t.onended=()=>fail('Микрофон отключён. Подключите его и нажмите «Повторить».'));
        const ctx=new AudioContext({sampleRate:16000});resources.current.ctx=ctx;
        await ctx.audioWorklet.addModule('/wake-processor.js');if(!alive())return;
        await ctx.resume();if(!alive())return;
        if(ctx.state!=='running')throw new Error('AudioContext suspended');
        const node=new AudioWorkletNode(ctx,'friday-pcm');resources.current.node=node;
        const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/wake`);resources.current.socket=socket;
        let ready=false,finished=false;
        socket.onopen=()=>{if(alive())socket.send(JSON.stringify({token,sample_rate:16000,mode:stopOnly?'stop':'command'}));};
        socket.onerror=()=>fail('Нет связи с голосовой активацией. Нажмите «Повторить».');
        socket.onclose=()=>{if(!finished)fail('Голосовая активация отключилась. Нажмите «Повторить».');};
        socket.onmessage=event=>{
          if(!alive())return;
          let result;try{result=JSON.parse(event.data);}catch{fail('Неверный ответ голосового сервиса.');return;}
          if(result.type==='ready'){ready=true;setStatus('waiting');}
          if(result.type==='wake'||result.type==='listening')setStatus('listening');
          if(result.type==='wake'){
            const oscillator=ctx.createOscillator(),gain=ctx.createGain();oscillator.frequency.value=740;gain.gain.setValueAtTime(.025,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.1);oscillator.connect(gain);gain.connect(ctx.destination);oscillator.start();oscillator.stop(ctx.currentTime+.1);oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
          }
          if(result.type==='transcribing')setStatus('transcribing');
          if(['idle','timeout','cancelled'].includes(result.type))setStatus('waiting');
          if(result.type==='error')fail(result.message);
          if(result.type==='uncertain'){finished=true;stop();setStatus('paused');uncertainCallback.current?.(result.text,result.message);}
          if(result.type==='stopped'){finished=true;stop();setStatus('paused');stopCallback.current?.();}
          if(result.type==='command'&&typeof result.text==='string'){
            finished=true;stop();setStatus('paused');callback.current(result.text);
          }
        };
        node.port.onmessage=event=>{
          if(!alive()||!ready||socket.readyState!==WebSocket.OPEN)return;
          if(socket.bufferedAmount>32000*3){fail('Звук поступает быстрее, чем обрабатывается. Повторите подключение.');return;}
          socket.send(event.data);
        };
        ctx.createMediaStreamSource(stream).connect(node);node.connect(ctx.destination);
      }catch(e){
        const name=(e as Error).name;
        fail(name==='NotAllowedError'?'Разрешите Пятнице доступ к микрофону в параметрах Windows.':name==='OverconstrainedError'||name==='NotFoundError'?'Выбранный микрофон не найден. Выберите другое устройство.':'Не удалось запустить фоновый микрофон. Нажмите «Повторить».');
      }
    })();},stopOnly?80:1000);
    return()=>{clearTimeout(timer);stop();};
  },[enabled,paused,device,token,attempt,stop,stopOnly]);
  return {status,error,stop,retry:()=>setAttempt(n=>n+1)};
}
