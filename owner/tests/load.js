// Składa kod aplikacji z plików docs/js/*.js w kolejności ze znaczników <script src> w index.html
const fs=require('fs'),path=require('path');
module.exports=()=>{const root=path.join(__dirname,'..','docs'),h=fs.readFileSync(path.join(root,'index.html'),'utf8');return [...h.matchAll(/<script src="(js\/[^"]+)"><\/script>/g)].map(m=>fs.readFileSync(path.join(root,m[1]),'utf8')).join('\n')};
