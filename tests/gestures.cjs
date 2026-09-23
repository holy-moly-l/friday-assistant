const assert=require('node:assert/strict');
const {GestureRecognizer,pose}=require('../src/gestures.ts');
function hand(type='palm',x=0,id='Right'){
  const p=Array.from({length:21},()=>({x:.5+x,y:.6,z:0}));p[0]={x:.5+x,y:.8,z:0};
  for(const [n,baseX] of [[5,.43],[9,.50],[13,.57],[17,.63]]){
    p[n]={x:baseX+x,y:.62,z:0};p[n+1]={x:baseX+x,y:.48,z:0};p[n+2]={x:baseX+x,y:.37,z:0};p[n+3]={x:baseX+x,y:.29,z:0};
    if(type==='fist'||type==='victory'&&n>=13){p[n+2].y=.60;p[n+3].y=.65;}
  }
  p[4]={x:.30+x,y:.58,z:0};
  if(type==='pinch')p[4]={...p[8],x:p[8].x+.01};
  return {id,score:.99,points:p};
}
for(const state of ['palm','fist','victory','pinch'])assert.equal(pose(hand(state)),state);
function sample(r,state,start,duration,x=0){let events=[];for(let t=start;t<start+duration;t+=50)events.push(...r.update([hand(state,x)],t));return events;}
function ready(mode='windows'){const r=new GestureRecognizer(mode);sample(r,'palm',100,500);return r;}
for(const mode of ['windows','media']){
 const r=new GestureRecognizer(mode);assert.equal(sample(r,'fist',100,1400).filter(x=>x.kind==='stop').length,1,'stop before initial palm');
 r.update([],1600);assert.equal(sample(r,'fist',1700,1400).filter(x=>x.kind==='stop').length,1,'stop after hand reacquisition');
}
{
 const r=new GestureRecognizer();assert.deepEqual(sample(r,'pinch',100,1500),[],'held pinch on activation must not grab');
}
{
 const r=ready();const e=sample(r,'pinch',600,700);assert.equal(e.filter(x=>x.kind==='drag_start').length,1);assert(e.some(x=>x.kind==='drag_move'));
 assert.equal(r.update([],1350)[0].kind,'release');assert.deepEqual(sample(r,'pinch',1400,600),[],'reacquisition must require release');
}
{
 const r=ready();assert.equal(sample(r,'victory',600,2000).filter(x=>x.kind==='maximize').length,1,'held V must fire only once');
}
{
 const r=ready('media');assert.equal(sample(r,'pinch',600,2500).filter(x=>x.kind==='play_pause').length,1);
 assert(!sample(r,'victory',3200,1500).length,'V must not maximize in media mode');
}
{
 const r=ready();assert.equal(sample(r,'fist',600,1400).filter(x=>x.kind==='stop').length,1);
}
for(const mode of ['windows','media']){
 const r=ready(mode);let events=[];for(let i=0;i<12;i++)events.push(...r.update([hand('palm',-i*.03)],600+i*40));
 assert.equal(events.filter(e=>e.kind===(mode==='windows'?'monitor_right':'seek_forward')).length,1);
}
{
 const r=ready();sample(r,'pinch',600,500);assert.equal(r.update([hand('pinch',.4)],1150)[0].kind,'release','hand jump must release');
}
{
 const r=ready();assert.deepEqual(r.update([hand('pinch',0,'Left')],650),[],'other hand cannot control');
}
{
 const r=ready();const events=[];for(let i=0;i<30;i++)events.push(...r.update([hand('palm',Math.sin(i)*.008)],600+i*40));assert.equal(events.length,0,'jitter cannot swipe');
}
console.log('Gesture recognition PASS: one hand, hold, release, hysteresis, two modes, swipe, jitter, loss, stop');
