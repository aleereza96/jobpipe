'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const state = {view:'jobs', filter:'shortlisted', search:'', offset:0, jobs:[], config:null, run:'idle', detail:null, request:0};
const labels = {shortlisted:'Shortlisted',applied:'Applied',skipped:'Skipped',low_score:'Low match'};
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let toastTimer;
function toast(message, error=false){$('#toast').textContent=message;$('#toast').className='toast'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),6500);}
async function api(path, data){const options=data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Jobpipe':'1'},body:JSON.stringify(data)};const response=await fetch(path,options);const result=await response.json();if(!response.ok)throw new Error(result.error||'Something went wrong');return result;}
function safely(fn){return async event=>{try{await fn(event);}catch(error){toast(error.message,true);}};}
function safeLink(url){try{const value=new URL(url);return ['http:','https:'].includes(value.protocol)?value.href:null;}catch{return null;}}
function date(value){if(!value)return '';const d=new Date(value);return Number.isNaN(d.getTime())?'':d.toLocaleDateString(undefined,{month:'short',day:'numeric'});}
function empty(title,body,action=''){return `<div class="empty"><div class="empty-symbol">✧</div><h3>${escapeHTML(title)}</h3><p>${escapeHTML(body)}</p>${action}</div>`;}
function table(jobs){if(!jobs.length)return empty(state.view==='followups'?'All caught up':'A little room for possibility',state.view==='followups'?'No follow-ups are due. Mark an opportunity as applied and it will appear here after seven days.':state.search?'No roles match your search. Try another company or keyword.':'No jobs in this view yet. Start a search or add a posting to your inbox.');return `<table class="job-table"><thead><tr><th>Role & company</th><th>Location</th><th>Match</th><th>${state.view==='followups'?'Applied':'Status'}</th><th aria-label="Details"></th></tr></thead><tbody>${jobs.map(j=>`<tr><td><div class="role-cell"><span class="company-avatar">${escapeHTML((j.company||'?').slice(0,2).toUpperCase())}</span><div><button class="job-title" data-job="${escapeHTML(j.id)}">${escapeHTML(j.title||'Untitled role')}</button><div class="company-name">${escapeHTML(j.company||'Company not listed')}</div></div></div></td><td class="location">${escapeHTML(j.location||'Not listed')}</td><td><span class="score ${j.score<70?'low':''}">${escapeHTML(j.score)}<small>/100</small></span></td><td>${state.view==='followups'?escapeHTML(date(j.applied_at)):`<span class="status ${escapeHTML(j.status)}">${escapeHTML(labels[j.status]||j.status)}</span>`}</td><td><button class="row-arrow" data-job="${escapeHTML(j.id)}" aria-label="View ${escapeHTML(j.title)}">↗</button></td></tr>`).join('')}</tbody></table>`;}
async function loadJobs(){const request=++state.request;const followups=state.view==='followups';const params=new URLSearchParams(followups?{due:'1'}:{status:state.filter,q:state.search,offset:String(state.offset)});if(!followups&&document.querySelector('#review-queue')?.checked)params.set('review','1');const data=await api('/api/jobs?'+params);if(request!==state.request)return;state.pageSize=data.limit||100;state.jobs=data.jobs;const target=followups?'#followups-list':'#jobs-list';$(target).innerHTML=table(data.jobs);if(!followups){$('#result-count').textContent=data.total?`${data.offset+1}–${data.offset+data.jobs.length} of ${data.total} opportunities`:'No opportunities in this view';$('#prev-page').disabled=state.offset===0;$('#next-page').disabled=state.offset+state.pageSize>=data.total;}}
async function loadStats(){const data=await api('/api/stats');$('#stat-total').textContent=data.total.toLocaleString();$('#stat-shortlisted').textContent=data.counts.shortlisted||0;$('#stat-applied').textContent=data.counts.applied||0;$('#stat-due').textContent=data.due;$('#nav-count').textContent=data.counts.shortlisted||0;$('#nav-due').textContent=data.due;}
async function loadSettings(){const data=await api('/api/settings');state.config={required_keywords:[], sponsorship_required:false, unknown_policy:'review', review_limit:10, min_relevance:4, role_keywords:[], include_unknown_location:true, include_relocation_outside_locations:false, exclude_german_required:false, ...data.config};if(!cvDirty){$('#cv-text').value=data.cv;$('#cv-format').value=data.cv_format||'md';}const form=$('#settings-form');for(const [name,value] of Object.entries(state.config)){const input=form.elements.namedItem(name);if(!input)continue;if(input.type==='checkbox')input.checked=value;else input.value=Array.isArray(value)?value.join(', '):value??'';}form.elements.greenhouse.value=(data.config.boards?.greenhouse||[]).join(', ');form.elements.lever.value=(data.config.boards?.lever||[]).join(', ');}
async function showView(view){if(!['jobs','followups','inbox','boards','alerts','cv','settings'].includes(view))view='jobs';state.view=view;$$('.view').forEach(el=>el.classList.add('hidden'));$('#'+view+'-view').classList.remove('hidden');$$('.nav').forEach(el=>el.classList.toggle('active',el.dataset.view===view));$('#crumb').textContent={jobs:'Opportunities',followups:'Follow-ups',inbox:'Add a posting',alerts:'Job alerts',boards:'Job sources',cv:'My CV',settings:'Preferences'}[view];history.replaceState(null,'','#'+view);if(['jobs','followups'].includes(view))await loadJobs();if(view==='boards')await loadBoards();if(view==='alerts')await loadAlerts();if(['cv','settings'].includes(view))await loadSettings();}
function setFilter(filter){state.filter=filter;state.offset=0;$$('.tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.filter===filter));return showView('jobs');}
function markdown(text){const container=document.createElement('div');for(const line of text.split('\n')){if(!line.trim())continue;const h=line.match(/^(#{1,3})\s+(.+)/);const p=document.createElement(h?(h[1].length===1?'h3':'h'+h[1].length):'p');if(h&&h[1].length===1)p.className='draft-title';p.textContent=h?h[2]:line;container.append(p);}return container.innerHTML;}
async function openJob(id){const job=state.jobs.find(j=>j.id===id);if(!job)return;state.detail=job;const a=job.analysis||{};const url=safeLink(job.url);const list=(title,values)=>Array.isArray(values)&&values.length?`<h3>${title}</h3><ul>${values.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul>`:'';$('#job-detail').innerHTML=`<span class="score ${job.score<70?'low':''}">${escapeHTML(job.score)}<small>/100 MATCH</small></span><h1 id="detail-title">${escapeHTML(job.title)}</h1><p class="meta">${escapeHTML(job.company)} · ${escapeHTML(job.location||'Location not listed')}</p><div class="detail-actions">${url?`<a class="primary" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Open posting ↗</a>`:''}${job.status==='shortlisted'?'<button class="secondary" id="mark-applied">Mark as applied</button>':''}${job.status==='applied'?`<span class="status applied">Applied ${escapeHTML(date(job.applied_at))} · Follow-up ${escapeHTML(date(job.follow_up_at))}</span>`:''}</div><div class="analysis-box"><h2>Why this could fit</h2><p>${escapeHTML(a.summary||a.skip||'This posting was filtered before AI scoring.')}</p>${list('Matches',a.matches)}${list('Gaps to consider',a.gaps)}${a.visa_or_relocation_signal?`<p>Visa / relocation signal: ${escapeHTML(a.visa_or_relocation_signal)}</p>`:''}</div><div class="draft-header"><h2>Your application draft</h2><button id="copy-draft" class="subtle-button hidden">Copy draft</button><button id="generate-cv-pdf" class="subtle-button hidden">Generate tailored CV PDF</button></div><div id="draft-content" class="draft loading">Loading draft…</div>`;$('#job-drawer').classList.remove('hidden');$('#drawer-backdrop').classList.remove('hidden');document.body.style.overflow='hidden';$('#close-drawer').focus();const data=await api('/api/draft?'+new URLSearchParams({id}));if(state.detail?.id!==id)return;state.draft=data.text;$('#draft-content').classList.remove('loading');$('#draft-content').innerHTML=data.text?markdown(data.text):empty('No draft for this role','Drafts are created when a job passes your match score and filters.');$('#copy-draft').classList.toggle('hidden',!data.text);$('#generate-cv-pdf').classList.toggle('hidden',!data.text);}
function closeDrawer(){$('#job-drawer').classList.add('hidden');$('#drawer-backdrop').classList.add('hidden');document.body.style.overflow='';const id=state.detail?.id;state.detail=null;const button=$$('[data-job]').find(el=>el.dataset.job===id);button?.focus();}
async function pollRun(){const data=await api('/api/run');const counts=data.counts;$('#search-counts').textContent=counts?('Found '+counts.found+' · Passed filters '+counts.passed+' · Sent to AI '+counts.sent+' · Shortlisted '+counts.shortlisted):'';const wasRunning=['running','stopping'].includes(state.run);state.run=data.state;const running=['running','stopping'].includes(data.state);$$('.start-search').forEach(b=>{b.disabled=running;b.querySelector('span').textContent=running?'Search in progress…':'Find opportunities';});$('#stop-search').classList.toggle('hidden',!running);$('#stop-search').disabled=data.state==='stopping';$('#run-state').textContent={idle:'Idle',running:'In progress',stopping:'Stopping…',completed:'Finished',failed:'Needs attention',stopped:'Stopped'}[data.state];$('#run-caption').textContent=data.state==='failed'?'The search stopped with an error. Check the activity below before trying again.':data.state==='completed'?'Search finished. Check the totals below for any jobs that need a retry.':data.started?'Started '+new Date(data.started).toLocaleTimeString():'Start a search to collect, score, and draft applications.';const logs=$('#run-logs');const stick=logs.scrollHeight-logs.scrollTop-logs.clientHeight<60;logs.textContent=data.logs.join('\n')||'Your progress will appear here.';if(stick)logs.scrollTop=logs.scrollHeight;$('#save-cv').disabled=running;$('#save-settings').disabled=running;if(running&&!wasRunning)$('#activity-panel').classList.remove('hidden');if(wasRunning&&!running){await loadStats();if(['jobs','followups'].includes(state.view))await loadJobs();}}
async function checkAuth(){const button=$('#check-auth');button.disabled=true;try{const data=await api('/api/auth');$('#auth-message').textContent=data.message;$('#auth-label').textContent=data.ready?'Connected':'Sign-in needed';}finally{button.disabled=false;}}
async function loadBoards() {
  const boards = await api('/api/boards');
  const list = $('#boards-list');
  list.replaceChildren();
  const hosts = {greenhouse: 'job-boards.greenhouse.io', lever: 'jobs.lever.co'};
  for (const [kind, host] of Object.entries(hosts)) {
    for (const slug of boards[kind] || []) {
      const row = document.createElement('li');
      const url = 'https://' + host + '/' + encodeURIComponent(slug);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'subtle-button';
      remove.textContent = 'Remove';
      remove.addEventListener('click', safely(async () => {
        await api('/api/boards/remove', {url});
        await loadBoards();
      }));
      row.append(kind + ' / ' + slug + ' ', remove);
      list.append(row);
    }
  }
  if (!list.children.length) list.textContent = 'No saved boards.';
}

const boardForm = $('#boards-form');
const boardInput = boardForm.elements.url;
const boardSave = $('#boards-save');
let previewedBoard = '';
boardInput.addEventListener('input', () => {
  previewedBoard = '';
  boardSave.disabled = true;
  $('#boards-preview').replaceChildren();
  $('#boards-status').textContent = '';
});
boardForm.addEventListener('submit', safely(async event => {
  event.preventDefault();
  const url = boardInput.value;
  boardSave.disabled = true;
  $('#boards-preview').replaceChildren();
  $('#boards-status').textContent = 'Checking board…';
  try {
    const result = await api('/api/boards/preview', {url});
    if (url !== boardInput.value) return;
    previewedBoard = url;
    $('#boards-status').textContent = result.count + ' open listings. Your location filters apply during searches.';
    for (const job of result.jobs) {
      const item = document.createElement('li');
      item.textContent = [job.title, job.location].filter(Boolean).join(' · ');
      $('#boards-preview').append(item);
    }
    boardSave.disabled = false;
  } catch (error) {
    if (url === boardInput.value) $('#boards-status').textContent = error.message;
  }
}));
boardSave.addEventListener('click', safely(async () => {
  const url = previewedBoard;
  if (!url || url !== boardInput.value) return;
  boardSave.disabled = true;
  try {
    await api('/api/boards/save', {url});
    await loadBoards();
    toast('Source saved for your next search.');
  } finally {
    boardSave.disabled = url !== previewedBoard;
  }
}));

async function loadAlerts() {
  const {configured, accounts, leads} = await api('/api/gmail');
  $('#gmail-connect').disabled = !configured;
  $('#gmail-sync').disabled = !configured || !accounts.length;
  $('#gmail-status').textContent = configured
    ? 'Connected accounts sync when you start a search.'
    : 'Set up the Google OAuth Desktop client file first. See Gmail job alerts in the Jobpipe README.';
  $('#gmail-accounts').replaceChildren();
  for (const account of accounts) {
    const row = document.createElement('p');
    row.textContent = account.email + ' · ' + (account.synced
      ? new Date(account.synced).toLocaleString() : 'Ready to import') + ' ';
    const disconnect = document.createElement('button');
    disconnect.className = 'secondary';
    disconnect.textContent = 'Disconnect';
    disconnect.addEventListener('click', safely(async () => {
      await api('/api/gmail/disconnect', {email: account.email});
      await loadAlerts();
    }));
    row.append(disconnect);
    $('#gmail-accounts').append(row);
  }
  $('#gmail-leads').replaceChildren();
  for (const lead of leads) {
    const row = document.createElement('div');
    const title = document.createElement('a');
    title.href = lead.url;
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    title.textContent = lead.title;
    const detail = document.createElement('p');
    detail.textContent = lead.source + ' · ' + (lead.ready ? 'Description available' : 'Needs description');
    row.append(title, detail);
    if (!lead.ready) {
      const form = document.createElement('form');
      const description = document.createElement('textarea');
      description.required = true;
      description.maxLength = 12000;
      description.placeholder = 'Paste the job description';
      description.setAttribute('aria-label', 'Job description for ' + lead.title);
      const add = document.createElement('button');
      add.className = 'secondary';
      add.textContent = 'Queue for scoring';
      form.append(description, add);
      form.addEventListener('submit', safely(async event => {
        event.preventDefault();
        await api('/api/gmail/description', {id: lead.id, description: description.value});
        await loadAlerts();
        toast('Posting queued for the next search.');
      }));
      row.append(form);
    }
    row.append(document.createElement('hr'));
    $('#gmail-leads').append(row);
  }
  if (!leads.length) $('#gmail-leads').textContent = 'Imported job alerts will appear here.';
}

$('#gmail-connect').addEventListener('click', safely(async () => {
  const result = await api('/api/gmail/connect', {});
  location.assign(result.url);
}));
$('#gmail-sync').addEventListener('click', safely(async () => {
  const button = $('#gmail-sync');
  button.disabled = true;
  $('#gmail-status').textContent = 'Importing job alerts…';
  try {
    const result = await api('/api/gmail/sync', {});
    await loadAlerts();
    $('#gmail-status').textContent = [
      result.added + ' new alerts imported.', ...result.errors
    ].join(' ');
  } finally {
    button.disabled = false;
  }
}));

$$('.nav').forEach(b=>b.addEventListener('click',safely(()=>showView(b.dataset.view))));
$$('[data-go]').forEach(b=>b.addEventListener('click',safely(()=>showView(b.dataset.go))));
$$('[data-filter]').forEach(b=>b.addEventListener('click',safely(()=>setFilter(b.dataset.filter))));
$('.brand').addEventListener('click',safely(async event=>{event.preventDefault();await showView('jobs');}));
$('#connection').addEventListener('click',safely(async()=>{await showView('settings');await checkAuth();}));
let searchTimer;$('#job-search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(safely(async()=>{state.search=$('#job-search').value;state.offset=0;await loadJobs();}),220);});
$('#prev-page').addEventListener('click',safely(async()=>{state.offset=Math.max(0,state.offset-(state.pageSize||100));await loadJobs();}));$('#next-page').addEventListener('click',safely(async()=>{state.offset+=(state.pageSize||100);await loadJobs();}));
async function downloadTailoredCv(button, job) {
  button.disabled = true;
  button.textContent = 'Generating PDF…';
  try {
    const response = await fetch('/api/cv/pdf', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Jobpipe': '1'},
      body: JSON.stringify({id: job.id})
    });
    if (!response.ok) throw new Error((await response.json()).error || 'Could not generate the CV PDF.');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'tailored-cv.pdf';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } finally {
    button.disabled = false;
    button.textContent = 'Generate tailored CV PDF';
  }
}
document.addEventListener('click', safely(async event => {
  if (event.target.id === 'generate-cv-pdf' && state.detail) {
    await downloadTailoredCv(event.target, state.detail);
  }
}));
document.addEventListener('click',safely(async event=>{const button=event.target.closest('[data-job]');if(button)await openJob(button.dataset.job);if(event.target.id==='copy-draft'){await navigator.clipboard.writeText(state.draft);toast('Draft copied. Review the details before using it.');}if(event.target.id==='mark-applied'){const id=state.detail.id;await api('/api/applied',{id});toast('Marked applied. Follow-up set for seven days from now.');await loadStats();await loadJobs();closeDrawer();}}));
$('#close-drawer').addEventListener('click',closeDrawer);$('#drawer-backdrop').addEventListener('click',closeDrawer);document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();if(e.key==='Tab'&&!$('#job-drawer').classList.contains('hidden')){const items=[...$('#job-drawer').querySelectorAll('button:not([disabled]),a[href]')].filter(el=>!el.classList.contains('hidden'));const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){last.focus();e.preventDefault();}else if(!e.shiftKey&&document.activeElement===last){first.focus();e.preventDefault();}}});
$$('.start-search').forEach(b=>b.addEventListener('click',safely(async()=>{b.disabled=true;try{await api('/api/run/start',{});$('#activity-panel').classList.remove('hidden');await pollRun();toast('Search started. You can keep browsing.');}finally{b.disabled=['running','stopping'].includes(state.run);}})));
$('#show-activity').addEventListener('click',()=>$('#activity-panel').classList.toggle('hidden'));$('#close-activity').addEventListener('click',()=>$('#activity-panel').classList.add('hidden'));$('#stop-search').addEventListener('click',safely(async()=>{await api('/api/run/stop',{});await pollRun();toast('Stopping the search. Completed jobs are saved.');}));
$('#inbox-form').addEventListener('submit',safely(async e=>{e.preventDefault();const b=e.target.querySelector('button[type=submit]');b.disabled=true;try{await api('/api/inbox',Object.fromEntries(new FormData(e.target)));e.target.reset();toast('Posting added. Start a search to score it.');}finally{b.disabled=false;}}));
const cvEditor = $('#cv-text');
const cvFormat = $('#cv-format');
const cvFile = $('#cv-file');
const cvResults = $('#cv-review-results');
const cvReviewStatus = $('#cv-review-status');
let cvDirty = false;
let cvRevision = 0;

function cvChanged(clearReview = true) {
  cvDirty = true;
  cvRevision += 1;
  $('#cv-file-status').textContent = 'Unsaved changes.';
  if (clearReview) {
    cvResults.replaceChildren();
    cvReviewStatus.textContent = '';
  }
}

cvEditor.addEventListener('input', () => cvChanged());
cvFormat.addEventListener('change', () => cvChanged());
cvFile.addEventListener('change', safely(async () => {
  const file = cvFile.files[0];
  cvFile.value = '';
  if (!file) return;
  const format = file.name.toLowerCase().split('.').pop();
  if (!['md', 'tex'].includes(format) || file.size > 400000) {
    throw new Error('Choose a Markdown (.md) or LaTeX (.tex) file under 400 KB.');
  }
  const revision = cvRevision;
  const content = new TextDecoder('utf-8', {fatal: true}).decode(await file.arrayBuffer());
  if (revision !== cvRevision) return;
  if (!content.trim() || content.length > 100000) {
    throw new Error('CV must contain between 1 and 100,000 characters.');
  }
  cvEditor.value = content;
  cvFormat.value = format;
  cvChanged();
  $('#cv-file-status').textContent = file.name + ' loaded. Save to make it active.';
}));

$('#save-cv').addEventListener('click', safely(async () => {
  const revision = cvRevision;
  await api('/api/settings', {cv: cvEditor.value, cv_format: cvFormat.value});
  if (revision === cvRevision) {
    cvDirty = false;
    $('#cv-file-status').textContent = 'Saved as your active CV.';
  }
  toast('CV saved for your next search.');
}));

async function reviewCv(action) {
  const revision = cvRevision;
  const buttons = [$('#score-cv'), $('#suggest-cv')];
  buttons.forEach(button => {button.disabled = true;});
  cvResults.replaceChildren();
  cvReviewStatus.textContent = action === 'score' ? 'Scoring CV…' : 'Looking for improvements…';
  try {
    const result = await api('/api/cv/review', {action, cv: cvEditor.value, format: cvFormat.value});
    if (revision !== cvRevision) return;
    if (action === 'score') {
      cvReviewStatus.textContent = 'CV writing score: ' + result.score + '/100';
      const feedback = document.createElement('p');
      feedback.textContent = result.feedback;
      cvResults.append(feedback);
      return;
    }
    cvReviewStatus.textContent = result.edits.length
      ? 'Review each proposed edit before applying it.'
      : 'No edits matched the current CV. Try reviewing a shorter excerpt or edit directly.';
    for (const edit of result.edits) {
      const card = document.createElement('div');
      card.className = 'analysis-box';
      for (const [label, text] of [['Before', edit.before], ['After', edit.after], ['Reason', edit.reason]]) {
        const paragraph = document.createElement('p');
        paragraph.textContent = label + ': ' + text;
        card.append(paragraph);
      }
      const apply = document.createElement('button');
      apply.type = 'button';
      apply.className = 'secondary';
      apply.textContent = 'Apply edit';
      apply.addEventListener('click', safely(() => {
        const parts = cvEditor.value.split(edit.before);
        if (parts.length !== 2) throw new Error('This excerpt changed. Request fresh suggestions.');
        cvEditor.value = parts.join(edit.after);
        cvChanged(false);
        apply.disabled = true;
        apply.textContent = 'Applied';
      }));
      card.append(apply);
      cvResults.append(card);
    }
  } catch (error) {
    if (revision === cvRevision) cvReviewStatus.textContent = '';
    throw error;
  } finally {
    buttons.forEach(button => {button.disabled = false;});
  }
}

$('#score-cv').addEventListener('click', safely(() => reviewCv('score')));
$('#suggest-cv').addEventListener('click', safely(() => reviewCv('suggest')));

$('#settings-form').addEventListener('submit',e=>e.preventDefault());
$('#save-settings').addEventListener('click',safely(async()=>{const f=$('#settings-form');if(!f.reportValidity())return;const changes={};for(const key of ['review_limit','min_score','min_salary_eur','min_relevance','max_llm_jobs_per_run','workers','ai_timeout_seconds','arbeitnow_pages'])changes[key]=Number(f.elements[key].value);const csv=key=>f.elements[key].value.split(',').map(x=>x.trim()).filter(Boolean);for(const key of ['required_keywords','include_keywords','exclude_keywords','location_keywords','role_keywords','visa_keywords'])changes[key]=csv(key);for(const key of ['unknown_policy','candidate_note','anthropic_model','ai_provider'])changes[key]=f.elements[key].value;changes.codex_model=f.elements.codex_model.value.trim()||null;for(const key of ['sponsorship_required','use_arbeitnow','include_unknown_location','include_relocation_outside_locations','exclude_german_required'])changes[key]=f.elements[key].checked;changes.boards={greenhouse:csv('greenhouse'),lever:csv('lever')};await api('/api/settings',{config:changes});toast('Preferences saved for your next search.');}));
$('#check-auth').addEventListener('click',safely(checkAuth));
(async()=>{try{await Promise.all([loadStats(),showView(location.hash.slice(1)||'jobs'),pollRun()]);}catch(e){toast(e.message,true);}})();
setInterval(()=>pollRun().catch(()=>{}),2500);

const originalOpenJob = openJob;
openJob = async function(id) {
 await originalOpenJob(id);
 if(state.detail?.id!==id)return;
 const a=state.detail.analysis||{};
 const section=document.createElement('section');
 section.innerHTML='<h2>Eligibility and evidence</h2><p>'+escapeHTML(a.eligibility?.status||'Not assessed — run a new search')+'</p>'+
 (a.eligibility?.checks||[]).map(x=>'<p>'+escapeHTML(x.requirement)+': '+escapeHTML(x.assessment)+'</p>').join('')+
 '<p>'+escapeHTML(a.evidence_status||'Evidence not available for this older analysis')+'</p>'+
 (a.evidence||[]).map(x=>'<h3>'+escapeHTML(x.requirement)+' · '+escapeHTML(x.assessment)+'</h3><p>Posting: '+escapeHTML(x.posting_evidence)+'</p><p>CV: '+escapeHTML(x.cv_evidence||'No supporting quote')+'</p>').join('');
 for(const [label,decision] of [['Interested','interested'],['Not for me','dismissed'],['Clear feedback','clear']]){
  const button=document.createElement('button');button.className='secondary';button.textContent=label;
  button.onclick=safely(async()=>{
   const reason=decision==='dismissed'?prompt('Why is this not for you? (optional)'):'';
   if(reason===null)return;
   await api('/api/feedback',{id,decision,reason});toast('Feedback saved');await loadJobs();
  });section.append(button);
 }
 $('#job-detail').append(section);
};

const queueToggle=document.createElement('label');
queueToggle.className='checkbox';
queueToggle.innerHTML='<input type="checkbox" id="review-queue"> Focused review queue';
document.querySelector('#job-search').parentElement.append(queueToggle);
queueToggle.querySelector('input').addEventListener('change',safely(async()=>{state.offset=0;await loadJobs();}));
