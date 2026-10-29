/* ---------- start ---------- */
const drawAll=()=>{drawOv();drawRec();drawScan();drawEtf();drawWatch();drawPf();drawCtx();checkAlerts();drawChg();drawLt();if($('#cmp').classList.contains('on'))drawCmp()};head('#head',drawScan);head('#ehead',drawEtf);head('#whead',drawWatch);
['q','fv','fi','fx','fm'].forEach(i=>$('#'+i).oninput=drawScan);['eq','ev'].forEach(i=>$('#'+i).oninput=drawEtf);['rmode','rtype','rkind','rconf','rnew'].forEach(i=>$('#'+i).oninput=drawRec);['cap','risk','maxw','cost','frac'].forEach(i=>$('#'+i).oninput=()=>{drawRec();if($('#inst').classList.contains('on')&&by(cur))$('#dplan').innerHTML=planHtml(by(cur))});
$('#wbtn').onclick=()=>{const v=$('#wadd').value.trim().toUpperCase();if(v&&!wl.includes(v)){wl.push(v);sv();drawWatch()}$('#wadd').value=''};
async function load(){try{const j=await(await fetch('results.json?'+Date.now())).json();if(j.updated_at!=window._u){window._u=j.updated_at;D=j;D.results.forEach(x=>x.up1=x.plan&&x.lv>=3?x.plan.up1:null);loadFD().then(drawPf);drawAll();loadSig()}
 ;setMeta(j)}catch(e){$('#meta').textContent='Brak danych – uruchom skan w zakładce Actions.'}}
load();setInterval(load,60000);
