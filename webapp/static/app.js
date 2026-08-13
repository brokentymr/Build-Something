'use strict';
const $ = (s, r=document) => r.querySelector(s);
const screen = $('#screen');
const backBtn = $('#back');
let stack = [];
let AI_MODE = '';

async function api(path, method='GET', body) {
  const opt = { method, headers: {} };
  if (body) { opt.headers['Content-Type']='application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  return r.json();
}
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function go(fn, keep) { if(!keep) stack.push(fn); render(); }
function render(){ const fn = stack[stack.length-1]; backBtn.classList.toggle('hidden', stack.length<=1); fn&&fn(); }
backBtn.onclick = () => { if(stack.length>1){stack.pop(); render();} };

// ---------------------------------------------------------------- landing
function landing(){
  screen.innerHTML = `
    <h1 class="hero">What would you<br>like to build?</h1>
    <p class="lede">A guided path from an idea to a complete, buildable PDF — cut lists, drawings and a step-by-step sequence.</p>
    <button class="bigbtn" id="b-new">
      <div class="ic">✨</div><div class="t">Something New</div>
      <div class="s">Describe it, answer a few questions, get your package.</div>
    </button>
    <button class="bigbtn" id="b-resume">
      <div class="ic">📚</div><div class="t">Pick up where you left off</div>
      <div class="s">Open a project from your library.</div>
    </button>`;
  $('#b-new').onclick = () => go(newBuild);
  $('#b-resume').onclick = () => go(library);
}

// ---------------------------------------------------------------- new
let quickTypes = [];
async function newBuild(){
  if(!quickTypes.length){ const c = await api('/api/catalog'); quickTypes = c.nodes; AI_MODE=c.ai_mode; $('#aimode').textContent = 'AI · '+AI_MODE; }
  screen.innerHTML = `
    <p class="eyebrow">Tell us the idea</p>
    <h1 class="hero" style="font-size:23px">What are you making?</h1>
    <textarea class="free" id="free" placeholder="e.g. a low concrete-look coffee table for my living room"></textarea>
    <p class="muted" style="margin:14px 0 8px">Or start from a type:</p>
    <div class="chips" id="quick">${quickTypes.map(n=>`<button class="chip" data-node="${n.id}">${esc(n.display_name)}</button>`).join('')}</div>
    <button class="btn" id="submit" style="margin-top:22px">Continue</button>
    <div id="intake-out"></div>`;
  $('#quick').querySelectorAll('.chip').forEach(c=> c.onclick=()=>startWith(c.dataset.node));
  $('#submit').onclick = async () => {
    const text = $('#free').value.trim();
    if(!text){ return; }
    const p = await api('/api/projects/new','POST',{title:text.slice(0,40)});
    const res = await api('/api/projects/'+p.id+'/intake','POST',{text});
    handleIntake(p.id, res);
  };
}
async function startWith(node){
  const p = await api('/api/projects/new','POST',{title:'New '+node.replace('_',' ')});
  await api('/api/projects/'+p.id+'/pick','POST',{node});
  openProject(p.id);
}
function handleIntake(pid, res){
  if(res.outcome==='offer_template'){
    // a template is offered, never assumed — "a shoe bench with a lower shelf"
    // once keyword-matched the floating shelf and would have been built as one
    const out = $('#intake-out');
    out.innerHTML = `<div class="card"><div class="q"><p class="prompt">${esc(res.message)}</p>
      <div class="opts">
        <button class="opt" id="use-t">Use the ${esc(res.node_display)} template
          <span class="muted">— verified, fewer questions</span></button>
        <button class="opt" id="design-it">Design mine from my description
          <span class="muted">— tailored to exactly what I wrote</span></button>
      </div></div></div>`;
    $('#use-t').onclick = async () => {
      await api('/api/projects/'+pid+'/pick','POST',{node:res.node});
      openProject(pid);
    };
    $('#design-it').onclick = () => {
      if(res.extracted && res.extracted.length) go(()=>confirmScreen(pid,res));
      else openProject(pid);
    };
    return;
  }
  if(res.outcome==='resolved'){
    if(res.extracted && res.extracted.length) go(()=>confirmScreen(pid,res));
    else openProject(pid);
    return;
  }
  const out = $('#intake-out');
  if(res.outcome==='disambiguate'){
    out.innerHTML = `<div class="card"><div class="q"><p class="prompt">${esc(res.message)}</p>
      <div class="opts">${res.options.map((o,i)=>`<button class="opt" data-v="${o.value}">${esc(o.note||o.value)}${o.term?` <span class="muted">(${esc(o.term)})</span>`:''}</button>`).join('')}</div></div></div>`;
    out.querySelectorAll('.opt').forEach(b=> b.onclick=async()=>{
      const v=b.dataset.v;
      if(quickTypes.find(n=>n.id===v)){ await api('/api/projects/'+pid+'/pick','POST',{node:v}); openProject(pid); }
      else { // construction choice -> map to a node then continue
        const node = v==='cast_slab'||v==='troweled_overlay' ? 'coffee_table' : v;
        await api('/api/projects/'+pid+'/pick','POST',{node}); openProject(pid);
      }
    });
  } else {
    out.innerHTML = `<div class="notice">${esc(res.message||'We could not place that yet.')}</div>`;
  }
}

// ---------------------------------------------------------------- confirm (measure 1)
function confirmScreen(pid, res){
  const conf = Math.round((res.confidence||0)*100);
  screen.innerHTML = `
    <p class="eyebrow">${esc(res.node_display||'')} · understood ${conf}%</p>
    <h1 class="hero" style="font-size:23px">Here's what we caught</h1>
    <p class="lede">Pulled straight from your description — you can change any of it later. We'll only ask about what's still open.</p>
    <div class="known"><div class="h">From your description</div>
      ${res.extracted.map(e=>`<div class="row"><span>${esc(e.label)}</span><span class="v">${esc(e.value)}</span></div>`).join('')}</div>
    <div class="measurebar"><span class="m done">1 · Understood</span><span class="m">2 · Audit</span><span class="m">3 · Gates</span></div>
    <button class="btn go" id="cont">Looks right — continue</button>
    <button class="btn alt" id="edit">Start over</button>`;
  $('#cont').onclick=()=>openProject(pid);
  $('#edit').onclick=()=>{ stack=[landing,newBuild]; render(); };
}

// ---------------------------------------------------------------- library
async function library(){
  const {projects} = await api('/api/library');
  screen.innerHTML = `<p class="eyebrow">Your library</p><h1 class="hero" style="font-size:23px">Ongoing projects</h1>
    <div class="lib">${projects.length? projects.map(p=>`
      <div class="item" data-id="${p.id}">
        <div class="thumb">${p.status==='released'?'📄':'🪚'}</div>
        <div class="meta"><div class="t">${esc(p.title)}</div>
          <div class="s">${esc(p.node==='__designed__'?'designed for you':(p.node?p.node.replace('_',' '):'choosing type'))} · ${p.photo_count} photo(s)</div></div>
        <div class="badge ${p.status==='released'?'released':''}">${esc(p.status)}</div>
      </div>`).join('') : '<p class="muted">No projects yet. Start something new.</p>'}</div>`;
  screen.querySelectorAll('.item').forEach(it=> it.onclick=()=>openProject(it.dataset.id));
}

// ---------------------------------------------------------------- open/route
async function openProject(pid){
  const st = await api('/api/projects/'+pid);
  AI_MODE = st.ai_mode; $('#aimode').textContent='AI · '+st.ai_mode;
  const route = () => {
    if(st.status==='released' || st.document) return resultScreen(pid, st);
    // "You can leave and come back; it keeps going" — so coming back has to land
    // on the design in progress, not on the questions that started it.
    if(st.status==='generating') return generate(pid);
    if(st.status==='photos') return photosScreen(pid, st);
    return configureScreen(pid, st);
  };
  stack.push(route); render();
}

// ---------------------------------------------------------------- photos
function photosScreen(pid, st){
  const grid = () => `<div class="photogrid">
      ${st.photos.map(p=>`<div class="ph" style="background-image:url('${p.data_url}')"></div>`).join('')}
      <label class="add">+<input type="file" accept="image/*" capture="environment" hidden id="file"></label>
    </div>`;
  screen.innerHTML = `
    <p class="eyebrow">${esc(st.node_display||'')}</p>
    <h1 class="hero" style="font-size:23px">Share inspiration photos</h1>
    <p class="lede">A few reference shots of the look you're after. This shapes the finish and proportions — you can skip it.</p>
    ${st.structural_notice?`<div class="notice">⚠︎ ${esc(st.structural_notice)}</div>`:''}
    <div id="g">${grid()}</div>
    <button class="btn go" id="cont">Continue</button>
    <button class="btn alt" id="skip">Skip for now</button>`;
  const bind = () => { const f=$('#file'); if(f) f.onchange = async e=>{
      const file=e.target.files[0]; if(!file) return;
      const reader=new FileReader();
      reader.onload=async()=>{ await api('/api/projects/'+pid+'/photos','POST',{mime:file.type,data_url:reader.result});
        const s2=await api('/api/projects/'+pid); st.photos=s2.photos; $('#g').innerHTML=grid(); bind(); };
      reader.readAsDataURL(file);
  };};
  bind();
  const proceed = async () => {
    await api('/api/projects/'+pid+'/photos-done','POST',{});
    let s2 = await api('/api/projects/'+pid);
    if(s2.planning){ await planning(pid); s2 = await api('/api/projects/'+pid); }
    stack.pop(); stack.push(()=>configureScreen(pid,s2)); render();
  };
  $('#cont').onclick = proceed; $('#skip').onclick = proceed;
}

// ---------------------------------------------------------------- configure
function configureScreen(pid, st){
  const turn = st.turn;
  const pr = st.progress || {answered:0,total:1};
  const pct = Math.round(100*pr.answered/Math.max(1,pr.total));
  let sel = {}; // field -> value for this turn
  const knownHtml = st.known && st.known.length ? `<div class="known"><div class="h">What we know so far</div>
      ${st.known.map(k=>`<div class="row"><span>${esc(k.label)}</span><span class="v">${esc(k.value)}</span></div>`).join('')}</div>` : '';

  if(!turn){
    // Numbers are editable here: changing one and rebuilding is the whole of
    // "make it 90 inches instead", and the answer store has always been versioned.
    const editable = (st.known||[]).filter(k=>k.numeric);
    screen.innerHTML = `<p class="eyebrow">${esc(st.node_display)}</p>
      <h1 class="hero" style="font-size:23px">${st.document?'Change something and rebuild':'Ready to generate'}</h1>
      ${editable.length?`<div class="known"><div class="h">Dimensions — edit any of these</div>
        ${editable.map(k=>`<div class="row"><span>${esc(k.label)}</span>
          <input class="numedit" data-f="${esc(k.field)}" value="${esc(k.value)}" inputmode="decimal"></div>`).join('')}</div>`:knownHtml}
      ${(st.known||[]).some(k=>!k.numeric)?`<div class="known"><div class="h">Other choices</div>
        ${st.known.filter(k=>!k.numeric).map(k=>`<div class="row"><span>${esc(k.label)}</span><span class="v">${esc(k.value)}</span></div>`).join('')}</div>`:''}
      <button class="btn go" id="gen">${st.document?'Rebuild the package':'Generate build package'}</button>`;
    $('#gen').onclick=async()=>{
      const changed={};
      screen.querySelectorAll('.numedit').forEach(el=>{
        const was=(st.known.find(k=>k.field===el.dataset.f)||{}).value;
        if(el.value.trim() && el.value.trim()!==was) changed[el.dataset.f]=parseFloat(el.value);
      });
      if(Object.keys(changed).length) await api('/api/projects/'+pid+'/answer','POST',{answers:changed});
      generate(pid);
    };
    return;
  }
  const qHtml = turn.questions.map(q=>{
    let body='';
    if(q.type==='choice'){
      body = `<div class="opts">${q.options.map(o=>`<button class="opt" data-f="${q.field}" data-v="${esc(o.value)}">${esc(o.label)}</button>`).join('')}</div>`;
    } else {
      body = `<div class="chips">${q.numeric_presets.map(v=>`<button class="chip" data-f="${q.field}" data-v="${v}">${v}${q.unit==='in'?'"':''}</button>`).join('')}
        <div class="custom"><input type="number" placeholder="custom" data-cf="${q.field}"> <span class="muted" style="align-self:center">${esc(q.unit)}</span></div></div>`;
    }
    return `<div class="card q"><p class="prompt">${esc(q.prompt)} ${q.required?'':'<span class="muted">(optional)</span>'}${q.tailored?'<span class="tailored">✨ tailored</span>':''}</p>
      ${body}${q.explain?`<button class="linkish" data-x="${q.id}">Not sure?</button><div class="explain hidden" id="x-${q.id}">${esc(q.explain)}</div>`:''}</div>`;
  }).join('');

  screen.innerHTML = `<p class="eyebrow">${esc(st.node_display)} · step ${pr.answered+1}</p>
    <div class="progress"><i style="width:${pct}%"></i></div>
    ${knownHtml}${qHtml}
    <button class="btn" id="cont" disabled>Continue</button>
    ${st.can_generate?`<button class="btn go" id="gen" style="margin-top:10px">Generate now</button>`:''}`;

  const check = () => { const need = turn.questions.filter(q=>q.required).map(q=>q.field);
    $('#cont').disabled = !need.every(f=> f in sel); };
  screen.querySelectorAll('.opt').forEach(b=> b.onclick=()=>{
    screen.querySelectorAll(`.opt[data-f="${b.dataset.f}"]`).forEach(x=>x.classList.remove('sel'));
    b.classList.add('sel'); sel[b.dataset.f]=b.dataset.v; check();
  });
  screen.querySelectorAll('.chip[data-f]').forEach(b=> b.onclick=()=>{
    screen.querySelectorAll(`.chip[data-f="${b.dataset.f}"]`).forEach(x=>x.classList.remove('sel'));
    b.classList.add('sel'); sel[b.dataset.f]=Number(b.dataset.v);
    const ci=screen.querySelector(`input[data-cf="${b.dataset.f}"]`); if(ci) ci.value=''; check();
  });
  screen.querySelectorAll('input[data-cf]').forEach(inp=> inp.oninput=()=>{
    screen.querySelectorAll(`.chip[data-f="${inp.dataset.cf}"]`).forEach(x=>x.classList.remove('sel'));
    if(inp.value!=='') sel[inp.dataset.cf]=Number(inp.value); else delete sel[inp.dataset.cf]; check();
  });
  screen.querySelectorAll('.linkish').forEach(b=> b.onclick=()=> $('#x-'+b.dataset.x).classList.toggle('hidden'));
  $('#cont').onclick = async () => {
    const s2 = await api('/api/projects/'+pid+'/answer','POST',{answers:sel});
    stack[stack.length-1] = ()=>configureScreen(pid,s2); render();
  };
  const g=$('#gen'); if(g) g.onclick=()=>generate(pid);
}

// ---------------------------------------------------------------- planning
// A build with no template has no question graph, so the agent writes one for
// this object. It takes a few seconds and it is worth saying why.
async function planning(pid){
  screen.innerHTML = `<h1 class="hero" style="font-size:23px">Working out what to ask you</h1>
    <p class="lede">Reading your description and photos, so we only ask what actually
      changes the design.</p><div class="spinner"></div>`;
  const res = await api('/api/projects/'+pid+'/plan','POST',{});
  if(res.planned===false){
    screen.innerHTML = `<div class="notice">We could not scope that one: ${esc(res.error||'unknown')}</div>
      <button class="btn alt" id="home">Back to start</button>`;
    $('#home').onclick=()=>{ stack=[landing]; render(); };
    throw new Error(res.error||'planning failed');
  }
}

// ---------------------------------------------------------------- generate
const PHASES = [
  ['planning',   'Scoping the build'],
  ['designing',  'Designing it'],
  ['reviewing',  'Reviewing the design'],
  ['repairing',  'Fixing what does not hold up'],
  ['writing',    'Writing the build instructions'],
  ['drawing',    'Drawing plans, sections and joints'],
  ['paginating', 'Laying out the document'],
  ['gates',      'Checking every number and drawing'],
];

async function generate(pid){
  const draw = (phase, detail, failed) => {
    let at = PHASES.findIndex(p=>p[0]===phase);
    if(phase==='done') at = PHASES.length;
    screen.innerHTML = `<h1 class="hero" style="font-size:23px">Measure thrice, cut once</h1>
      <p class="lede">${esc(detail || 'Auditing before we commit the spec.')}</p>
      ${failed?'':'<div class="spinner"></div>'}
      <ul class="steps">${PHASES.map(([k,label],i)=>
        `<li class="${i<at?'done':i===at?'active':''}">${esc(label)}</li>`).join('')}</ul>
      <p class="muted" style="margin-top:16px">A design this app has not seen before
        usually takes five to fifteen minutes — it draws the piece, checks its own work
        and fixes what it finds, and the harder pieces take more rounds of that. You can
        leave and come back; it keeps going without you.</p>`;
  };
  draw('planning','');

  const res = await api('/api/projects/'+pid+'/generate','POST',{});
  if(res.released===false){
    const st = await api('/api/projects/'+pid);
    stack[stack.length-1]=()=>{ configureScreen(pid, st);
      const b=document.createElement('div'); b.className='notice';
      b.textContent='⤺ '+(res.message||'A few more answers needed')+(res.missing&&res.missing.length?': '+res.missing.join(', '):'');
      screen.prepend(b); };
    return render();
  }

  // follow the job — every line shown is a phase the worker actually reached
  for(;;){
    await new Promise(r=>setTimeout(r, 1500));
    let job;
    try { job = (await api('/api/projects/'+pid+'/job')).job; }
    catch(e){ continue; }
    if(!job || !job.status) continue;
    if(job.status==='failed'){
      draw(job.phase, '', true);
      const note=document.createElement('div'); note.className='notice';
      note.textContent = job.error || 'This one did not come together.';
      screen.prepend(note);
      // The design is drawn fresh each run, so a failure is often just this run.
      // Offer the thing most likely to work before offering to start over.
      const retry=document.createElement('button'); retry.className='btn';
      retry.textContent='Try again';
      retry.onclick=()=>generate(pid);
      screen.appendChild(retry);
      const again=document.createElement('button'); again.className='btn alt';
      again.textContent='Change my answers';
      again.onclick=async()=>{ const st=await api('/api/projects/'+pid);
        stack[stack.length-1]=()=>configureScreen(pid,st); render(); };
      screen.appendChild(again);
      return;
    }
    if(job.status==='done') break;
    draw(job.phase, job.detail);
  }
  const st = await api('/api/projects/'+pid);
  stack[stack.length-1]=()=>resultScreen(pid, st, res); render();
}

// ---------------------------------------------------------------- result
function resultScreen(pid, st, res){
  const doc = st.document || {summary:res&&res.summary, gates:res&&res.gates, pages:res&&res.pages, pdf_url:'/api/projects/'+pid+'/document.pdf'};
  const s = doc.summary||{};
  const gates = doc.gates||[];
  screen.innerHTML = `
    <p class="eyebrow" style="color:var(--ok)">✓ Released · Rev ${esc(st.revision||'A')}</p>
    <h1 class="hero" style="font-size:23px">${esc(st.node_display||'Build')} package ready</h1>
    <div class="summary">
      <div class="stat"><div class="n">${s.pieces??'—'}</div><div class="l">pieces · ${s.part_types??'—'} types</div></div>
      <div class="stat"><div class="n">${doc.pages??'—'}</div><div class="l">document pages</div></div>
      <div class="stat"><div class="n">${s.weight?('~'+Math.round(s.weight)):'—'}</div><div class="l">lb (est.)</div></div>
      <div class="stat"><div class="n">${s.sheets?Object.values(s.sheets).reduce((a,b)=>a+b,0):'—'}</div><div class="l">${esc(s.stock_word||'stock')} to buy</div></div>
    </div>
    <div class="gates"><p class="eyebrow">Release gates</p>
      ${gates.map(g=>`<div class="gate"><span class="dot ${g.passed?'':'fail'}"></span>${esc(g.name)}</div>`).join('')}</div>
    ${s.derived?`<p class="eyebrow">Derived, not asked</p><div class="derived">${s.derived.map(d=>`<div class="d"><div class="dl">${esc(d.label)}: ${esc(d.value)}</div><div class="db">${esc(d.basis)}</div></div>`).join('')}</div>`:''}
    <p class="eyebrow" style="margin-top:18px">Your document · ${doc.pages||''} pages</p>
    <a class="pdfwrap coverwrap" href="${doc.pdf_url}" target="_blank">
      <img src="/api/projects/${pid}/cover.png" alt="document cover"></a>
    <a class="btn" href="${doc.pdf_url}" download>Download PDF</a>
    <button class="btn alt" id="revise">Change something and rebuild</button>
    <button class="btn alt" id="home">Back to start</button>`;
  $('#revise').onclick=async()=>{ const fresh=await api('/api/projects/'+pid);
    stack[stack.length-1]=()=>configureScreen(pid,fresh); render(); };
  $('#home').onclick=()=>{ stack=[landing]; render(); };
}

// boot (with deep-link routing for shareable links / previews)
(async()=>{
  try{const c=await api('/api/catalog'); AI_MODE=c.ai_mode; $('#aimode').textContent='AI · '+c.ai_mode; quickTypes=c.nodes;}catch(e){}
  const p=new URLSearchParams(location.search), view=p.get('view'), pid=p.get('pid');
  if(pid){
    const st=await api('/api/projects/'+pid);
    if(view==='result') stack=[()=>resultScreen(pid,st)];
    else if(view==='photos') stack=[()=>photosScreen(pid,st)];
    else if(view==='configure') stack=[()=>configureScreen(pid,st)];
    else if(view==='confirm'){
      const res={node_display:st.node_display, confidence:1.0,
        extracted:(st.known||[]).map(k=>({label:k.label,value:k.value}))};
      stack=[()=>confirmScreen(pid,res)];
    }
    else if(view==='measures'){
      const steps=['Auditing completeness (2 judges)','Solving geometry (pure)','Deriving parts & joinery','Nesting sheets','Drawing plans & sections','Paginating document','Running release gates (measure 3)'];
      stack=[()=>{ screen.innerHTML=`<h1 class="hero" style="font-size:23px">Measure thrice, cut once</h1>
        <p class="lede">Auditing before we commit the spec.</p><div class="spinner"></div>
        <ul class="steps">${steps.map((s,k)=>`<li class="${k<4?'done':k===4?'active':''}">${s}</li>`).join('')}</ul>`; }];
    }
    else stack=[()=> (st.document?resultScreen(pid,st): st.status==='photos'?photosScreen(pid,st):configureScreen(pid,st))];
    return render();
  }
  if(view==='new'){ stack=[landing, newBuild]; return render(); }
  if(view==='library'){ stack=[landing, library]; return render(); }
  stack=[landing]; render();
})();
