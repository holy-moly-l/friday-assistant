import {FilesetResolver, HandLandmarker} from '@mediapipe/tasks-vision';
let tracker:HandLandmarker|null=null;
self.onmessage=async(event:MessageEvent)=>{
  const {type, frame, time, base}=event.data;
  try {
    if(type==='init'){
      const files=await FilesetResolver.forVisionTasks(base+'/hand-tracking/wasm',true);
      // CPU in a worker avoids competing with STT/Qwen for the GPU and blocking React.
      tracker=await HandLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:base+'/hand-tracking/hand_landmarker.task',delegate:'CPU'},runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.65,minHandPresenceConfidence:.65,minTrackingConfidence:.65});
      self.postMessage({type:'ready'});
    } else if(type==='frame' && tracker){
      const start=performance.now();
      const result=tracker.detectForVideo(frame,time);
      self.postMessage({type:'hands',time,latency:performance.now()-start,hands:result.landmarks.map((points,i)=>({
        // Camera input is not mirrored; the UI is. MediaPipe handedness assumes selfie input.
        id:result.handedness[i][0].categoryName==='Left'?'Right':'Left',points,score:result.handedness[i][0].score,aspect:frame.width/frame.height,
      }))});
    }
  } catch (error) {console.error('[HANDS] runtime initialization/inference failed',error instanceof Error?error.message:'unknown');self.postMessage({type:'error',message:'Не удалось запустить локальное отслеживание рук. Выключите камеру и повторите.'});}
  finally {frame?.close();}
};
