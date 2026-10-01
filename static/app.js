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
let last=1.13920;

threshold.addEventListener("input",()=>thresholdValue.textContent=threshold.value+"%");
document.getElementById("apply").addEventListener("click",()=>{
  points=[]; last=1.13920; setWait("Engine reset — waiting for qualifying Fractal + DMI setup");
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

function tick(){
  last += (Math.random()-.48)*.00025;
  points.push(last); if(points.length>80)points.shift();
  priceEl.textContent=last.toFixed(5);
  draw();
  // This front-end intentionally does not invent a trading signal.
  // The real engine will set Fractal + DMI values when a live feed is connected.
}
setInterval(tick,500); tick();
setWait("Waiting for qualifying Fractal + DMI setup");
