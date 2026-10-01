const canvas=document.getElementById("chart");
const ctx=canvas.getContext("2d");
const signalEl=document.getElementById("signal");
const reasonEl=document.getElementById("reason");
const confidenceEl=document.getElementById("confidence");
const meter=document.getElementById("meter");
const threshold=document.getElementById("threshold");
const thresholdValue=document.getElementById("thresholdValue");
const priceEl=document.getElementById("price");
const feedStatus=document.getElementById("feedStatus");
let points=[];

threshold.addEventListener("input",()=>thresholdValue.textContent=threshold.value+"%");
document.getElementById("apply").addEventListener("click",()=>{
  points=[];
  setWait("Engine reset — waiting for qualifying Fractal + DMI setup");
  pollState();
});

function setWait(reason){
  signalEl.textContent="WAIT"; signalEl.className="signal wait";
  reasonEl.textContent=reason; confidenceEl.textContent="0%"; meter.style.width="0%";
  document.getElementById("plusSquares").textContent="□□□□□";
  document.getElementById("minusSquares").textContent="□□□□□";
}

function resize(){
  const dpr=devicePixelRatio||1;
  const r=canvas.getBoundingClientRect();
  canvas.width=r.width*dpr; canvas.height=r.height*dpr;
  ctx.setTransform(dpr,0,0,dpr,0,0);
}
window.addEventListener("resize",resize); resize();

function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle="rgba(120,190,230,.10)"; ctx.lineWidth=1;
  for(let i=1;i<8;i++){const y=i*h/8;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
  for(let i=1;i<10;i++){const x=i*w/10;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}
  if(points.length<2)return;
  const min=Math.min(...points),max=Math.max(...points),pad=(max-min)*.2||.0001;
  ctx.strokeStyle="#35d9ff";ctx.lineWidth=2.5;ctx.beginPath();
  points.forEach((p,i)=>{
    const x=i*(w/(points.length-1)); const y=h-((p-(min-pad))/(max-min+2*pad))*h;
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  });ctx.stroke();
}

function updateFeed(state){
  if(!state) return;
  if(state.price != null) priceEl.textContent=Number(state.price).toFixed(5);

  if(state.feed_connected){
    feedStatus.textContent="LIVE";
  } else {
    feedStatus.textContent="WAITING";
  }

  const candles=Array.isArray(state.candles)?state.candles:[];
  if(candles.length){
    points=candles.slice(-80).map(c=>Number(c.close)).filter(Number.isFinite);
    draw();
  }
}

async function pollState(){
  try{
    const response=await fetch("/api/state",{cache:"no-store"});
    if(response.ok) updateFeed(await response.json());
  }catch(e){
    feedStatus.textContent="WAITING";
  }
}

setInterval(pollState,250);
pollState();
setWait("Waiting for qualifying Fractal + DMI setup");
