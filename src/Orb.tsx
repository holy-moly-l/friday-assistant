import { useLayoutEffect, useRef } from 'react';
import { Pause, Play } from 'lucide-react';
import { themes, type ThemeId } from './AppearanceSettings';
export type MotionMode='interactive'|'ambient'|'still';
export function Orb({active,level,theme,motion,onMotion}:{active:boolean;level:number;theme:ThemeId;motion:MotionMode;onMotion:(mode:MotionMode)=>void}){
  const canvas=useRef<HTMLCanvasElement>(null);
  const values=useRef({active,level,rgb:themes[theme].rgb,motion});values.current={active,level,rgb:themes[theme].rgb,motion};
  const controls=useRef({x:180,y:145,hover:false,drag:false,lastX:0,lastY:0,yaw:0,pitch:0,vx:0,vy:0});
  const resumeMode=useRef<MotionMode>('interactive');
  const toggle=()=>{if(motion==='still')onMotion(resumeMode.current);else{resumeMode.current=motion;onMotion('still');}};
  useLayoutEffect(()=>{
    const el=canvas.current!,ctx=el.getContext('2d')!;
    const dpr=Math.min(devicePixelRatio||1,2);el.width=360*dpr;el.height=300*dpr;ctx.scale(dpr,dpr);
    const points=Array.from({length:1000},(_,i)=>{const y=1-i/999*2,r=Math.sqrt(1-y*y),a=i*2.399963;return{x:Math.cos(a)*r,y,z:Math.sin(a)*r};});
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');let raf=0,last=0,t=0,visible=true;
    const render=(time:number)=>{
      raf=0;const dt=Math.min((time-last)||33,50)/1000;
      if(time-last<32){schedule();return;}last=time;
      const v=values.current,c=controls.current,moving=v.motion!=='still'&&!reduced.matches;
      if(moving){t+=dt;if(!c.drag){c.yaw+=c.vx;c.pitch+=c.vy;c.vx*=.93;c.vy*=.93;}c.pitch=Math.max(-1.1,Math.min(1.1,c.pitch));}
      const angle=t*.13+c.yaw,pitch=c.pitch,scale=94+(moving&&v.active?Math.sin(t*4)*2+v.level*12:0);
      ctx.clearRect(0,0,360,300);
      const glow=ctx.createRadialGradient(180,143,15,180,143,145);glow.addColorStop(0,`rgba(${v.rgb},.12)`);glow.addColorStop(1,'transparent');ctx.fillStyle=glow;ctx.fillRect(20,0,320,295);
      const projected=points.map(p=>{const x=p.x*Math.cos(angle)+p.z*Math.sin(angle),z=p.z*Math.cos(angle)-p.x*Math.sin(angle);return{x,y:p.y*Math.cos(pitch)-z*Math.sin(pitch),z:p.y*Math.sin(pitch)+z*Math.cos(pitch)};}).sort((a,b)=>a.z-b.z);
      for(const p of projected){let x=180+p.x*scale*(1+p.z*.1),y=143+p.y*scale*(1+p.z*.1);const distance=Math.hypot(x-c.x,y-c.y),near=moving&&v.motion==='interactive'&&c.hover?Math.max(0,1-distance/72):0;
        x+=(x-c.x)*near*.12;y+=(y-c.y)*near*.12;
        ctx.fillStyle=`rgba(${v.rgb},${Math.min(.95,.14+(p.z+1)*.32+near*.35)})`;ctx.beginPath();ctx.arc(x,y,(p.z>.3?1.15:.7)+near*.8,0,Math.PI*2);ctx.fill();
      }
      ctx.save();ctx.translate(180,143);ctx.rotate(-.3+Math.sin(t*.3)*.04+pitch*.15);ctx.strokeStyle=`rgba(${v.rgb},.23)`;ctx.lineWidth=.8;ctx.beginPath();ctx.ellipse(0,0,137,38,0,0,Math.PI*2);ctx.stroke();ctx.restore();
      const shadow=ctx.createRadialGradient(180,264,1,180,264,46);shadow.addColorStop(0,`rgba(${v.rgb},.18)`);shadow.addColorStop(1,'transparent');ctx.fillStyle=shadow;ctx.fillRect(134,262,92,5);
      if(moving)schedule();
    };
    function schedule(){if(!raf&&visible&&!document.hidden)raf=requestAnimationFrame(render);}
    const refresh=()=>{last=0;schedule();};
    const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)refresh();else{cancelAnimationFrame(raf);raf=0;}});observer.observe(el);
    reduced.addEventListener('change',refresh);document.addEventListener('visibilitychange',refresh);el.addEventListener('pointermove',refresh);el.addEventListener('keydown',refresh);
    render(performance.now());return()=>{cancelAnimationFrame(raf);observer.disconnect();reduced.removeEventListener('change',refresh);document.removeEventListener('visibilitychange',refresh);el.removeEventListener('pointermove',refresh);el.removeEventListener('keydown',refresh);};
  },[theme,motion]);
  return <div className={'orb-wrap interactive-orb '+motion}>
    <canvas ref={canvas} tabIndex={0} role="img" aria-label="Интерактивное ядро. Перетаскивайте мышью или вращайте стрелками. Пробел — пауза."
      onPointerMove={e=>{const c=controls.current,r=e.currentTarget.getBoundingClientRect();c.x=(e.clientX-r.left)*360/r.width;c.y=(e.clientY-r.top)*300/r.height;c.hover=true;if(c.drag&&motion==='interactive'){c.vx=(e.clientX-c.lastX)*.006;c.vy=(e.clientY-c.lastY)*.005;c.yaw+=c.vx;c.pitch+=c.vy;}c.lastX=e.clientX;c.lastY=e.clientY;}}
      onPointerDown={e=>{if(motion!=='interactive'||e.button!==0)return;e.currentTarget.setPointerCapture(e.pointerId);Object.assign(controls.current,{drag:true,lastX:e.clientX,lastY:e.clientY,vx:0,vy:0});}}
      onPointerUp={e=>{controls.current.drag=false;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}}
      onPointerCancel={()=>{controls.current.drag=false;}}
      onLostPointerCapture={()=>{controls.current.drag=false;}}
      onPointerLeave={()=>{controls.current.hover=false;}}
      onKeyDown={e=>{if(e.ctrlKey||e.altKey||e.metaKey)return;if(e.code==='Space'){e.preventDefault();toggle();}if(motion==='interactive'&&e.key.startsWith('Arrow')){e.preventDefault();if(e.key==='ArrowLeft')controls.current.yaw-=.2;if(e.key==='ArrowRight')controls.current.yaw+=.2;if(e.key==='ArrowUp')controls.current.pitch-=.15;if(e.key==='ArrowDown')controls.current.pitch+=.15;}}}/>
    <span className="orb-tip" aria-hidden="true">{motion==='interactive'?'Потяните, чтобы повернуть':motion==='still'?'Движение на паузе':''}</span>
    <button className="orb-pause" onClick={toggle} aria-label={motion==='still'?'Включить анимацию':'Приостановить анимацию'} title={motion==='still'?'Включить анимацию':'Приостановить анимацию'}>{motion==='still'?<Play size={14}/>:<Pause size={14}/>}</button>
  </div>;
}
