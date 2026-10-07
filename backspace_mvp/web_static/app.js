/* All displayed evidence is escaped; credentials never enter the browser. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  dashboard:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  layers:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  network:'<circle cx="12" cy="12" r="3"/><circle cx="4" cy="4" r="2"/><circle cx="20" cy="4" r="2"/><circle cx="4" cy="20" r="2"/><circle cx="20" cy="20" r="2"/><path d="m6 6 4 4m4 0 4-4M6 18l4-4m4 0 4 4"/>',
  book:'<path d="M12 5C8 3 5 3 2 4v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-3-1-6-1-10 1Zm0 0v15"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-13 5h2m4 0h2"/>',
  help:'<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 4v.1"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v5h5M8 12h8m-8 4h8"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.spark}</svg>`;
const state = {page: ['overview','teacher','model','scope','plan'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview',
  mode: localStorage.getItem('backspace-mode') === 'workspace' ? 'workspace' : 'demo', data:null, config:null, perception:null, graphType:'material', questionId:null, selected:null, job:null, zoom:1, graphFocus:null, patternId:null, planDay:1};
let animationContext, toastTimer, pollTimer, graphAnimation, reloadSequence=0, hideJobTimer, jobStarting=false, uploading=false;
const savingTasks=new Set();
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
document.body.classList.toggle('motion-off',localStorage.getItem('backspace-motion')==='off');
const labels = {overview:'작업 홈',teacher:'선생님 자료',model:'Teacher Model',scope:'이번 시험범위',plan:'나의 학습계획'};
const reasoningLabels = {compare:'조건 비교',infer_cause:'원인 추론',predict:'결과 예측',justify:'근거 제시',read_data:'자료 해석',recall:'개념 회상',classify:'분류',calculate:'수량 계산',eliminate:'가능성 제거',apply:'개념 적용'};

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'X-Backspace-Client':'web',...options.headers}});
  let body;try{body=await response.json();}catch{throw Error('서버 응답을 읽지 못했습니다. 서버 연결을 확인하고 다시 시도하세요.');}
  if (!response.ok) throw Error(body.error || '요청을 완료하지 못했습니다.');
  return body;
}
const post = (path, value) => api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
function toast(message) {
  clearTimeout(toastTimer); $('#toast').textContent = message;
  if (window.gsap && Motion.enabled()) gsap.to('#toast',{autoAlpha:1,y:-4,duration:.25,overwrite:true});
  else $('#toast').style.opacity=1;
  toastTimer=setTimeout(()=>{if(window.gsap&&Motion.enabled()) gsap.to('#toast',{autoAlpha:0,y:0,duration:.25});else $('#toast').style.opacity=0;},5000);
}
function modal(title, html) {
  if(state.perception&&!closeReview(false,()=>modal(title,html)))return;
  $('#dialog').classList.remove('review-dialog');
  $('#dialog-title').textContent=title; $('#dialog-body').innerHTML=html;
  if (!$('#dialog').open) $('#dialog').showModal();
  if(window.gsap && Motion.enabled()) gsap.fromTo('#dialog',{opacity:0,y:12,scale:.98},{opacity:1,y:0,scale:1,duration:.3,ease:'power2.out'});
}
async function reload(animate=true) {
  const sequence=++reloadSequence;
  if(!state.config)state.config=await api('/api/config');
  const previous=state.data; const incoming=await api(`/api/data?mode=${state.mode}`);if(sequence!==reloadSequence)return;state.data=incoming;
  if(!animate&&previous&&previous.mode===incoming.mode)refreshView(previous);else render(animate);
  if (state.data.job && !state.job) trackJob(state.data.job);
}
function navigate(page) {
  if (!labels[page]) return;
  if(!state.data){state.page=page;history.replaceState(null,'','#'+page);return;}
  if(state.perception&&!closeReview(false,()=>navigate(page))){history.replaceState(null,'','#'+state.page);return;}
  document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');updateSidebarAccess();
  if(state.page===page&&$('#main').children.length>1)return;
  state.page=page; state.selected=null; state.graphFocus=null; state.zoom=1;
  document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');
  history.replaceState(null,'','#'+page); render();
  window.scrollTo({top:0,behavior:'instant'});$('#main').focus({preventScroll:true});
}
function setMode(mode) {
  if(state.perception&&!closeReview(false,()=>setMode(mode)))return;
  state.mode=mode;state.selected=null;localStorage.setItem('backspace-mode',mode);
  reload().catch(e=>toast(e.message));
}
function demoNote() {
  return state.mode==='demo' ? `<div class="demo-note"><strong>예시 자료</strong><span>합성 생명과학 데이터</span><button class="text-button" data-action="my-space">내 자료로 전환 ↗</button></div>` : '';
}
function intro(kicker,title,description,button='') {
  return `<section class="intro"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${description}</p></div>${button}</section>${demoNote()}`;
}
function button(text,action,primary=false,ico='arrow') {
  return `<button class="button ${primary?'primary':''}" data-action="${action}" ${state.job&&action.startsWith('run-')?'disabled':''}>${icon(ico)}${text}</button>`;
}
function staleNote() {
  return state.data.model_stale ? '<div class="info-strip warn">자료가 변경됐습니다. Teacher Model을 갱신한 뒤 계획을 생성하세요.</div>' : '';
}
function render(animate=true) {
  Motion.clear();graphAnimation?.revert();
  $('#breadcrumb').textContent=labels[state.page];
  $$('.nav-item').forEach(b=>{b.classList.toggle('active',b.dataset.page===state.page);b.setAttribute('aria-current',b.dataset.page===state.page?'page':'false');b.title=labels[b.dataset.page];});
  $('#mode-button').innerHTML=(state.mode==='demo'?'예시 자료':'내 자료')+' <span>⌄</span>';
  $('#main').innerHTML=state.page==='overview'?overview():state.page==='teacher'?documentsPage('teacher'):state.page==='scope'?documentsPage('scope'):state.page==='model'?modelPage():planPage();
  $$('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));drawGraph();bindForms();
  if(animate)Motion.enter(state.page);
}
function preserveInputs(){return $$('input:not([type=file]),select,textarea',$('#main')).map(el=>({id:el.id,value:el.value,checked:el.checked,focus:el===document.activeElement,start:el.selectionStart,end:el.selectionEnd}));}
function restoreInputs(inputs){for(const x of inputs){const el=document.getElementById(x.id);if(!el)continue;el.value=x.value;if(el.type==='checkbox')el.checked=x.checked;if(x.focus){el.focus({preventScroll:true});if(x.start!=null)try{el.setSelectionRange(x.start,x.end);}catch{}}}}
function refreshView(previous){
  const scroll=window.scrollY,inputs=preserveInputs();
  const template=document.createElement('template');
  if(state.page==='plan'&&$('#plan-content')&&!!previous.plan===!!state.data.plan){template.innerHTML=planPage();$('#plan-content').replaceWith(template.content.querySelector('#plan-content'));$('#plan-notices')?.replaceWith(template.content.querySelector('#plan-notices'));}
  else if(['teacher','scope'].includes(state.page)&&$('#file-panel')){const listScroll=$('.document-list')?.scrollTop||0,searchValue=$('#file-search')?.value||'',searchFocused=document.activeElement===$('#file-search');template.innerHTML=documentsPage(state.page);$('#file-panel').replaceWith(template.content.querySelector('#file-panel'));if($('#file-search')){$('#file-search').value=searchValue;filterDocuments(searchValue);if(searchFocused)$('#file-search').focus({preventScroll:true});}if($('.document-list'))$('.document-list').scrollTop=listScroll;if(state.page==='scope'&&JSON.stringify(previous.scope_material)!==JSON.stringify(state.data.scope_material))render(false);}
  else if(state.page==='overview'&&$('#home-status'))$('#home-status').innerHTML=homeStatus();
  else if(state.page==='model'&&previous.model&&state.data.model&&previous.model_stale===state.data.model_stale&&$('#model-report')){const graphChanged=JSON.stringify([previous.material,previous.question_graphs,previous.patterns,previous.model?.concept_importance])!==JSON.stringify([state.data.material,state.data.question_graphs,state.data.patterns,state.data.model?.concept_importance]);$('#model-report').innerHTML=modelReport();if(graphChanged)drawGraph();}
  else render(false);
  bindForms();restoreInputs(inputs);if($('#file-search'))filterDocuments($('#file-search').value);if($('#exam-name-field'))$('#exam-name-field').hidden=$('#upload-kind').value!=='exam';if(state.job)drawJob(state.job);window.scrollTo({top:scroll,behavior:'instant'});
}
async function uploadFiles(files) {
  if(state.job||jobStarting||uploading){toast('현재 작업이 끝난 뒤 자료를 추가하세요.');return;}
  const target=state.page==='scope'?'scope':'teacher',kind=$('#upload-kind')?.value||'material';
  const examId=$('#exam-id')?.value||'',materialType=$('#material-type')?.value||'worksheet';
  let uploaded=0;const rejected=[];uploading=true;
  try{
    for(const file of files){
      if(!file.size||file.size>state.config.max_file_bytes){rejected.push(`${file.name}: 0바이트 초과·${state.config.max_file_mb}MB 이하 파일이 필요합니다.`);continue;}
      const query=new URLSearchParams({filename:file.name,target,kind,exam_id:kind==='exam'?examId:'',material_type:materialType});
      try{await api('/api/upload?'+query,{method:'POST',body:file});uploaded++;}catch(error){rejected.push(`${file.name}: ${error.message}`);}
    }
    if(uploaded){state.mode='workspace';localStorage.setItem('backspace-mode','workspace');await reload(false);$('#mode-button').innerHTML='내 자료 <span>⌄</span>';}
    if(uploaded||rejected.length)toast(`${uploaded}개 자료 저장.${rejected.length?' '+rejected.join(' '):' 자료 읽기로 진행하세요.'}`);
  }finally{uploading=false;if($('#file-input'))$('#file-input').value='';}
}
function bindForms() {
  $$('[data-memory-file]').forEach(el=>el.onclick=()=>openUnderstanding(el.dataset.memoryFile).catch(e=>toast(e.message)));
  $$('[data-perception-file]').forEach(el=>el.onclick=()=>{
    toast('인식 결과를 여는 중…');
    openPerception(el.dataset.perceptionFile).catch(e=>toast(e.message));
  });
  $$('[data-read-target]').forEach(el=>el.onclick=()=>startJob('read',{target:el.dataset.readTarget}).catch(e=>toast(e.message)));
  if($('#file-input'))$('#file-input').onchange=e=>uploadFiles([...e.target.files]).catch(e=>toast(e.message));
  if($('#upload-kind'))$('#upload-kind').onchange=e=>{if($('#exam-name-field'))$('#exam-name-field').hidden=e.target.value!=='exam';};
  const drop=$('#dropzone');if(drop&&!drop.dataset.bound){drop.dataset.bound='true';['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('dragging');}));['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('dragging');}));drop.addEventListener('drop',e=>uploadFiles([...e.dataTransfer.files]).catch(e=>toast(e.message)));}
  if($('#ai-plan'))$('#ai-plan').onchange=e=>{$('#plan-cost-note').innerHTML=e.target.checked?'NVIDIA·Jev 사용 · 개념 수에 따라 호출량 증가':'기본 계획 · API 호출 없음';};
  if($('#plan-form'))$('#plan-form').onsubmit=e=>{e.preventDefault();startJob('plan',{days:Number($('#days').value),daily_minutes:Number($('#minutes').value),max_concepts:Number($('#concept-limit').value),exam_format:$('#exam-format').value,offline:!$('#ai-plan').checked}).catch(e=>toast(e.message));};
  if($('#exam-format')&&state.data.plan)$('#exam-format').value=state.data.plan.parameters.exam_format;
  if($('#note-form'))$('#note-form').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;if(form.dataset.saving)return;const input=$('#plan-note'),note=input.value,mode=state.mode;form.dataset.saving='true';try{await post('/api/plan/event',{mode,event_type:'constraint',note});if(input.isConnected&&input.value===note)input.value='';if(state.mode===mode)await reload(false);toast('메모를 저장했습니다. 계획 수정이 필요하면 다시 생성하세요.');}catch(e){toast(e.message);}finally{delete form.dataset.saving;}};
  syncJobControls();
}

async function openUnderstanding(fileId){
 const row=state.data.files.find(f=>f.id===fileId);if(!row)return;
 const result=await api('/api/memory?mode='+state.mode+'&target='+row.target+'&file_id='+encodeURIComponent(fileId));
 const notes=result.notes||[];
 const coverage=(result.coverage||[]).map(c=>`${(c.locators||[]).length}/${c.total_locators||0}쪽 저장${c.complete?'':' · 일부 범위'}`).join(' · ');
 modal('이해 노트',`<p class="context-text">${esc(row.name)} · ${result.matching_count||0}개 노트${result.matching_count>notes.length?' · '+notes.length+'개 표시':''}</p>${coverage?`<p class="field-tip">${esc(coverage)}</p>`:''}${notes.map(n=>`<article class="understanding-card"><div class="source-line">${esc(n.topic.join(' / '))} · ${esc(n.provenance.locator)} · ${n.stale?'원문 변경 · 이전 노트':n.review_status==='rejected'?'오류 표시 · 교사 근거에서 제외':n.review_status==='accepted'?'검토 완료':'AI 해석 검토 필요'}</div><h3>${esc(n.title)}</h3><p class="understanding-content">${esc(n.content)}</p><details><summary>원문 근거 · 관련 노트 ${(n.amem.links||[]).length}개</summary><pre>${esc(n.provenance.quote)}</pre><p class="field-tip">${esc(n.source_type)} · ${esc(n.provenance.source_file)} · ${esc(n.provenance.locator)}</p></details></article>`).join('')||'<div class="empty-state">저장된 이해 노트가 없습니다.</div>'}<p class="field-tip">원문을 짧은 자연어 노트로 먼저 저장합니다. 그래프·Teacher Model 생성과 별도이며 NVIDIA를 사용합니다.</p><button class="button" id="build-understanding" ${state.job?'disabled':''}>${notes.length?'이해 노트 이어 만들기':'이 자료 이해 노트 만들기'}</button>`);
 $('#build-understanding').onclick=()=>{ $('#dialog').close();startJob('understand',{target:row.target,file_id:fileId}).catch(e=>toast(e.message)); };
}
async function startJob(action,options={}) {
  if(state.job||jobStarting||uploading)return;
  const config=await api('/api/config');state.config=config;
  if(!config.runtime||config.runtime.restart_required)throw new Error('서버 업데이트 적용이 필요합니다. 업데이트된 프로그램 주소로 접속하세요. 저장된 노트는 유지됩니다.');
  if(state.mode==='demo'&&action!=='plan'){setMode('workspace');toast('내 자료 작업공간에서 자료를 추가한 뒤 실행하세요.');return;}
  jobStarting=true;try{const job=await post('/api/jobs',{action,mode:state.mode,...options});trackJob(job);}finally{jobStarting=false;}
}
function syncJobControls(){
  const busy=!!state.job&&['queued','running'].includes(state.job.status);
  $$('[data-read-target],[data-action^=run-],[data-analyze-visual],#build-understanding').forEach(b=>b.disabled=busy);
  const canPlan=state.data?.model&&!state.data.model_stale&&state.data.scope_material?.concepts.length&&!(state.data.files||[]).some(f=>f.target==='scope'&&(f.status==='pending'||f.analysis_stale));
  $$('#plan-form button').forEach(b=>b.disabled=busy||!canPlan);
  $$('#note-form button').forEach(b=>b.disabled=busy||!state.data?.plan);
}
const jobPresentation = {id:null,view:'expanded',latest:null,detailsOpen:false,markup:null};
function setJobView(view,restoreFocus=false){
  jobPresentation.view=view;
  try{sessionStorage.setItem('backspace-job-view:'+jobPresentation.id,view);}catch{}
  $('#job-tray').hidden=view!=='expanded';
  $('#job-mini').hidden=view!=='minimized';
  $('#job-toggle').setAttribute('aria-expanded',String(view==='expanded'));
  if(restoreFocus)$('#job-toggle').focus({preventScroll:true});
}
function jobVisibilityAction(action){
  if(action==='dismiss-job'){setJobView('hidden',true);return true;}
  if(action==='minimize-job'){setJobView('minimized');$('#job-mini').focus({preventScroll:true});return true;}
  if(action==='show-job'&&jobPresentation.latest){clearTimeout(hideJobTimer);drawJob(jobPresentation.latest);setJobView('expanded');$('#job-tray [data-action="dismiss-job"]').focus({preventScroll:true});return true;}
  return false;
}
function drawJob(job) {
  const tray=$('#job-tray');syncJobControls();
  if(jobPresentation.id!==job.id){
    jobPresentation.id=job.id;jobPresentation.view='expanded';jobPresentation.detailsOpen=false;jobPresentation.markup=null;
    try{const saved=sessionStorage.getItem('backspace-job-view:'+job.id);if(['expanded','minimized','hidden'].includes(saved))jobPresentation.view=saved;}catch{}
  }
  jobPresentation.latest=job;
  if(job.action==='read'&&job.status==='running')for(const f of state.data.files){if(job.step.includes(f.name)){const badge=$(`[data-file-row="${CSS.escape(f.id)}"] .badge`);if(badge){badge.textContent='◷ 읽는 중';badge.classList.add('pending');}}}
  const partial=job.outcome==='partial_success',review=job.outcome==='needs_review',reading=job.action==='read';
  const title=partial?(reading?'일부 자료의 읽기를 완료했어요.':job.action==='plan'?'기존 결과를 보존했어요. 계획은 재개할 수 있어요.':job.partial_understanding?'일부 자료의 이해 노트를 저장했어요.':'이해 노트를 저장했어요.'):review?'저장한 결과를 확인해 주세요.':job.status==='done'?(reading?'텍스트·이미지 읽기를 마쳤어요.':'분석 결과를 저장했어요.'):job.status==='failed'?(reading?'자료를 읽지 못했어요.':'이해 노트를 저장하지 못했어요.'):job.status==='interrupted'?'작업이 중단됐어요.':reading?'자료를 읽고 있어요.':'자료의 연결을 찾고 있어요.';
  const tasks=job.stage_tasks||[],pending=tasks.filter(t=>['pending','failed_retryable','not_started','running'].includes(t.status)),reviewTasks=tasks.filter(t=>['rejected','failed_terminal'].includes(t.status));
  const stages=[...new Set(tasks.map(t=>t.stage))];
  const explanation=partial?(reading?job.step||'자료별 읽기 상태를 확인해 주세요.':job.action==='plan'?job.step||'기존 결과는 보존됐습니다. 계획 생성만 재개할 수 있습니다.':'후속 분석 일부가 남았습니다. 저장된 노트는 자료 목록에서 볼 수 있습니다.'):job.error||job.step||'작업 준비 중';
  const busy=['queued','running'].includes(job.status),steps=job.completed_steps||[];
  const phase=busy?(reading?'자료 읽는 중':'분석 중'):partial?(reading?'읽기 확인':'후속 분석 대기'):review?'검토 필요':job.status==='done'?(reading?'읽기 완료':'분석 완료'):'분석 확인';
  const completed=tasks.filter(t=>['complete','skipped'].includes(t.status)).length;
  const summary=tasks.length?`완료 ${completed} · 전체 ${tasks.length}단계`:steps.length?`${steps.length}개 단계 완료`:'';
  const indicator=busy?'<span class="spinner" aria-hidden="true"></span>':icon(partial||review?'help':job.status==='done'?'check':'help');
  if(!$('.job-window-actions',tray))tray.innerHTML=`<div class="job-tray-head"><h3 id="job-title"><span class="job-status-icon"></span>진행상황</h3><div class="job-window-actions"><button data-action="minimize-job" aria-label="진행상황 최소화" title="최소화">−</button><button data-action="dismiss-job" aria-label="진행상황 닫기" title="닫기">×</button></div></div><div class="job-tray-body"></div><div class="job-tray-footer" hidden></div>`;
  $('.job-status-icon',tray).innerHTML=indicator;
  const markup=`<p class="job-result-title">${esc(title)}</p><p class="job-current" role="status" aria-live="polite">${esc(explanation)}</p>${summary?`<p class="job-stage-count">${esc(summary)}</p>`:''}${tasks.length||steps.length?`<details data-job-details><summary>단계별 진행 보기${pending.length?` · 재시도 ${pending.length}`:''}${reviewTasks.length?` · 검토 필요 ${reviewTasks.length}`:''}</summary><ul>${stages.length?stages.map(s=>{const group=tasks.filter(t=>t.stage===s),done=group.filter(t=>['complete','skipped'].includes(t.status)).length;return `<li>${done===group.length?'✓':'△'} ${esc(stageLabels[s]||s)} · ${done}/${group.length}</li>`;}).join(''):steps.map(s=>`<li>✓ ${esc(s)}</li>`).join('')}</ul>${[...pending,...reviewTasks].filter(t=>t.last_error).map(t=>`<p class="job-stage-error">${esc(stageLabels[t.stage]||t.stage)} · ${esc(stageStatus[t.status]||t.status)} · ${esc((t.last_error.message||t.last_error.error_type).split('진단 기록:')[0].slice(0,180))}</p>`).join('')}</details>`:''}${(job.warnings||[]).map(w=>`<p class="ocr-warning">${esc(w)}</p>`).join('')}`;
  const footer=$('.job-tray-footer',tray),footerMarkup=!busy&&pending.length?(reading?'<button class="button small" data-action="retry-read">자료 읽기 다시 시도</button>':`<button class="button small" data-resume-target="${esc(job.target||'teacher')}">미완료 분석 재개</button>`):'';
  if(footer.innerHTML!==footerMarkup)footer.innerHTML=footerMarkup;
  footer.hidden=!footerMarkup;
  if(jobPresentation.markup!==markup){
    const body=$('.job-tray-body',tray),scroll=body?.scrollTop||0,details=$('[data-job-details]',tray);
    if(details)jobPresentation.detailsOpen=details.open;
    const active=document.activeElement,focusAction=tray.contains(active)?active?.dataset?.action:null;
    body.innerHTML=markup;jobPresentation.markup=markup;
    const newDetails=$('[data-job-details]',tray);if(newDetails)newDetails.open=jobPresentation.detailsOpen;
    if($('.job-tray-body',tray))$('.job-tray-body',tray).scrollTop=scroll;
    if(focusAction)$(`[data-action="${focusAction}"]`,tray)?.focus({preventScroll:true});
  }
  $('#job-mini').innerHTML=indicator+`<span>${esc(phase)}</span><span aria-hidden="true">↗</span>`;
  const toggle=$('#job-toggle');toggle.hidden=false;toggle.title=phase;
  setJobView(jobPresentation.view);
}
function trackJob(job) {
  clearTimeout(hideJobTimer);state.job=job;drawJob(job);clearTimeout(pollTimer);let failures=0;
  const poll=async()=>{if(state.job&&state.job.id!==job.id)return;try{
    const current=await api('/api/jobs/'+job.id);if(state.job&&state.job.id!==job.id)return;failures=0;state.job=current;drawJob(current);
    if(['done','failed','interrupted'].includes(current.status)){
      state.job=null;await reload(false);if(current.action==='visual')await refreshVisualReview(current);if(current.status==='done'&&!['partial_success','needs_review'].includes(current.outcome))hideJobTimer=setTimeout(()=>{if(!state.job&&jobPresentation.id===current.id&&jobPresentation.view==='expanded'&&!$('[data-job-details]',$('#job-tray'))?.open)setJobView('minimized');},5000);
      if(current.status==='done')toast(current.action==='read'?(current.outcome==='partial_success'?'일부 자료 읽기 완료 · 자료별 상태를 확인해 주세요.':'자료 읽기 완료.'):current.outcome==='partial_success'?(current.action==='plan'?'계획 생성 대기 · 필요한 자료와 설정을 확인해 주세요.':'이해 노트 저장 · 미완료 단계만 재개할 수 있어요.'):'저장 완료. 결과에서 근거와 선택 범위를 확인해 주세요.');
    }else pollTimer=setTimeout(poll,1400);
  }catch(e){failures++;toast('작업 상태 연결이 끊겼습니다. 저장된 작업을 다시 확인합니다.');pollTimer=setTimeout(poll,Math.min(15000,1500*failures));}};
  pollTimer=setTimeout(poll,800);
}
async function toggleTask(id) {
  const task=state.data.plan.tasks.find(t=>t.id===id);if(!task||state.job||savingTasks.has(id))return;
  savingTasks.add(id);
  const flipState=window.Flip&&Motion.enabled()?Flip.getState('.task-card'):null;
  try{await post('/api/plan/event',{mode:state.mode,event_type:'progress',task_id:id,status:task.status==='completed'?'pending':'completed'});
    await reload(false);
    if(flipState&&state.page==='plan')Flip.from(flipState,{duration:.4,ease:'power2.inOut',absolute:false});
  }finally{savingTasks.delete(id);}
}
function download(kind) {
  const value=state.data[kind];if(!value)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download=kind==='plan'?'current_plan.json':'teacher_model.json';anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function filterDocuments(query){const term=query.trim().normalize('NFKC').toLocaleLowerCase();const rows=$$('[data-file-search]');let visible=0;rows.forEach(row=>{row.hidden=!row.dataset.fileSearch.normalize('NFKC').toLocaleLowerCase().includes(term);if(!row.hidden)visible++;});if($('.search-empty'))$('.search-empty').hidden=!term||visible>0;}
document.addEventListener('input',e=>{if(e.target.id==='file-search')filterDocuments(e.target.value);});
document.addEventListener('click',async e=>{
  const resume=e.target.closest('[data-resume-target]');
  if(resume){try{await startJob('resume',{target:resume.dataset.resumeTarget,...(resume.dataset.resumeTasks?{task_ids:JSON.parse(resume.dataset.resumeTasks)}:{})});}catch(err){toast(err.message);}return;}
  const nav=e.target.closest('[data-page]');if(nav){e.preventDefault();navigate(nav.dataset.page);return;}
  const graph=e.target.closest('[data-graph]');if(graph){state.graphType=graph.dataset.graph;state.graphFocus=null;state.selected=null;state.zoom=1;const scope=$('#graph-stage')?.dataset.scope==='true';const flip=window.Flip&&Motion.enabled()?Flip.getState('.map-panel'):null;$('.map-panel').outerHTML=mapPanel(scope);drawGraph();if(flip)Flip.from(flip,{duration:.3});return;}
  const day=e.target.closest('[data-plan-day]');if(day){state.planDay=day.dataset.planDay==='all'?null:Number(day.dataset.planDay);refreshView(state.data);return;}
  const task=e.target.closest('[data-task]');if(task){try{await toggleTask(task.dataset.task);}catch(err){toast(err.message);}return;}
  const detail=e.target.closest('[data-task-detail]');if(detail){const t=state.data.plan.tasks.find(t=>t.id===detail.dataset.taskDetail);modal('과제의 완료 기준',`<h3>산출물</h3><p>${esc(t.expected_output)}</p><h3>완료 기준</h3><ul>${t.success_criteria.map(c=>`<li>${esc(c)}</li>`).join('')}</ul><h3>원문 근거</h3>${t.material_evidence.slice(0,4).map(c=>`<blockquote class="evidence-quote">${esc(c.raw_evidence)}</blockquote><div class="source-line">${esc(c.source_title)} · ${esc(c.locator)}</div>`).join('')}`);return;}
  const hyp=e.target.closest('[data-hypothesis]');if(hyp){const h=state.data.model.assessment_ideals.find(h=>h.id===hyp.dataset.hypothesis),registry=new Map(state.data.model.evidence_registry.map(e=>[e.id,e]));modal('교사 가설의 근거와 대안',`<p>${esc(h.statement)}</p><h3>지지 근거</h3>${h.supporting_evidence.map(ref=>{const card=registry.get(ref.evidence_id);return `<p>${esc(ref.reason)}</p>${(card?.citations||[]).slice(0,2).map(c=>`<blockquote class="evidence-quote">${esc(c.raw_evidence)}</blockquote><div class="source-line">${esc(c.source_title)} · ${esc(c.locator)}</div>`).join('')}`;}).join('')}<h3>분석 범위와 조건</h3><p>지지 ${h.supporting_question_ids.length} / 포함 ${state.data.patterns?.coverage.included_questions||state.data.dataset.questions.length}문항 · 전체 ${state.data.dataset.questions.length}문항</p><p>${esc((h.applicable_context.conditions||[]).join(' · '))}</p><h3>반례 검색 범위</h3>${h.counter_evidence.map(ref=>{const card=registry.get(ref.evidence_id);return `<p>${esc(ref.reason)}</p>${(card?.citations||[]).map(c=>`<blockquote class="evidence-quote">${esc(c.raw_evidence)}</blockquote><div class="source-line">${esc(c.source_title)} · ${esc(c.locator)}</div>`).join('')}`;}).join('')}<p>${h.counter_evidence.length?'제공 근거에서 반례 후보가 식별됐습니다.':'제공 문맥에서 반례를 식별하지 못했습니다. 전체 자료에 반례가 없다는 뜻은 아닙니다.'}</p><h3>다른 설명</h3><ul>${h.alternative_explanations.map(t=>`<li>${esc(t)}</li>`).join('')}</ul><h3>추가 확인할 자료</h3><ul>${h.next_validation_data.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`);return;}
  const action=e.target.closest('[data-action]')?.dataset.action;if(!action)return;
  try{
    if(jobVisibilityAction(action))return;
    if(action==='retry-read'){await startJob('read',{target:jobPresentation.latest?.target||'teacher'});return;}
    if(action==='add'){navigate('teacher');return;}
    if(action==='my-space'){setMode('workspace');return;}
    if(action.startsWith('go-')){navigate(action.slice(3));return;}
    if(action.startsWith('download-')){download(action.slice(9));return;}
    if(action.startsWith('run-')){await startJob(action.slice(4));return;}
    if(action.startsWith('zoom-')){
      state.zoom=action==='zoom-reset'?1:Math.max(.65,Math.min(1.9,state.zoom+(action==='zoom-in'?.15:-.15)));
      zoomGraph();
    }
  }catch(err){toast(err.message);}
});
$('#mode-button').addEventListener('click',()=>setMode(state.mode==='demo'?'workspace':'demo'));
$('#close-dialog').addEventListener('click',()=>{if(state.perception)closeReview();else $('#dialog').close();});
$('#dialog').addEventListener('cancel',e=>{if(state.perception){e.preventDefault();closeReview();}});
$('#dialog').addEventListener('click',e=>{if(e.target===$('#dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){if(state.perception)closeReview();else e.target.close();}}});
$('#menu-toggle').addEventListener('click',()=>{const open=document.body.classList.toggle('menu-open');$('#menu-toggle').setAttribute('aria-expanded',String(open));updateSidebarAccess();});
$('#help-button').addEventListener('click',()=>{
 modal('자료에서 계획까지',`<h3>1. 선생님의 사고방식 만들기</h3><p>과거 학습자료·시험지를 업로드하고, 읽은 원문을 검토한 뒤 Teacher Model을 생성하세요.</p><h3>2. 이번 시험 준비하기</h3><p>새 시험범위를 별도로 추가하세요. 기간과 시간을 정하면 공부 깊이와 활동을 배정합니다.</p><h3>내 자료와 원문</h3><p>원본과 결과는 이 컴퓨터에 저장됩니다. AI 분석을 실행할 때 NVIDIA·Jev를 사용하며, 로컬 읽기와 기본 계획은 API를 호출하지 않습니다.</p><label class="toggle-row"><input id="motion-setting" type="checkbox" ${localStorage.getItem('backspace-motion')!=='off'?'checked':''}>화면 모션 사용</label><p class="field-tip">시스템의 동작 줄이기 설정을 우선합니다. 이 설정은 브라우저에 저장됩니다.</p>`);
 if($('#motion-setting'))$('#motion-setting').onchange=e=>{localStorage.setItem('backspace-motion',e.target.checked?'on':'off');document.body.classList.toggle('motion-off',!e.target.checked);Motion.clear();};
});
window.addEventListener('hashchange',()=>{if(labels[location.hash.slice(1)])navigate(location.hash.slice(1));});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#dialog').open&&jobPresentation.view==='expanded'&&!$('#job-tray').hidden){e.preventDefault();setJobView('hidden',true);}});
reload().catch(e=>{$('#main').innerHTML=`<div class="error-view"><h2>작업공간을 열지 못했습니다.</h2><p>${esc(e.message)}</p><button class="button" data-action="my-space">다시 연결</button></div>`;});


document.addEventListener('click',e=>{if(!e.target.closest('.concept-browser summary')||!window.Flip||!Motion.enabled())return;const panel=$('.map-panel');const before=Flip.getState(panel);requestAnimationFrame(()=>{if(panel.isConnected)Flip.from(before,{duration:.35,ease:'power2.inOut'});});});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('menu-open')){document.body.classList.remove('menu-open');$('#menu-toggle').setAttribute('aria-expanded','false');updateSidebarAccess();$('#menu-toggle').focus();}});

const tabletMenuMedia=matchMedia('(min-width:701px) and (max-width:1000px)');
function updateSidebarAccess(){document.querySelector('.sidebar').inert=matchMedia('(min-width:701px) and (max-width:1000px)').matches&&!document.body.classList.contains('menu-open');}
tabletMenuMedia.addEventListener('change',updateSidebarAccess);updateSidebarAccess();
