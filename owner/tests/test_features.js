// node tests/test_features.js  (wymaga: npm i xlsx) – porównywarka, ryzyko portfela, zmiany/alerty, tryb inwestora, RSI vs backend
const fs=require('fs'),path=require('path'),assert=require('assert');global.XLSX=require('xlsx');
const el=()=>new Proxy(function(){},{get:(t,k)=>k=='classList'?{toggle(){},add(){},remove(){},contains:()=>false}:k=='style'?{}:k=='dataset'?{}:k=='open'?false:k=='value'?'':k=='checked'?false:k=='files'?[]:k=='length'?0:el(),set:()=>true,apply:()=>el()});
const store={};global.document={querySelector:()=>el(),querySelectorAll:()=>[],documentElement:{},addEventListener(){},createElement:()=>el(),hidden:false};global.addEventListener=()=>{};global.getComputedStyle=()=>({getPropertyValue:()=>'#000'});
global.localStorage={getItem:k=>store[k]??null,setItem(k,v){store[k]=v},removeItem(k){delete store[k]}};global.window={};global.Chart=function(){this.destroy=()=>{}};global.fetch=async u=>({json:async()=>({})});global.setInterval=()=>{};global.URL={createObjectURL:()=>''};global.Blob=function(){};global.confirm=()=>true;global.alert=console.log;global.scrollTo=()=>{};
const js=require('./load')(),fx=JSON.parse(fs.readFileSync(path.join(__dirname,'rsi_fixture.json'),'utf8'));global.FIX=fx;
eval(js+`
const near=(a,b,e=0.01)=>assert(Math.abs(a-b)<e,a+' != '+b);
// RSI: front = backend (Wilder, ten sam seed)
const r=rsi(FIX.c);FIX.rsi.forEach((v,i)=>{if(i>=14&&v!=null)near(r[i],v,0.11)});
// porównywarka: wspólna oś dat, rebase, statystyki, brak interpolacji
const AA=cmpAlign([{t:[1,2,3,4,5],c:[10,11,12,13,14]},{t:[2,3,5,6],c:[20,22,21,25]},null],10);assert.deepStrictEqual(AA.dates,[2,3,5]);assert.deepStrictEqual(AA.series[0],[11,12,14]);assert.deepStrictEqual(AA.series[1],[20,22,21]);assert.strictEqual(AA.series[2],null);
assert.strictEqual(cmpStats([1,2,3]),null);const up=Array.from({length:30},(_,i)=>100+i),SS=cmpStats(up);near(SS.ret,29);assert.strictEqual(SS.mdd,0);const dn=cmpStats([...up,90]);assert(dn.mdd<-20);
// ryzyko portfela: koncentracja, look-through ETF, braki sektora
FD={QQQ:{etf:{hold:[['NVDA','Nvidia',9],['MSFT','Microsoft',8]],sectors:{technology:50,healthcare:10}}}};NT={NVDA:{kind:'trading',acct:'IKE'}};
const RR=pfRisk([{y:'NVDA',v:300,cur:'USD',etf:false,sec:'Information Technology'},{y:'QQQ',v:500,cur:'USD',etf:true,sec:''},{y:'XYZ',v:200,cur:'PLN',etf:false,sec:''}]);
near(RR.top1,50);near(RR.top3,100);near(RR.eff,1/(0.09+0.25+0.04));near(RR.look.NVDA.d,30);near(RR.look.NVDA.e,4.5);near(RR.semi.d+RR.semi.e,34.5);near(RR.sec.technology,30+25);near(RR.secUnk,20);near(RR.cur.USD,80);near(RR.kind.trading,30);near(RR.kind.nieoznaczone,70);assert.strictEqual(pfRisk([]),null);
assert.strictEqual(geoOf('CDR.WA'),'Polska (GPW)');assert.strictEqual(geoOf('VWCE.DE'),'Europa (poza Polską)');assert.strictEqual(geoOf('AAPL'),'USA');
// zmiany od ostatniej wizyty + alerty
D={updated_at:Date.now()/1e3-60,results:[{symbol:'AAA',price:105,lv:3,plan:{setup:'Trend'},earnings_days:3,fund:{rec:'buy',target:120}},{symbol:'BBB',price:50,lv:1,plan:null,earnings_days:null,fund:null}],diag:{cut:false,reddit:1,stocktwits:false,fx:true}};
wl=['AAA','BBB','ZZZ'];PF=null;SB={ts:1,st:{AAA:{lv:2,pl:null,ed:null,rec:'hold',tg:100},BBB:{lv:2,pl:null,ed:null}}};AL=[{id:1,sym:'AAA',kind:'above',price:100,fired:null},{id:2,sym:'BBB',kind:'above',price:60,fired:null}];
checkAlerts();assert(AL[0].fired&&!AL[1].fired);const ch=changes(),TT=ch.map(c=>c.t+':'+c.s);
['Nowe setupy:AAA','Poprawa sygnału:AAA','Pogorszenie sygnału:BBB','Zbliżające się wyniki:AAA','Konsensus analityków:AAA','Przekroczone poziomy:AAA','Nieaktualne dane:ZZZ'].forEach(k=>assert(TT.includes(k),'brak '+k+' w '+TT));assert(TT.some(t=>t.startsWith('Nieaktualne dane:')&&t.endsWith(':'))); // StockTwits niedostępny
saveSeen();assert(JSON.parse(store.seen).st.AAA.lv==3);drawChg();
// tryb inwestora i notatki
D.results[0].hi52_pct=-40;FD={AAA:{m:{payout:95,de:200,revg:15,fcf:-1,pe:50}}};const HH=invHtml('AAA');assert(HH.includes('Payout')&&HH.includes('Ujemny free cash flow')&&HH.includes('Wzrost przychodów')&&HH.includes('poniżej szczytu'));
NT.AAA={review:'2020-01-01'};assert(invHtml('AAA').includes('Termin ponownego sprawdzenia'));
// porównywarka renderuje się bez błędów także przy brakach danych
CM=['AAA','BBB'];FD={};drawCmp().then(()=>{console.log('FEATURES OK')}).catch(e=>{console.error('FAIL',e);process.exit(1)});
// ręczne mapowanie kolumn (nierozpoznane nagłówki) i częściowe zamknięcia
(async()=>{const book=rows=>{const wb=XLSX.utils.book_new();for(const [n,a] of Object.entries(rows))XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet(a),n);const b=XLSX.write(wb,{type:'buffer',bookType:'xlsx'});return{name:'m.xlsx',lastModified:5,arrayBuffer:async()=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)}};
 const f=book({'Open Position':[['Instrument','Ile sztuk','Kurs wejścia'],['AAPL.US',3,100],['MSFT.US',2,200]],'Closed Positions':[['Position','Symbol','Gross P/L','Close Time','Volume'],[7,'AAPL.US',10,'2026-02-01 10:00:00',1],[7,'AAPL.US',25,'2026-02-02 10:00:00',2]]});
 let F=await parseFile(f);const o=F.sheets.find(x=>x.kind=='open');assert(o.missing.includes('vol')&&o.missing.includes('op')&&o.acc.length==0);
 F=await parseFile(f,{'Open Position':{vol:o.hdr.indexOf('Ile sztuk'),op:o.hdr.indexOf('Kurs wejścia')}});const o2=F.sheets.find(x=>x.kind=='open');assert.strictEqual(o2.missing.length,0);assert.strictEqual(o2.acc.length,2);assert.strictEqual(o2.acc[0].vol,3);
 const c=F.sheets.find(x=>x.kind=='closed');assert.strictEqual(c.acc.length,2);assert.strictEqual(new Set(c.acc.map(r=>r.id)).size,2);  // dwa częściowe zamknięcia tej samej pozycji nie zlewają się
 // EU: waluta w tabeli, regiony, akumulacja
 D={results:[{symbol:'SAP.DE',name:'SAP',mkt:'DE',cur:'EUR',price:200.5,exch:'XETRA',index:'DAX',lv:3,vscore:1,conf:'niska',compl:55,dvol:90,flags:[],reasons:[],plan:null,comps:{tech:[1]},change_pct:1,week_pct:1,month_pct:1,rsi:50,adx:20,vol_ratio:1,atr_pct:2,rs:null,hi52_pct:-3}],indices:[],news:{},market_news:[],reddit:[],st_trending:[],market:{name:'Byczy',a50:60,adv:50,buy:20,sell:10},market_by:{DE:{name:'Mieszany',a50:50,n:80}},fx:{}};
 assert(tr(D.results[0]).includes('EUR'));assert.strictEqual(accDist('Vanguard FTSE All-World UCITS ETF (USD) Accumulating'),'Akumulujący');assert.strictEqual(accDist('iShares Core DAX UCITS ETF (DE) EUR (Dist)'),'Dystrybuujący');assert.strictEqual(accDist('SPDR S&P 500'),null);
 drawOv();drawScan();console.log('FEATURES2 OK')})().catch(e=>{console.error('FAIL2',e);process.exit(1)});
`);
