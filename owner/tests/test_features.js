// node tests/test_features.js  (wymaga: npm i xlsx) – porównywarka, ryzyko portfela, zmiany/alerty, tryb inwestora, RSI vs backend
const fs=require('fs'),path=require('path'),assert=require('assert');global.XLSX=require('xlsx');
const el=()=>new Proxy(function(){},{get:(t,k)=>k=='classList'?{toggle(){},add(){},remove(){},contains:()=>false}:k=='style'?{}:k=='dataset'?{}:k=='open'?false:k=='value'?'':k=='checked'?false:k=='files'?[]:k=='length'?0:el(),set:()=>true,apply:()=>el()});
const store={};global.document={querySelector:()=>el(),querySelectorAll:()=>[],documentElement:{},addEventListener(){},createElement:()=>el(),hidden:false};global.addEventListener=()=>{};global.innerWidth=1200;global.getComputedStyle=()=>({getPropertyValue:()=>'#000'});
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

// zakładka długoterminowa i wiadomości z pamięci
(async()=>{D={results:[{symbol:'AAA',name:'Alfa',mkt:'US',sector:'IT',exch:'NASDAQ',etf:false,lt:{s:80,l:'Silne',a:'Gromadź',cov:90,p:{quality:90,growth:80,value:60,safety:70,income:null,trend:90},why:['ROE 28%'],fl:[]}},{symbol:'ETFX',etf:true,lt:null},{symbol:'BBB',name:'Beta',mkt:'DE',etf:false,lt:null}],news:{},market_news:[],indices:[]};NW={AAA:{ts:1,items:[{title:'X <b>',url:'javascript:alert(1)',src:'S',ts:1,sent:0}]}};
 drawLt();const nh=newsFor('AAA');assert(nh.includes('&lt;b&gt;')&&!nh.includes('javascript:alert')&&nh.includes('href="#"'));assert(newsFor('ZZZ').includes('Brak zapisanych'));console.log('FEATURES3 OK')})().catch(e=>{console.error('FAIL3',e);process.exit(1)});

// procenty do celu, stan wejścia, nazwa metryki względnej
(async()=>{const px={symbol:'P',name:'P',lv:3,vscore:1,conf:'wysoka',compl:90,flags:[],reasons:[],sma20:9,price:10,cur:'USD',etf:false,rs:8.04,rsi:50,adx:20,change_pct:1,week_pct:1,month_pct:1,vol_ratio:1,atr_pct:2,hi52_pct:-3,dvol:10,
 plan:{setup:'Wybicie',quality:70,entry:10,stop:9.7,t1:10.45,t2:10.9,horizon:'3–10 sesji',atr_pct:2,state:'teraz',pull:null,zlo:9.9,zhi:10,up1:4.5,up2:9,dn:-3,rng10:6.3}};
 assert(pp(8.04).includes('+8.0 p.p.')||pp(8.04).includes('+8,0 p.p.'));assert(action(px).includes('Wejście teraz')&&action(px).includes('+4,5%')||action(px).includes('+4.5%'));
 const w={...px,plan:{...px.plan,state:'czekaj',pull:9.8,alt:{entry:9.8,stop:9.5,t1:10.25,t2:10.7,up1:4.6,up2:9.2}}};assert(action(w).includes('Poczekaj')&&action(w).includes('9.8'));
 D={results:[px],news:{},market_news:[],indices:[]};NW={};const h=planHtml(px);assert(h.includes('Potencjał do celu')&&h.includes('wejście teraz')&&h.includes('Brak wystarczających danych historycznych'));assert(planHtml(w).includes('Lepsze wejście'));
 BT={stats:{Wybicie:{all:{ev:100,t1:40,stop:30,amb:10}}}};assert(planHtml(px).includes('cel 1 przed stopem w 40%'));
 assert(tr(px).includes('+4,5%')||tr(px).includes('+4.5%'));assert(tr(px).includes('p.p.'));assert(COLS.some(c=>c[1]=='Wynik vs rynek 3M')&&COLS.some(c=>c[0]=='up1'));
 drawRec();drawScan();console.log('FEATURES4 OK')})().catch(e=>{console.error('FAIL4',e);process.exit(1)});

// zaawansowany wykres, czytanie wykresu, scenariusze Monte Carlo
(async()=>{const n=300,c=[],o=[],hh=[],ll=[],v=[],t=[];let p=100;for(let i=0;i<n;i++){const d=Math.sin(i/9)*2+0.15;o.push(p);p=p+d;c.push(+p.toFixed(2));hh.push(+(Math.max(o[i],p)+1).toFixed(2));ll.push(+(Math.min(o[i],p)-1).toFixed(2));v.push(1000+i);t.push(20000+i)}
 H={t,c,o,h:hh,l:ll,v};const Lv=levels(H);assert(Lv.up.every(z=>z.p>Lv.last)&&Lv.dn.every(z=>z.p<Lv.last)&&Lv.up.length<=3);
 const R=readChart(H,null);assert(R.some(r=>r.startsWith('Trend'))&&R.some(r=>r.includes('RSI'))&&R.some(r=>r.includes('MACD'))&&R.some(r=>r.includes('Bollinger')));assert(readChart({c:[1,2,3],t:[1,2,3],v:[1,1,1]},null)[0].includes('Za mało'));
 D={results:[],indices:[],news:{},market_news:[]};cur='AAA';RN=252;CT='candle';drawChart();CT='line';tgl.macd=1;tgl.bb=1;tgl.fib=1;drawChart();RN=-1;drawChart();
 const mc={H:10,sc:{neutral:{pt:38,ps:50,pa:3,pn:9,pu:49,er:-0.1,q:[-8,-3,0,3,8],mu:0},trend:{pt:50,ps:38,pa:3,pn:9,pu:60,er:0.2,q:[-6,-1,2,5,10],mu:0.2},reversal:{pt:25,ps:62,pa:3,pn:10,pu:35,er:-0.4,q:[-10,-5,-2,1,6],mu:-0.2}},fan:[[.95,.94,.93,.93,.92,.92,.91,.91,.9,.9],[.98,.98,.97,.97,.97,.96,.96,.96,.96,.95],[1,1,1,1,1,1,1,1,1,1],[1.02,1.03,1.03,1.04,1.04,1.05,1.05,1.05,1.06,1.06],[1.05,1.06,1.07,1.08,1.09,1.1,1.1,1.11,1.12,1.12]]};
 const X={symbol:'AAA',price:100,plan:{entry:100,stop:96,t1:106,t2:112},mc,mcl:{pu:55,p20:12,q:[-30,-10,5,20,45]},cf:[4,6,[['cena powyżej SMA200',true],['RSI poniżej 75',false]]],exch:'NASDAQ',cur:'USD'};
 D.results=[X];const sh=scenHtml(X);assert(sh.includes('Monte Carlo')&&sh.includes('Neutralny')&&sh.includes('Kalibracja modelu: brak')&&sh.includes('12 miesięcy')&&sh.includes('nie prognoza'));
 BT={calib:[{pred:38,real:35,n:120}]};assert(scenHtml(X).includes('przewidziane 38% → zrealizowane 35%'));BT=null;
 assert(scenHtml({symbol:'Z'}).includes('Brak symulacji'));drawScen();FD={AAA:{ts:1,m:{target:120,tlow:90,thigh:140,rec:'buy',analysts:12,gm:40,om:20,fcf:2e9}}};
 assert(consHtml('AAA').includes('+20,0%')||consHtml('AAA').includes('+20.0%'));assert(ratiosHtml('AAA').includes('Marża brutto'));assert(consHtml('ZZZ').includes('Brak danych'));
 fillInst('AAA');fillFd('AAA');console.log('FEATURES5 OK')})().catch(e=>{console.error('FAIL5',e);process.exit(1)});
`);
