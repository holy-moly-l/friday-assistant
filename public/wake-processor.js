// AudioWorklet continues receiving microphone frames when Electron is minimized.
// Average samples into 16 kHz PCM; transfer a 100 ms frame without copying it again.
class FridayPCM extends AudioWorkletProcessor {
  constructor(){super();this.sum=0;this.count=0;this.position=0;this.buffer=new Int16Array(1600);this.index=0;}
  process(inputs,outputs){
    const channel=inputs[0]?.[0];
    if(channel){for(const sample of channel){
      this.sum+=sample;this.count++;this.position+=16000;
      if(this.position>=sampleRate){
        this.position-=sampleRate;
        const value=Math.max(-1,Math.min(1,this.sum/this.count));
        this.buffer[this.index++]=Math.round(value*(value<0?32768:32767));this.sum=0;this.count=0;
        if(this.index===1600){this.port.postMessage(this.buffer.buffer,[this.buffer.buffer]);this.buffer=new Int16Array(1600);this.index=0;}
      }
    }}
    // The node is connected to keep it alive, but never plays captured audio.
    for(const output of outputs)for(const channel of output)channel.fill(0);
    return true;
  }
}
registerProcessor('friday-pcm',FridayPCM);
