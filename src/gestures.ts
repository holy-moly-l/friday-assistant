// Pure gesture recognizer; independent from camera, renderer and Windows execution.
export type Point = {x:number; y:number; z:number};
export type Hand = {id:string; points:Point[]; score:number; aspect?:number};
export type GestureAction = {kind:'drag_start'|'drag_move'|'release'|'maximize'|'monitor_left'|'monitor_right'|'play_pause'|'seek_forward'|'seek_backward'|'stop'; x?:number; y?:number};
export type Mode = 'windows'|'media';
const distance=(a:Point,b:Point)=>Math.hypot(a.x-b.x,a.y-b.y,a.z-b.z);
const center=(p:Point[])=>({x:(p[0].x+p[9].x)/2,y:(p[0].y+p[9].y)/2,z:0});

export function pose(hand:Hand, wasPinched=false) {
  // Landmarks use separate normalized axes; bring y into x/z units for 16:9 cameras.
  const p=hand.points.map(p=>({...p,y:p.y/(hand.aspect||1)}));
  if(p.length!==21 || hand.score<.65 || p.some(p=>!Number.isFinite(p.x+p.y+p.z)))return 'none';
  const size=distance(p[0],p[9]);
  if(size<.055)return 'none';
  const extended=[8,12,16,20].map(t=>distance(p[t],p[0])>distance(p[t-2],p[0])*1.27 && distance(p[t],p[t-3])>size*.55);
  if(extended.every(x=>!x))return 'fist';
  const pinch=distance(p[4],p[8])/size;
  if(pinch<(wasPinched?.43:.29))return 'pinch';
  if(extended.every(Boolean))return 'palm';
  if(extended[0]&&extended[1]&&!extended[2]&&!extended[3])return 'victory';
  return 'neutral';
}

export class GestureRecognizer {
  mode:Mode; hand:string;
  private previous='none';private since=0;private last=0;private smooth:Point|null=null;
  private swipe:Point|null=null;private swipeTime=0;private fired=false;private dragging=false;
  private needsRelease=true;private cooldown=0;private anchor:Point|null=null;
  hint='Покажите ведущую руку';progress=0;
  constructor(mode:Mode='windows',hand='Right'){this.mode=mode;this.hand=hand;}
  reset(){this.previous='none';this.smooth=null;this.anchor=null;this.dragging=false;this.needsRelease=true;this.fired=false;this.last=0;this.progress=0;}
  update(hands:Hand[], now:number):GestureAction[] {
    const selected=hands.filter(h=>h.id===this.hand && h.score>=.65);
    const hand=selected.length===1?selected[0]:undefined;
    const state=hand?pose(hand,this.previous==='pinch'):'none';
    const events:GestureAction[]=[];
    this.progress=0;
    if(state==='none'||!hand){
      if(this.dragging)events.push({kind:'release'});
      this.reset();this.hint='Рука вне кадра — движение остановлено';return events;
    }
    const raw=center(hand.points);raw.x=1-raw.x; // Same coordinates as the mirrored preview.
    const dt=now-this.last;
    if(this.smooth && (dt>400 || Math.hypot(raw.x-this.smooth.x,raw.y-this.smooth.y)>.23)){
      if(this.dragging)events.push({kind:'release'});
      this.reset();this.hint='Покажите жест снова';return events;
    }
    const alpha=1-Math.exp(-Math.max(1,dt)/55);
    this.smooth=this.smooth?{x:this.smooth.x+(raw.x-this.smooth.x)*alpha,y:this.smooth.y+(raw.y-this.smooth.y)*alpha,z:0}:raw;
    this.last=now;
    if(state!==this.previous){this.since=now;this.fired=false;this.swipe=null;this.previous=state;}
    if(this.dragging && state!=='pinch'){this.dragging=false;events.push({kind:'release'});}
    // First show a relaxed/open hand. A held pinch on activation or reacquisition cannot grab.
    if(this.needsRelease){
      this.hint='Раскройте ладонь, чтобы начать';
      if((state==='palm'||state==='neutral') && now-this.since>=250){this.needsRelease=false;this.since=now;}
      return events;
    }
    if(state==='fist'){
      this.hint='Удерживайте кулак — остановить управление';this.progress=Math.min(1,(now-this.since)/1000);
      if(this.progress===1&&!this.fired){this.fired=true;events.push({kind:'stop'});}
      return events;
    }
    if(now<this.cooldown){this.hint='Отпустите жест';return events;}
    if(state==='pinch'){
      this.hint=this.mode==='windows'?'Щипок — перемещение окна':'Щипок — пауза / воспроизведение';
      const hold=this.mode==='windows'?220:550;
      this.progress=Math.min(1,(now-this.since)/hold);
      if(this.progress===1&&!this.fired){
        this.fired=true;
        if(this.mode==='windows'){this.dragging=true;this.anchor={...this.smooth};events.push({kind:'drag_start',...this.smooth});}
        else {events.push({kind:'play_pause'});this.cooldown=now+1000;}
      } else if(this.dragging && this.anchor){events.push({kind:'drag_move',...this.smooth});}
    } else if(state==='victory' && this.mode==='windows'){
      this.hint='Удерживайте V — развернуть / восстановить';this.progress=Math.min(1,(now-this.since)/900);
      if(this.progress===1&&!this.fired){this.fired=true;this.cooldown=now+1200;events.push({kind:'maximize'});}
    } else if(state==='palm'){
      this.hint=this.mode==='windows'?'Ладонь в сторону — другой монитор':'Ладонь в сторону — перемотка на 5 с';
      if(!this.swipe && now-this.since>=300){this.swipe={...this.smooth};this.swipeTime=now;}
      if(this.swipe && !this.fired){
        const dx=this.smooth.x-this.swipe.x,dy=this.smooth.y-this.swipe.y;
        if(now-this.swipeTime>850){this.swipe={...this.smooth};this.swipeTime=now;}
        else if(Math.abs(dx)>.22 && Math.abs(dy)<.12){
          this.fired=true;this.cooldown=now+1200;
          events.push({kind:this.mode==='windows'?(dx>0?'monitor_right':'monitor_left'):(dx>0?'seek_forward':'seek_backward')});
        }
      }
    } else this.hint='Щипок, V или движение открытой ладони';
    return events;
  }
}
