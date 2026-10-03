(function(){
"use strict";
var canvas=document.getElementById("chart"),ctx=canvas.getContext("2d");
var adxCanvas=document.getElementById("adxChart"),adxCtx=adxCanvas?adxCanvas.getContext("2d"):null;
var signalEl=document.getElementById("signal"),reasonEl=document.getElementById("reason"),confidenceEl=document.getElementById("confidence"),meter=document.getElementById("meter");
var threshold=document.getElementById("threshold"),thresholdValue=document.getElementById("thresholdValue"),priceEl=document.getElementById("price"),feedStatus=document.getElementById("feedStatus");
var assetEl=document.getElementById("asset"),timeframeEl=document.getElementById("timeframe"),selectedAssetEl=document.getElementById("selectedAsset"),selectedTimeframeEl=document.getElementById("selectedTimeframe");
var state={},candles=[],applyingConfig=false,pendingAsset=null,pendingTimeframe=null;

function $(id){return document.getElementById(id);}
function xhr(url,method,data,done){
  var x=new XMLHttpRequest(); x.open(method||"GET",url,true);
  x.setRequestHeader("Cache-Control","no-cache");
  if(data!==null){x.setRequestHeader("Content-Type","application/json");}
  x.onreadystatechange=function(){if(x.readyState===4){if(x.status>=200&&x.status<300){try{done(null,JSON.parse(x.responseText));}catch(e){done(e,null);}}else{done(new Error("HTTP "+x.status),null);}}};
  try{x.send(data===null?null:JSON.stringify(data));}catch(e){done(e,null);}
}
function setSelected(){
  var a=assetEl.value||"—",p=Number(timeframeEl.value||60);
  if(selectedAssetEl)selectedAssetEl.textContent=a;
  if(selectedTimeframeEl)selectedTimeframeEl.textContent="TIMEFRAME: "+(p<60?p+"s":(p%60===0?p/60+"m":p+"s"));
}
function hasOption(el,value,numeric){
  var i,o; for(i=0;i<el.options.length;i++){o=el.options[i];if(numeric?Number(o.value)===Number(value):o.value===value)return true;} return false;
}
function bind(){
  var tabs=document.querySelectorAll(".tabs button"),i;
  for(i=0;i<tabs.length;i++)(function(btn){
    btn.onclick=function(){
      var j;for(j=0;j<tabs.length;j++)tabs[j].classList.remove("active");btn.classList.add("active");
      var targets={Signals:".signal-grid",Chart:".chart-card",Performance:".rules",Settings:".controls"},t=document.querySelector(targets[btn.textContent.trim()]);
      if(t)t.scrollIntoView(false);
    };
  })(tabs[i]);
  assetEl.onchange=function(){pendingAsset=assetEl.value;setSelected();};
  timeframeEl.onchange=function(){pendingTimeframe=Number(timeframeEl.value);setSelected();};
  threshold.oninput=function(){thresholdValue.textContent=threshold.value+"%";};
  $("apply").onclick=function(){
    applyingConfig=true;
    xhr("/api/config","POST",{asset:assetEl.value,timeframe:Number(timeframeEl.value)},function(err,r){
      if(!err&&r&&r.ok){
        state.asset=assetEl.value;state.period=Number(timeframeEl.value);pendingAsset=state.asset;pendingTimeframe=state.period;
        if(hasOption(assetEl,state.asset,false))assetEl.value=state.asset;
        if(hasOption(timeframeEl,state.period,true))timeframeEl.value=String(state.period);
        setSelected();feedStatus.textContent="SWITCHING";
      }else if(r){reasonEl.textContent=r.error||"Unable to change timeframe";}
      poll();setTimeout(function(){applyingConfig=false;},500);
    });
  };
}
function resize(){
  var d=window.devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=Math.max(1,Math.floor(r.width*d));canvas.height=Math.max(1,Math.floor(r.height*d));ctx.setTransform(d,0,0,d,0,0);
  if(adxCanvas&&adxCtx){var ar=adxCanvas.getBoundingClientRect();adxCanvas.width=Math.max(1,Math.floor(ar.width*d));adxCanvas.height=Math.max(1,Math.floor(ar.height*d));adxCtx.setTransform(d,0,0,d,0,0);}
  draw();drawAdx();
}
function draw(){
  var w=canvas.clientWidth,h=canvas.clientHeight;ctx.clearRect(0,0,w,h);ctx.fillStyle="#071018";ctx.fillRect(0,0,w,h);
  if(candles.length<1){ctx.fillStyle="#8ca5b8";ctx.font="14px sans-serif";ctx.fillText("Loading live candles...",18,30);return;}
  var left=52,right=12,top=14,bottom=h-14,view=candles.slice(Math.max(0,candles.length-70)),hi=-Infinity,lo=Infinity,i,c;
  for(i=0;i<view.length;i++){c=view[i];hi=Math.max(hi,Number(c.high));lo=Math.min(lo,Number(c.low));}
  var range=hi-lo||0.0001,step=(w-left-right)/view.length;
  function yp(p){return top+(hi-p)/range*(bottom-top-8);}
  ctx.strokeStyle="rgba(120,190,230,.12)";ctx.lineWidth=1;
  for(i=0;i<6;i++){var y=top+i*(bottom-top)/5;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-right,y);ctx.stroke();ctx.fillStyle="#718798";ctx.font="10px sans-serif";ctx.fillText((hi-i*range/5).toFixed(5),4,y+3);}
  for(i=0;i<view.length;i++){c=view[i];var x=left+i*step+step/2,o=yp(Number(c.open)),cl=yp(Number(c.close)),hh=yp(Number(c.high)),ll=yp(Number(c.low)),up=Number(c.close)>=Number(c.open);ctx.strokeStyle=up?"#35d98a":"#ff5c70";ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(x,hh);ctx.lineTo(x,ll);ctx.stroke();ctx.fillRect(x-Math.max(1,step*.31),Math.min(o,cl),Math.max(2,step*.62),Math.max(2,Math.abs(cl-o)));}
  // Draw confirmed Fractal 3 arrows directly on the main price chart.
  // Marks are time-aligned, so changing timeframe automatically redraws them.
  var marks=Array.isArray(state.fractal_marks)?state.fractal_marks:[];
  for(i=0;i<marks.length;i++){
    var mk=marks[i], mi=-1, j;
    for(j=0;j<view.length;j++){if(Number(view[j].time)===Number(mk.time)){mi=j;break;}}
    if(mi<0)continue;
    var mx=left+mi*step+step/2, my=yp(Number(mk.price)), upMark=String(mk.type)==="UP";
    ctx.fillStyle=upMark?"#35d98a":"#ff5c70";ctx.beginPath();
    if(upMark){ctx.moveTo(mx,my+10);ctx.lineTo(mx-6,my+20);ctx.lineTo(mx+6,my+20);}else{ctx.moveTo(mx,my-10);ctx.lineTo(mx-6,my-20);ctx.lineTo(mx+6,my-20);}
    ctx.closePath();ctx.fill();
  }
  // Highlight the exact fractal candle used by the signal engine.
  var sf=Number(state.signal_fractal_time);
  if(isFinite(sf)){
    for(j=0;j<view.length;j++){
      if(Number(view[j].time)===sf){
        var sx=left+j*step+step/2, sy=yp(Number(state.signal_fractal_price));
        ctx.strokeStyle="#ffd21c";ctx.lineWidth=2;ctx.beginPath();
        ctx.arc(sx,sy,8,0,Math.PI*2);ctx.stroke();
        ctx.fillStyle="#ffd21c";ctx.font="9px sans-serif";
        ctx.fillText("SIGNAL SOURCE",Math.max(left,sx-30),Math.max(10,sy-25));
        break;
      }
    }
  }
}
function drawAdx(){
  if(!adxCanvas||!adxCtx)return;
  var w=adxCanvas.clientWidth,h=adxCanvas.clientHeight;adxCtx.clearRect(0,0,w,h);adxCtx.fillStyle="#071018";adxCtx.fillRect(0,0,w,h);
  var left=52,right=12,top=24,bottom=h-22;adxCtx.fillStyle="#91a8b8";adxCtx.font="11px sans-serif";adxCtx.fillText("ADX +DI / -DI  LENGTH 7  SMOOTHING 14",left,14);
  var ds=Array.isArray(state.dmi_series)?state.dmi_series.slice(Math.max(0,state.dmi_series.length-70)):[];if(ds.length<2){adxCtx.fillStyle="#718798";adxCtx.font="13px sans-serif";adxCtx.fillText("Waiting for ADX DI data...",left,45);return;}
  var mx=25,i,v;for(i=0;i<ds.length;i++){v=ds[i];mx=Math.max(mx,Number(v.plus)||0,Number(v.minus)||0);}var dx=(w-left-right)/(ds.length-1);
  for(i=0;i<=4;i++){var y=bottom-i*(bottom-top)/4;adxCtx.strokeStyle="rgba(120,190,230,.12)";adxCtx.beginPath();adxCtx.moveTo(left,y);adxCtx.lineTo(w-right,y);adxCtx.stroke();adxCtx.fillStyle="#718798";adxCtx.font="9px sans-serif";adxCtx.fillText(String(Math.round(mx*i/4)),4,y+3);}
  drawLine("plus","#35d98a");drawLine("minus","#ff5c70");
  var last=ds[ds.length-1],gap=Math.abs((Number(last.plus)||0)-(Number(last.minus)||0));adxCtx.fillStyle="#35d98a";adxCtx.fillText("+DI "+(Number(last.plus)||0).toFixed(2),left+50,h-6);adxCtx.fillStyle="#ff5c70";adxCtx.fillText("-DI "+(Number(last.minus)||0).toFixed(2),left+145,h-6);adxCtx.fillStyle=gap>=5?"#ffd21c":"#91a8b8";adxCtx.fillText(gap>=5?"WIDE OVERLAP":"OVERLAP",w-105,h-6);
  function drawLine(key,col){adxCtx.strokeStyle=col;adxCtx.lineWidth=2;adxCtx.beginPath();for(var j=0;j<ds.length;j++){var xx=left+j*dx,yy=bottom-(Number(ds[j][key])||0)/mx*(bottom-top);if(j)adxCtx.lineTo(xx,yy);else adxCtx.moveTo(xx,yy);}adxCtx.stroke();}
}
function clocks(){
  var now=new Date(),ids=["local","ny","london","tokyo"],zones=["","America/New_York","Europe/London","Asia/Tokyo"],i,e,s;
  for(i=0;i<ids.length;i++){e=$("clock-"+ids[i]);if(!e)continue;try{s=zones[i]?now.toLocaleTimeString("en-US",{timeZone:zones[i],hour:"2-digit",minute:"2-digit",second:"2-digit"}):now.toLocaleTimeString("en-US",{hour:"2-digit",minute:"2-digit",second:"2-digit"});e.textContent=s;}catch(ex){e.textContent=now.toLocaleTimeString();}}
  var p=Number(state.period||60),r=p-(Math.floor(new Date().getTime()/1000)%p),ce=$("countdown");if(ce)ce.textContent=("0"+Math.floor(r/60)).slice(-2)+":"+("0"+(r%60)).slice(-2);
}
function loadAssets(done){
  xhr("/api/assets","GET",null,function(err,d){
    if(err||!d){if(reasonEl)reasonEl.textContent="Unable to load live asset/timeframe menu";if(done)done();return;}
    var prevA=state.asset||assetEl.value,prevP=Number(state.period||timeframeEl.value||60),groups=d.asset_groups||{},order=["Forex","Crypto","Indices","Commodities","Stocks","Other"],i,j,items,o,g;
    assetEl.innerHTML="";
    for(i=0;i<order.length;i++){items=Array.isArray(groups[order[i]])?groups[order[i]]:[];if(!items.length)continue;g=document.createElement("optgroup");g.label=order[i].toUpperCase();for(j=0;j<items.length;j++){o=document.createElement("option");o.value=items[j];o.textContent=items[j];g.appendChild(o);}assetEl.appendChild(g);}
    if(!assetEl.options.length){items=d.assets||[];for(i=0;i<items.length;i++){o=document.createElement("option");o.value=items[i];o.textContent=items[i];assetEl.appendChild(o);}}
    if(hasOption(assetEl,prevA,false))assetEl.value=prevA;
    timeframeEl.innerHTML="";items=d.timeframes||[];for(i=0;i<items.length;i++){o=document.createElement("option");o.value=String(items[i]);o.textContent=items[i]<60?items[i]+"s":(items[i]%60===0?items[i]/60+"m":items[i]+"s");timeframeEl.appendChild(o);}
    if(hasOption(timeframeEl,prevP,true))timeframeEl.value=String(prevP);assetEl.disabled=false;timeframeEl.disabled=false;if(done)done();
  });
}
function updateFeed(s){
  state=s||{};candles=Array.isArray(state.candles)?state.candles:[];
  priceEl.textContent=state.price!=null?Number(state.price).toFixed(8):"—";feedStatus.textContent=state.feed_connected?"LIVE":"WAITING";
  if(state.asset&&hasOption(assetEl,state.asset,false)&&(pendingAsset===null||state.asset===pendingAsset))assetEl.value=state.asset;
  if(state.period&&hasOption(timeframeEl,state.period,true)&&(pendingTimeframe===null||Number(state.period)===pendingTimeframe))timeframeEl.value=String(state.period);
  if(pendingAsset!==null&&state.asset===pendingAsset)pendingAsset=null;if(pendingTimeframe!==null&&Number(state.period)===pendingTimeframe)pendingTimeframe=null;setSelected();
  draw();drawAdx();
  var conf=Number(state.confidence||0),raw=state.signal||"WAIT",ok=raw!=="WAIT"&&conf>=Number(threshold.value);
  signalEl.textContent=ok?raw:"WAIT";signalEl.className="signal "+(ok?String(raw).toLowerCase():"wait");confidenceEl.textContent=conf+"%";meter.style.width=Math.min(100,conf)+"%";
  var sourceText="";
  if(state.fractal&&state.signal_fractal_time!=null){
    sourceText=" • SOURCE "+state.fractal+" @ "+new Date(Number(state.signal_fractal_time)*1000).toLocaleTimeString();
  }
  if(state.signal_plus_di!=null&&state.signal_minus_di!=null){
    sourceText+=" • +DI "+Number(state.signal_plus_di).toFixed(2)+" / -DI "+Number(state.signal_minus_di).toFixed(2);
  }
  reasonEl.textContent=(ok?state.reason:(raw!=="WAIT"?"Signal below threshold: "+conf+"% • "+state.reason:(state.reason||"Waiting")))+sourceText;
  var ps=Number(state.plus_strength||0),ms=Number(state.minus_strength||0);$("plusSquares").textContent="■■■■■".slice(0,ps)+"□□□□□".slice(0,5-ps);$("minusSquares").textContent="■■■■■".slice(0,ms)+"□□□□□".slice(0,5-ms);
  var di=$("diValues");if(di)di.textContent="+DI "+(state.plus_di==null?"—":state.plus_di)+" • -DI "+(state.minus_di==null?"—":state.minus_di)+" • "+(state.wide_cross?"WIDE X":"OVERLAP");
}
function poll(){xhr("/api/state","GET",null,function(err,s){if(!err&&s)updateFeed(s);else feedStatus.textContent="WAITING";});}
function start(){bind();resize();loadAssets(function(){poll();});poll();clocks();setInterval(poll,1000);setInterval(clocks,1000);window.onresize=resize;}
if(document.readyState==="loading")window.onload=start;else start();
})();