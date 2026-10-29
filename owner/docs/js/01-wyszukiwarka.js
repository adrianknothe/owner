/* ---------- wyszukiwarka ---------- */
$('#gs').oninput=()=>{const q=$('#gs').value.trim().toUpperCase(),b=$('#gsr');if(!q){b.style.display='none';return}
 const m=D.results.filter(x=>x.symbol.startsWith(q)).concat(D.results.filter(x=>!x.symbol.startsWith(q)&&(x.name||'').toUpperCase().includes(q))).slice(0,8);
 b.innerHTML=m.map(x=>`<div data-s="${x.symbol}"><span><b>${x.symbol}</b> <span class="mute">${esc(x.name)}</span></span>${vb(x)}</div>`).join('')||`<div data-s="${esc(q)}"><span>Otwórz ${esc(q)}</span></div>`;b.style.display='block';
 $$('#gsr div').forEach(d=>d.onclick=()=>{b.style.display='none';$('#gs').value='';open_(d.dataset.s)})};
$('#gs').onkeydown=e=>{if(e.key=='Enter'){const d=$('#gsr div');if(d)d.click()}};document.addEventListener('click',e=>{if(!e.target.closest('.sw'))$('#gsr').style.display='none'});
