export function splitSpeech(text:string,limit=80):string[]{
  const sentences=text.replace(/```[\s\S]*?```/g,' Фрагмент кода доступен в чате. ').match(/[^.!?\n]+[.!?\n]*|[.!?]+/g)||[text];
  const result:string[]=[];let current='';
  for(const sentence of sentences){
    for(const word of sentence.trim().split(/\s+/)){
      if(current.length+word.length+1>limit&&current){result.push(current.trim());current='';}
      if(word.length>limit){for(let i=0;i<word.length;i+=limit)result.push(word.slice(i,i+limit));}
      else current+=(current?' ':'')+word;
    }
    if(current.trim()){result.push(current.trim());current='';}
  }
  if(current.trim())result.push(current.trim());return result.filter(Boolean);
}
