import type {Hand} from './gestures';
const chains=[[0,1,2,3,4],[0,5,6,7,8],[5,9,10,11,12],[9,13,14,15,16],[13,17,18,19,20],[0,17]];

export function drawHands(canvas:HTMLCanvasElement,hands:Hand[],width:number,height:number,progress:number,leading:string){
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
  const ctx=canvas.getContext('2d');if(!ctx)return;
  ctx.clearRect(0,0,width,height);
  for(const hand of hands){
    const points=hand.points.map(p=>({x:(1-p.x)*width,y:p.y*height,z:p.z}));
    if(points.length!==21)continue;
    const color=hand.id==='Right'?'104,214,255':'171,171,255';
    const scale=Math.max(.7,width/1000);
    ctx.save();ctx.lineCap='round';ctx.lineJoin='round';
    // A translucent palm plane, thin lit bones and crisp joint cores retain the real hand beneath.
    ctx.beginPath();[0,5,9,13,17].forEach((i,n)=>n?ctx.lineTo(points[i].x,points[i].y):ctx.moveTo(points[i].x,points[i].y));ctx.closePath();
    const fill=ctx.createLinearGradient(points[0].x,points[0].y,points[9].x,points[9].y);
    fill.addColorStop(0,`rgba(${color},.02)`);fill.addColorStop(1,`rgba(${color},.18)`);ctx.fillStyle=fill;ctx.fill();
    for(const glow of [true,false]){
      ctx.lineWidth=(glow?7:2.2)*scale;ctx.strokeStyle=`rgba(${color},${glow?.12:.9})`;
      ctx.shadowColor=`rgba(${color},.55)`;ctx.shadowBlur=glow?14*scale:0;
      for(const chain of chains){ctx.beginPath();chain.forEach((i,n)=>n?ctx.lineTo(points[i].x,points[i].y):ctx.moveTo(points[i].x,points[i].y));ctx.stroke();}
    }
    for(let i=0;i<points.length;i++){
      const p=points[i],tip=[4,8,12,16,20].includes(i),radius=(tip?4.6:3)*scale;
      ctx.beginPath();ctx.arc(p.x,p.y,radius+3*scale,0,Math.PI*2);ctx.fillStyle=`rgba(${color},.12)`;ctx.fill();
      ctx.beginPath();ctx.arc(p.x,p.y,radius,0,Math.PI*2);ctx.fillStyle=tip?'#f3fbff':`rgb(${color})`;ctx.fill();
    }
    if(hand.id===leading&&progress>0){
      const p=points[0];ctx.beginPath();ctx.arc(p.x,p.y,20*scale,-Math.PI/2,-Math.PI/2+progress*Math.PI*2);ctx.strokeStyle='#e5f8ff';ctx.lineWidth=2.5*scale;ctx.stroke();
    }
    ctx.restore();
  }
}
