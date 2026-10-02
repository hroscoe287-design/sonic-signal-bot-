const canvas=document.getElementById("chart"),ctx=canvas.getContext("2d"),adxCanvas=document.getElementById("adxChart"),adxCtx=adxCanvas.getContext("2d");
const signalEl=document.getElementById("signal"),reasonEl=document.getElementById("reason"),confidenceEl=document.getElementById("confidence"),meter=document.getElementById("meter"),threshold=document.getElementById("threshold"),thresholdValue=document.getElementById("thresholdValue"),priceEl=document.getElementById("price"),feedStatus=document.getElementById("feedStatus"),assetEl=document.getElementById("asset"),timeframeEl=document.getElementById("timeframe"),selectedAssetEl=document.getElementById("selectedAsset"),selectedTimeframeEl=document.getElementById("selectedTimeframe");
let state={}, candles=[], dmi=[];
let controlsInitialized=false;
let applyingConfig=false;
let pendingAsset=null;
let pendingTimeframe=null;

document.querySelectorAll(".tabs button").forEach(btn=>{
  btn.addEventListener("click",()=>{
    document.querySelectorAll(".tabs button").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
    const label=btn.textContent.trim();
    const targets={
      Signals:".signal-grid",
      Chart:".chart-card",
      Performance:".rules",
      Settings:".controls"
    };
    const target=document.querySelector(targets[label]);
    if(target) target.scrollIntoView({behavior:"smooth",block:"start"});
  });
});

function showSelectedAsset(){
  const asset=assetEl.value||"—";
  const p=Number(timeframeEl.value||60);
  if(selectedAssetEl) selectedAssetEl.textContent=asset;
  if(selectedTimeframeEl) selectedTimeframeEl.textContent="TIMEFRAME: "+(p<60?p+"s":(p%60===0?p/60+"m":p+"s"));
}
assetEl.addEventListener("change",()=>{pendingAsset=assetEl.value;showSelectedAsset()});
timeframeEl.addEventListener("change",()=>{pendingTimeframe=Number(timeframeEl.value);showSelectedAsset()});
threshold.addEventListener("input",()=>thresholdValue.textContent=threshold.value+"%");
document.getElementById("apply").addEventListener("click",async()=>{
  applyingConfig=true;
  const asset=assetEl.value;
  const timeframe=Number(timeframeEl.value);
  try{
    const r=await fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({asset,timeframe})});
    const result=await r.json();
    if(result.ok){
      state.asset=asset; state.period=timeframe; state.timeframe=timeframe+"s";
      pendingAsset=asset; pendingTimeframe=timeframe;
      if([...assetEl.options].some(o=>o.value===asset)) assetEl.value=asset;
      if([...timeframeEl.options].some(o=>Number(o.value)===timeframe)) timeframeEl.value=String(timeframe);
      if(selectedAssetEl) selectedAssetEl.textContent=asset;
      if(selectedTimeframeEl) selectedTimeframeEl.textContent="TIMEFRAME: "+(timeframe<60?timeframe+"s":(timeframe%60===0?timeframe/60+"m":timeframe+"s"));
      feedStatus.textContent="SWITCHING";
    }else{
      reasonEl.textContent=result.error||"Unable to change timeframe";
    }
    await pollState();
  }finally{setTimeout(()=>{applyingConfig=false},500)}
});

function resize(){const d=devicePixelRatio||1,r=canvas.getBoundingClientRect(),ar=adxCanvas.getBoundingClientRect();canvas.width=Math.max(1,r.width*d);canvas.height=Math.max(1,r.height*d);ctx.setTransform(d,0,0,d,0,0);adxCanvas.width=Math.max(1,ar.width*d);adxCanvas.height=Math.max(1,ar.height*d);adxCtx.setTransform(d,0,0,d,0,0);draw();drawAdx()}
window.addEventListener("resize",resize);resize();

function draw(){
  const w=canvas.clientWidth,h=canvas.clientHeight;
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle="#071018";ctx.fillRect(0,0,w,h);
  if(candles.length<2){ctx.fillStyle="#8ca5b8";ctx.font="14px sans-serif";ctx.fillText("Waiting for live candles…",18,30);return}
  const left=52,right=12,top=14,priceBottom=h-14;
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
}
function drawAdx(){
  const w=adxCanvas.clientWidth,h=adxCanvas.clientHeight;
  adxCtx.clearRect(0,0,w,h);adxCtx.fillStyle="#071018";adxCtx.fillRect(0,0,w,h);
  const left=52,right=12,top=24,bottom=h-22;
  adxCtx.fillStyle="#91a8b8";adxCtx.font="11px sans-serif";adxCtx.fillText("ADX • +DI / −DI • LENGTH 7 • SMOOTHING 14",left,14);
  const ds=(Array.isArray(state.dmi_series)?state.dmi_series:[]).slice(-70);
  if(ds.length<2){adxCtx.fillStyle="#718798";adxCtx.font="13px sans-serif";adxCtx.fillText("Waiting for ADX DI data…",left,45);return}
  const mx=Math.max(25,...ds.flatMap(x=>[+x.plus||0,+x.minus||0]));
  const dx=(w-left-right)/(ds.length-1);
  for(let n=0;n<=4;n++){const y=bottom-n*(bottom-top)/4;adxCtx.strokeStyle="rgba(120,190,230,.12)";adxCtx.beginPath();adxCtx.moveTo(left,y);adxCtx.lineTo(w-right,y);adxCtx.stroke();adxCtx.fillStyle="#718798";adxCtx.font="9px sans-serif";adxCtx.fillText(String(Math.round(mx*n/4)),4,y+3)}
  [["plus","#35d98a"],["minus","#ff5c70"]].forEach(([key,col])=>{
    adxCtx.strokeStyle=col;adxCtx.lineWidth=2;adxCtx.beginPath();
    ds.forEach((v,i)=>{const x=left+i*dx,y=bottom-(+v[key]||0)/mx*(bottom-top);i?adxCtx.lineTo(x,y):adxCtx.moveTo(x,y)});adxCtx.stroke();
  });
  const last=ds[ds.length-1],gap=Math.abs((+last.plus||0)-(+last.minus||0));
  adxCtx.fillStyle="#35d98a";adxCtx.fillText("+DI "+Number(last.plus||0).toFixed(2),left+50, h-6);
  adxCtx.fillStyle="#ff5c70";adxCtx.fillText("−DI "+Number(last.minus||0).toFixed(2),left+145,h-6);
  adxCtx.fillStyle=gap>=5?"#ffd21c":"#91a8b8";adxCtx.fillText(gap>=5?"WIDE OVERLAP":"OVERLAP",w-105,h-6);
}

function clocks(){const now=new Date(),zones={local:Intl.DateTimeFormat().resolvedOptions().timeZone,ny:"America/New_York",london:"Europe/London",tokyo:"Asia/Tokyo"};Object.entries(zones).forEach(([id,z])=>{let e=document.getElementById("clock-"+id);if(e)e.textContent=new Intl.DateTimeFormat("en-US",{timeZone:z,hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(now)});let p=Number(state.period||60),r=p-(Math.floor(Date.now()/1000)%p),e=document.getElementById("countdown");if(e)e.textContent=String(Math.floor(r/60)).padStart(2,"0")+":"+String(r%60).padStart(2,"0")}

async function loadAssets(){
  try{
    const d=await(await fetch("/api/assets",{cache:"no-store"})).json();
    const previousAsset=state.asset||assetEl.value;
    const previousPeriod=Number(state.period||timeframeEl.value||60);

    assetEl.innerHTML="";
    const groups=d.asset_groups||{};
    const order=["Forex","Crypto","Indices","Commodities","Stocks","Other"];
    order.forEach(category=>{
      const items=Array.isArray(groups[category])?groups[category]:[];
      if(!items.length)return;
      const group=document.createElement("optgroup");
      group.label=category.toUpperCase();
      items.forEach(symbol=>{
        const o=document.createElement("option");
        o.value=symbol;
        o.textContent=symbol;
        group.appendChild(o);
      });
      assetEl.appendChild(group);
    });
    if(!assetEl.options.length){
      (d.assets||[]).forEach(symbol=>{
        const o=document.createElement("option");
        o.value=symbol;o.textContent=symbol;assetEl.appendChild(o);
      });
    }
    if(previousAsset && [...assetEl.options].some(o=>o.value===previousAsset)) assetEl.value=previousAsset;

    timeframeEl.innerHTML="";
    (d.timeframes||[]).forEach(x=>{
      const o=document.createElement("option");
      o.value=String(x);
      o.textContent=x<60?x+"s":(x%60===0?x/60+"m":x+"s");
      timeframeEl.appendChild(o);
    });
    if([...timeframeEl.options].some(o=>Number(o.value)===previousPeriod)){
      timeframeEl.value=String(previousPeriod);
    }
    assetEl.disabled=false;
    timeframeEl.disabled=false;
  }catch(e){
    console.error("Asset catalog load failed",e);
    reasonEl.textContent="Unable to load live asset/timeframe menu";
  }
}

function updateFeed(s){
  state=s;candles=Array.isArray(s.candles)?s.candles:[];dmi=Array.isArray(s.dmi_series)?s.dmi_series:[];
  priceEl.textContent=s.price!=null?Number(s.price).toFixed(8):"—";feedStatus.textContent=s.feed_connected?"LIVE":"WAITING";
  if(s.asset && [...assetEl.options].some(o=>o.value===s.asset) && (pendingAsset===null || s.asset===pendingAsset)) assetEl.value=s.asset;
  if(s.period && [...timeframeEl.options].some(o=>Number(o.value)===Number(s.period)) && (pendingTimeframe===null || Number(s.period)===pendingTimeframe)) timeframeEl.value=String(s.period);
  if(pendingAsset!==null && s.asset===pendingAsset) pendingAsset=null;
  if(pendingTimeframe!==null && Number(s.period)===pendingTimeframe) pendingTimeframe=null;
  if(s.asset && selectedAssetEl) selectedAssetEl.textContent=s.asset;
  if(s.period && selectedTimeframeEl){
    const p=Number(s.period);
    selectedTimeframeEl.textContent="TIMEFRAME: "+(p<60?p+"s":(p%60===0?p/60+"m":p+"s"));
  }
  controlsInitialized=true;
  draw();drawAdx();
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
loadAssets().then(()=>pollState());setInterval(pollState,250);setInterval(clocks,250);pollState();clocks();
