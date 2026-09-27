/* Local application chart controls. No network libraries or analytical approvals. */
'use strict';
function numeric(v) {
  if (typeof v !== 'number' && typeof v !== 'string') return null;
  if (typeof v === 'string' && !/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(v.trim())) return null;
  const n = Number(v); return Number.isFinite(n) ? n : null;
}
function chartData(rows, kind, x, y) {
  let invalid = 0;
  const points = rows.map((row, i) => {
    const value = numeric(row[y]);
    const xv = kind === 'scatter' ? numeric(row[x]) : i + 1;
    if (value === null || xv === null) { invalid++; return null; }
    return {x:xv, y:value, label:x ? String(row[x] ?? '(missing)') : String(i+1), row:i+1};
  });
  const valid = points.filter(Boolean);
  if (!valid.length) throw Error('No valid numeric values for this selection. Choose other columns.');
  if (kind === 'bar' && rows.length > 40) throw Error('Individual-row bars are limited to 40 rows for readable labels. Choose a histogram or scatter plot, or load a smaller reviewed result.');
  if (kind !== 'histogram') return {points, invalid, valid:valid.length};
  const lo = Math.min(...valid.map(p=>p.y)), hi = Math.max(...valid.map(p=>p.y));
  const width = hi === lo ? 0 : (hi-lo)/10;
  if (!Number.isFinite(width) || (hi !== lo && width === 0)) throw Error('Numeric range cannot be binned safely.');
  const bins = Array.from({length:width ? 10 : 1}, (_,i)=>({x:i+1,y:0,label:width ? `${lo+i*width} ≤ value ${i===9?'≤':'<'} ${lo+(i+1)*width}` : String(lo)}));
  valid.forEach(p=>bins[width ? Math.min(9,Math.floor((p.y-lo)/width)) : 0].y++);
  return {points:bins,invalid,valid:valid.length};
}
if (typeof module !== 'undefined') module.exports = {numeric,chartData};
if (typeof document !== 'undefined') {
  const $ = id=>document.getElementById(id);
  let data = null;
  const option = (value,label)=>{const o=document.createElement('option');o.value=value;o.textContent=label;return o;};
  const clear = ()=>{data=null;$('chart').replaceChildren();$('tableWrap').replaceChildren();$('counts').textContent='';$('evidence').textContent='No source loaded.';$('x').replaceChildren();$('y').replaceChildren();};
  const resetSource = ()=>{clear();$('table').replaceChildren(option('','Load database to list tables'));$('status').textContent='Source changed. Load data to continue.';};
  $('source').onchange=()=>{$('path').value=$('source').value;$('upload').value='';resetSource();};
  $('path').oninput=()=>{$('upload').value='';resetSource();};
  $('upload').onchange=()=>{$('path').value='';$('source').value='';resetSource();};
  $('key').oninput=()=>{clear();$('status').textContent='Array key changed. Load data again.';};
  $('table').onchange=()=>{clear();$('status').textContent='Table changed. Load data again.';};
  async function load() {
    clear();$('message').textContent='';$('status').textContent='Reading locally…';$('load').disabled=true;
    ['source','path','upload','table','key'].forEach(id=>$(id).disabled=true);
    try {
      const body={table:$('table').value,records_key:$('key').value};
      const file=$('upload').files[0];
      if(file){
        if(file.size>5*1024*1024)throw Error('Upload limit is 5 MiB. For larger files up to 20 MiB, copy into the project and enter its relative path.');
        const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
        for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        body.filename=file.name;body.content=btoa(binary);
      } else {body.path=$('path').value.trim();if(!body.path)throw Error('Select a dataset or browse for a file.');}
      const response=await fetch('/api/explore',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const result=await response.json();if(!response.ok)throw Error(result.error || 'Unable to read data');
      const selected=$('table').value;$('table').replaceChildren(option('','Select a table…'),...(result.tables||[]).map(t=>option(t,t)));$('table').value=selected;
      if(result.needs_table){$('status').textContent='Select a SQLite table, then click Load data.';return;}
      data=result;
      $('status').textContent=`${result.source}: ${result.rows.length.toLocaleString()} rows loaded.${result.truncated?' FIRST 5,000 ONLY — source has additional rows.':' Complete dataset loaded.'}`;
      $('evidence').textContent=`Source: ${result.source} | SHA-256: ${result.sha256} | ${result.notice} ${result.truncated?'Charts describe only the first 5,000 rows, not the full population.':''}`;
      const numericFields=result.fields.filter(f=>result.rows.some(r=>numeric(r[f])!==null));
      $('x').replaceChildren(option('','Row number'),...result.fields.map(f=>option(f,f)));
      $('y').replaceChildren(...numericFields.map(f=>option(f,f)));
      if(numericFields.length){$('x').value=numericFields[0];$('y').value=numericFields[1]||numericFields[0];}
      const table=document.createElement('table'),head=table.createTHead().insertRow();
      result.fields.forEach(f=>{const th=document.createElement('th');th.textContent=f;head.append(th);});
      const tb=table.createTBody();result.rows.slice(0,100).forEach(row=>{const tr=tb.insertRow();result.fields.forEach(f=>{const td=tr.insertCell();const v=row[f];td.textContent=v===null?'null':v===undefined?'(absent)':typeof v==='object'?JSON.stringify(v):String(v);});});
      $('tableWrap').append(table);render();
    }catch(e){$('status').textContent='Load failed.';$('message').textContent=e.message;}finally{$('load').disabled=false;['source','path','upload','table','key'].forEach(id=>$(id).disabled=false);}
  }
  function render(){
    $('chart').replaceChildren();$('tooltip').hidden=true;$('message').textContent='';$('counts').textContent='';if(!data)return;
    const kind=$('kind').value,x=$('x').value,y=$('y').value;
    $('x').disabled=kind==='histogram';
    try{
      if(!y)throw Error('No numeric columns available. Nested objects remain available in the data table.');
      // Scatter can use an explicit row index without mutating source records.
      const rows=kind==='scatter'&&!x?data.rows.map((r,i)=>({...r,'':i+1})):data.rows;
      const model=chartData(rows,kind,x,y), pts=model.points.filter(Boolean);
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 900 440');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${kind}: ${y} by ${x||'row number'}`);
      const add=(tag,attrs,text)=>{const el=document.createElementNS(svg.namespaceURI,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,v));if(text!==undefined)el.textContent=text;svg.append(el);return el;};
      const bar=kind==='bar'||kind==='histogram';
      let xmin=bar?.5:Math.min(...pts.map(p=>p.x)),xmax=bar?model.points.length+.5:Math.max(...pts.map(p=>p.x));
      let ymin=Math.min(...pts.map(p=>p.y)),ymax=Math.max(...pts.map(p=>p.y));
      if(bar){ymin=Math.min(0,ymin);ymax=Math.max(0,ymax);}
      if(xmin===xmax){xmin-=.5;xmax+=.5;}if(ymin===ymax){const pad=Math.abs(ymin)*.05||1;ymin-=pad;ymax+=pad;}
      if(!Number.isFinite(xmax-xmin)||!Number.isFinite(ymax-ymin)||xmax===xmin||ymax===ymin)throw Error('Numeric range cannot be represented safely on this chart.');
      const sx=n=>80+(n-xmin)/(xmax-xmin)*770,sy=n=>350-(n-ymin)/(ymax-ymin)*300;
      const fmt=n=>Number(n.toPrecision(5)).toLocaleString('en',{maximumSignificantDigits:5});
      for(let i=0;i<=5;i++){const v=ymin+(ymax-ymin)*i/5;add('line',{x1:80,x2:850,y1:sy(v),y2:sy(v),stroke:'#e2e7ed'});add('text',{x:70,y:sy(v)+5,'text-anchor':'end','font-size':13,fill:'#526174'},fmt(v));}
      add('path',{d:'M80 50V350H850',fill:'none',stroke:'#617187'});
      add('text',{x:80,y:25,'font-size':15,fill:'#1d2939'},kind==='histogram'?'Count of rows':y+' (source units)');
      add('text',{x:465,y:430,'text-anchor':'middle','font-size':14,fill:'#1d2939'},kind==='histogram'?y+' — equal-width bins; hover for bounds':kind==='line'?'Row number (source order)':x||'Row number');
      const tooltip=(el,p)=>{const tip=$('tooltip');const show=e=>{tip.textContent=kind==='histogram'?`${p.label}: ${p.y} rows`:`Row ${p.row} · ${p.label} · ${y}: ${p.y}`;tip.hidden=false;const rect=el.getBoundingClientRect();tip.style.left=Math.max(5,Math.min(innerWidth-310,e.clientX||rect.x))+'px';tip.style.top=Math.max(5,Math.min(innerHeight-80,(e.clientY||rect.y)+15))+'px';};el.setAttribute('tabindex','0');el.setAttribute('aria-label',`${p.label}: ${p.y}`);el.onmouseenter=show;el.onfocus=show;el.onmouseleave=el.onblur=()=>{tip.hidden=true;};};
      if(kind==='line'){let d='',gap=true;model.points.forEach(p=>{if(!p){gap=true;return;}d+=`${gap?'M':'L'}${sx(p.x)},${sy(p.y)} `;gap=false;});add('path',{d,fill:'none',stroke:'#2167b4','stroke-width':2});}
      pts.forEach(p=>{let el;if(bar){const w=770/(xmax-xmin)*(kind==='histogram'?.98:.65);el=add('rect',{x:sx(p.x)-w/2,y:Math.min(sy(0),sy(p.y)),width:w,height:Math.abs(sy(0)-sy(p.y)),fill:'#2167b4'});}else el=add('circle',{cx:sx(p.x),cy:sy(p.y),r:3,fill:'#2167b4'});tooltip(el,p);});
      if(kind==='bar'){pts.forEach(p=>add('text',{x:sx(p.x),y:365,transform:`rotate(50 ${sx(p.x)} 365)`,'font-size':12,fill:'#526174'},p.label.length>12?p.label.slice(0,11)+'…':p.label));}
      else if(kind==='histogram'){pts.forEach(p=>add('text',{x:sx(p.x),y:375,'text-anchor':'middle','font-size':12,fill:'#526174'},`Bin ${p.x}`));}
      else for(let i=0;i<=5;i++){const v=xmin+(xmax-xmin)*i/5;add('text',{x:sx(v),y:375,'text-anchor':'middle','font-size':13,fill:'#526174'},fmt(v));}
      $('chart').append(svg);$('counts').textContent=`${model.valid.toLocaleString()} valid rows · ${model.invalid.toLocaleString()} missing/non-numeric rows omitted${kind==='line'?' (gaps retained)':''}. ${data.truncated?'PARTIAL SOURCE: first 5,000 rows only.':''}`;
    }catch(e){$('message').textContent=e.message;}
  }
  $('load').onclick=load;['kind','x','y'].forEach(id=>$(id).onchange=render);
  fetch('/api/files').then(r=>{if(!r.ok)throw Error();return r.json();}).then(d=>d.files.forEach(f=>$('source').append(option(f,f)))).catch(()=>{$('status').textContent='Could not list project files. Browse for a local file instead.';});
}
