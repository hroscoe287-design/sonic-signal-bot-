const canvas=document.getElementById("chart"),ctx=canvas.getContext("2d");
const signalEl=document.getElementById("signal"),reasonEl=document.getElementById("reason"),confidenceEl=document.getElementById("confidence"),meter=document.getElementById("meter"),threshold=document.getElementById("threshold"),thresholdValue=document.getElementById("thresholdValue"),priceEl=document.getElementById("price"),feedStatus=document.getElementById("feedStatus"),assetEl=document.getElementById("asset"),timeframeEl=document.getElementById("timeframe");
let state={}, candles=[], dmi=[];

threshold.addEventListener("input",()=>thresholdValue.textContent=threshold.value+"%");
document.getElementById("apply").addEventListener("click",async()=>{
  await fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({asset:assetEl.value,timeframe:Number(timeframeEl.value)})});
  await pollState();
});

function resize(){const d=devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=r.width*d;canvas.height=r.height*d;ctx.setTransform(d,0,0,d,0,0);draw()}
window.addEventListener("resize",resize);resize();

function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle="#071018";ctx.fillRect(0,0,w,h);
  if(candles.length<2){ctx.fillStyle="#8ca5b8";ctx.font="14px sans-serif";ctx.fillText("Waiting for live candles…",18,30);return}
  const left=52,right=12,top=14,priceBottom=h*0.67,dmiTop=h*0.73,dmiBottom=h-24;
  const view=candles.slice(-70);
  const hi=Math.max(...view.map(c=>Number(c.high))),lo=Math.min(...view.map(c=>Number(c.low))),range=hi-lo||0.0001;
  const xStep=(w-left-right)/view.length;
  const yPrice=p=>top+(hi-p)/range*(priceBottom-top-8);
  ctx.strokeStyle="rgba(120,190,230,.12)";ctx.lineWidth=1;
  for(let n=0;n<6;n++){const y=top+n*(priceBottom-top)/5;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillStyle="#718798";ctx.font="10px sans-serif";ctx.fillText((hi-n*range/5).toFixed(5),4,y+3)}
  view.forEach((c,i)=>{
    const x=left+i*xStep+xStep/2,o=yPrice(+c.open),cl=yPrice(+c.close),hh=yPrice(+c.high),ll=yPrice(+c.low);
    const up=+c.close>=+c.open;ctx.strokeStyle=up?"#35d98a":"#ff5c70";ctx.fillStyle=up?"#35d98a":"#ff5c70";
    ctx.beginPath();ctx.moveTo(x,hh);ctx.lineTo(x,ll);ctx.stroke();
    const bh=Math.max(2,Math.abs(cl-o)),bw=Math.max(3,xStep*.62);ctx.fillRect(x-bw/2,Math.min(o,cl),bw,bh);
  });
  const byTime=new Map(view.map((c,i)=>[Number(c.time),{x:left+i*xStep+xStep/2,c:c}]));
  const marks=Array.isArray(state.fractal_marks)?state.fractal_marks:[];
  marks.forEach(m=>{
    const p=byTime.get(Number(m.time));if(!p)return;
    const y=yPrice(Number(m.price));ctx.fillStyle=m.type==="UP"?"#35d98a":"#ff5c70";ctx.font="bold 14px sans-serif";ctx.textAlign="center";ctx.fillText(m.type==="UP"?"▲":"▼",p.x,m.type==="UP"?y+18:y-8);ctx.textAlign="left";
  });
  ctx.strokeStyle="rgba(255,255,255,.15)";ctx.beginPath();ctx.moveTo(left,dmiTop-12);ctx.lineTo(w-right,dmiTop-12);ctx.stroke();
  ctx.fillStyle="#91a8b8";ctx.font="11px sans-serif";ctx.fillText("ADX • DI LENGTH 7 • ADX SMOOTHING 14",left,dmiTop-18);
  const ds=(Array.isArray(state.dmi_series)?state.dmi_series:[]).slice(-70);if(ds.length>1){
    const mx=Math.max(25,...ds.flatMap(x=>[+x.plus||0,+x.minus||0]));
    const dx=(w-left-right)/(ds.length-1);
    [["plus","#35d98a"],["minus","#ff5c70"]].forEach(([key,col])=>{
      ctx.strokeStyle=col;ctx.lineWidth=key==="adx"?1.4:1.8;ctx.beginPath();
      ds.forEach((v,i)=>{const x=left+i*dx,y=dmiBottom-(+v[key]||0)/mx*(dmiBottom-dmiTop);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
    });
    ctx.fillStyle="#35d98a";ctx.fillText("+DI",left+34,dmiTop+2);ctx.fillStyle="#ff5c70";ctx.fillText("−DI",left+65,dmiTop+2);
  }
}

function clocks(){const now=new Date(),zones={local:Intl.DateTimeFormat().resolvedOptions().timeZone,ny:"America/New_York",london:"Europe/London",tokyo:"Asia/Tokyo"};Object.entries(zones).forEach(([id,z])=>{let e=document.getElementById("clock-"+id);if(e)e.textContent=new Intl.DateTimeFormat("en-US",{timeZone:z,hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(now)});let p=Number(state.period||60),r=p-(Math.floor(Date.now()/1000)%p),e=document.getElementById("countdown");if(e)e.textContent=String(Math.floor(r/60)).padStart(2,"0")+":"+String(r%60).padStart(2,"0")}

async function loadAssets(){try{let d=await(await fetch("/api/assets",{cache:"no-store"})).json();assetEl.innerHTML="";d.assets.forEach(x=>{let o=document.createElement("option");o.value=x;o.textContent=x;assetEl.appendChild(o)});timeframeEl.innerHTML="";d.timeframes.forEach(x=>{let o=document.createElement("option");o.value=x;o.textContent=x<60?x+"s":x/60+"m";timeframeEl.appendChild(o)})}catch(e){}}

function updateFeed(s){
  state=s;candles=Array.isArray(s.candles)?s.candles:[];dmi=Array.isArray(s.dmi_series)?s.dmi_series:[];
  priceEl.textContent=s.price!=null?Number(s.price).toFixed(8):"—";feedStatus.textContent=s.feed_connected?"LIVE":"WAITING";
  if(s.asset)assetEl.value=s.asset;if(s.period)timeframeEl.value=s.period;
  draw();
  const conf=Number(s.confidence||0), rawSignal=s.signal||"WAIT";
  const ok=rawSignal!=="WAIT"&&conf>=Number(threshold.value);
  signalEl.textContent=ok?rawSignal:"WAIT";signalEl.className="signal "+(ok?rawSignal.toLowerCase():"wait");
  confidenceEl.textContent=conf+"%";meter.style.width=Math.min(100,conf)+"%";
  reasonEl.textContent=ok?s.reason:(rawSignal!=="WAIT"?"Signal below threshold: "+conf+"% • "+s.reason:(s.reason||"Waiting"));
  document.getElementById("plusSquares").textContent="■".repeat(Number(s.plus_strength||0))+"□".repeat(5-Number(s.plus_strength||0));
  document.getElementById("minusSquares").textContent="■".repeat(Number(s.minus_strength||0))+"□".repeat(5-Number(s.minus_strength||0));
  let di=document.getElementById("diValues");if(di)di.textContent="+DI "+(s.plus_di??"—")+" • −DI "+(s.minus_di??"—")+" • "+(s.wide_cross?"WIDE X":"OVERLAP");
}
async function pollState(){try{const r=await fetch("/api/state",{cache:"no-store"});if(r.ok)updateFeed(await r.json())}catch(e){feedStatus.textContent="WAITING"}}
loadAssets();setInterval(pollState,250);setInterval(clocks,250);pollState();clocks();
