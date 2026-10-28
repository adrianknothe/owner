// Uruchom: npm i xlsx && node tests/test_portfolio.js   (testuje wycenę walutową, import XTB i renderowanie)
const fs=require('fs'),path=require('path'),assert=require('assert');global.XLSX=require('xlsx');
const el=()=>new Proxy(function(){},{get:(t,k)=>k=='classList'?{toggle(){},add(){},remove(){},contains:()=>false}:k=='style'?{}:k=='dataset'?{}:k=='open'?false:k=='value'?'':k=='checked'?false:k=='files'?[]:k=='length'?0:el(),set:()=>true,apply:()=>el()});
const store={};global.document={querySelector:()=>el(),querySelectorAll:()=>[],documentElement:{},addEventListener(){},createElement:()=>el()};global.getComputedStyle=()=>({getPropertyValue:()=>'#000'});
global.localStorage={getItem:k=>store[k]??null,setItem(k,v){store[k]=v},removeItem(k){delete store[k]}};global.window={};global.Chart=function(){this.destroy=()=>{}};global.fetch=async()=>({json:async()=>({})});global.setInterval=()=>{};global.URL={createObjectURL:()=>''};global.Blob=function(){};global.confirm=()=>true;global.alert=console.log;global.scrollTo=()=>{};
const html=fs.readFileSync(path.join(__dirname,'..','docs','index.html'),'utf8'),js=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].pop()[1];
const book=rows=>{const wb=XLSX.utils.book_new();for(const [n,a] of Object.entries(rows))XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet(a),n);const b=XLSX.write(wb,{type:'buffer',bookType:'xlsx'});return{name:'x.xlsx',lastModified:0,arrayBuffer:async()=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)}};
eval(js+`
const near=(a,b,e=0.01)=>assert(Math.abs(a-b)<e,a+' != '+b);
const ff=(a,b)=>a==b?1:({USD:4,EUR:4.3}[a]/({PLN:1,USD:4,EUR:4.3}[b]||1));
// 1. USD -> PLN, rozdzielenie ceny i waluty
let r=valuePos({vol:10,op:100,pv:3500},120,'USD','PLN',ff);near(r.va,4800);near(r.priceEff,20);near(r.fxEff,14.2857);near(r.total,37.1429);near((1+r.priceEff/100)*(1+r.fxEff/100)-1,r.total/100,1e-6);
// 2. ta sama waluta
r=valuePos({vol:10,op:100,pv:1000},110,'PLN','PLN',ff);assert.strictEqual(r.fxEff,0);near(r.total,10);
// 3. brak danych nie jest zerem
r=valuePos({vol:10,op:100,pv:3500},null,'USD','PLN',ff);assert.strictEqual(r.va,null);assert.strictEqual(r.total,null);
r=valuePos({vol:10,op:100,pv:3500},120,'JPY','PLN',(a,b)=>null);assert.strictEqual(r.va,null);assert(r.note[0].includes('kursu'));
r=valuePos({vol:10,op:100,pv:null},120,'USD','PLN',ff);near(r.va,4800);assert.strictEqual(r.total,null);assert.strictEqual(r.fxEff,null);
// 4. pensy (GBX)
r=valuePos({vol:10,op:4000,pv:null},5000,'GBX','GBP',ff);near(r.vi,500);near(r.priceEff,25);
assert.strictEqual(curOf('CDR.WA',null),'PLN');assert.strictEqual(curOf('AAPL',null),'USD');assert.strictEqual(curOf('FOO.XX',null),null);assert.strictEqual(yh('BRK.B.US'),'BRK-B');assert.strictEqual(yh('VWCE.DE'),'VWCE.DE');
// 5. import: podgląd, błędne wiersze, deduplikacja, stan vs historia
D={results:[{symbol:'AAPL',name:'Apple',price:200,cur:'USD',lv:2,vscore:0,conf:'niska',compl:55,flags:[],reasons:[],atr_pct:2,etf:false,fund:{},above200:true,rsi:50,plan:null,sector:'IT'}],indices:[],news:{},market_news:[],reddit:[],st_trending:[],fx:{USD:{r:4,d:'2026-10-27',src:'Yahoo'},EUR:{r:4.3,d:'2026-10-27',src:'Yahoo'}}};
const f1=book({'Open Position':[['Currency','PLN'],[],['Position','Symbol','Category','Type','Volume','Open Time','Open Price','Market Price','Purchase Value'],[1,'AAPL.US','Stock','BUY',10,'2026-01-02 10:00:00',150,190,6000],[2,'VWCE.DE','ETF','BUY',5,'2026-02-01 10:00:00',120,125,2580],[3,'BAD.US','Stock','BUY',null,'2026-02-01 10:00:00',10,10,10],['Total']],
 'Closed Positions':[['Position','Symbol','Category','Volume','Open Price','Close Time','Gross P/L'],[9,'MSFT.US','Stock',2,400,'2026-03-01 12:00:00',150]],
 'Cash Operations':[['ID','Type','Time','Comment','Symbol','Amount'],[100,'Dividend','2026-04-01 10:00:00','x','AAPL.US',12.5],[101,'Withholding tax','2026-04-01 10:00:00','x','AAPL.US',-1.9],[102,'Deposit','2026-01-01 10:00:00','',null,5000],[103,'Free funds interest','2026-02-01 10:00:00','',null,1]]});
(async()=>{await stage([f1]);const S=STG.files[0];assert.strictEqual(S.acct,'PLN');const o=S.sheets.find(s=>s.kind=='open');assert.strictEqual(o.acc.length,2);assert.strictEqual(o.skip.length,1);assert(o.skip[0].why.includes('ilości'));
 assert.strictEqual(S.sheets.find(s=>s.kind=='cash').other,1);prevHtml();commit('PLN');assert.strictEqual(Object.keys(PF.snap.open).length,2);assert.strictEqual(Object.keys(PF.cash).length,3);
 // ponowny import tego samego pliku – bez duplikatów
 await stage([f1]);commit('PLN');assert.strictEqual(Object.keys(PF.cash).length,3);assert.strictEqual(Object.keys(PF.closed).length,1);
 // starszy plik nie nadpisuje nowszego stanu pozycji
 const old=book({'Open Position':[['Position','Symbol','Category','Type','Volume','Open Time','Open Price','Market Price','Purchase Value'],[7,'TSLA.US','Stock','BUY',1,'2020-01-01 10:00:00',100,100,400]]});await stage([old]);commit('PLN');assert(PF.snap.open[1]&&!PF.snap.open[7]);
 // 6. wycena portfela
 const C=pfCalc();const a=C.H.find(h=>h.y=='AAPL'),e=C.H.find(h=>h.y=='VWCE.DE');
 near(a.V.va,10*200*4);near(a.V.priceEff,33.3333);near(a.V.fxEff,(4/(6000/(10*150))-1)*100);near(e.V.va,5*125*4.3);assert.strictEqual(e.src,'plik XTB');near(e.V.fxEff,(4.3/(2580/(5*120))-1)*100);
 near(C.d12,0,100);assert(C.nk<=C.n);assert.strictEqual(C.real,150);
 D.diag={universe:10,attempted:10,processed:9,skipped:1,cut:false,news:1,reddit:1,stocktwits:false,fx:true,fng:true,minutes:5};SG={cost_pct:0.1,stats:{Wybicie:{n:2,n5:2,w5:50,a5:1.2,x5:0.4,ev:2,t1:1,stop:0,amb:1,mfe:3,mae:-1}},signals:[{sym:'AAPL',ts:1,setup:'Wybicie',px:1,e:1,s:1,t1:2,r5:1.1,ex:'amb',n:5}]};
 drawPf();drawSig();drawCtx();drawOv();drawRec();drawScan();drawEtf();drawWatch();console.log('ALL OK')})().catch(e=>{console.error('FAIL',e);process.exit(1)});`);
