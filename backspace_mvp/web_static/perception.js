function reviewDirty(){return !!state.perception&&state.perception.drafts.size>0;}
function visualPanel(page){
 const v=state.perception,r=v.doc.visual_analysis?.[page.locator],busy=!!state.job;
 const button=`<button class="button small" data-analyze-visual="${esc(page.locator)}" ${busy?'disabled':''}>${r?'저장된 그림 분석 확인':'이 페이지 그림 분석'}</button>`;
 if(!r)return `<section class="visual-analysis"><div class="visual-heading"><h3>그림 이해</h3>${button}</div><p class="context-text">원본 이미지와 주변 설명을 함께 읽어 화살표·구조·관계를 분석합니다. 선택한 페이지에만 Gemini API를 사용합니다.</p></section>`;
 const result=r.result,images=new Map(r.images.map(i=>[i.id,i]));
 const rows=[...result.observations.map(o=>({...o,kind:'관찰'})),...result.connections.map(c=>({...c,kind:'관계 해석',description:c.from_label+' → '+c.to_label+' · '+c.interpretation}))];
 return `<section class="visual-analysis"><div class="visual-heading"><h3>그림 이해</h3><span class="badge pending">AI 해석 · 검토 필요</span></div><p>${esc(result.summary)}</p><p class="source-line">${esc(r.model)} · 이미지 ${r.coverage.image_inputs}장${r.coverage.full_page_image?' · 전체 페이지 포함':''}</p>${rows.map((o,n)=>{const im=images.get(o.image_id),[x1,y1,x2,y2]=o.region;return `<details class="visual-observation"><summary>${esc(o.kind)} · ${esc(o.description)}</summary>${o.visual_cue?`<p>시각 단서: ${esc(o.visual_cue)}</p>`:''}<p class="source-line">추출 확신도 ${Math.round(o.confidence*100)}% · 정확도 측정값 아님</p><figure class="visual-proof"><img src="/api/perception/${encodeURIComponent(v.fileId)}/visual-images/${im.file.slice(7,-4)}" alt="${esc(page.locator)} 시각 근거 원본"><span style="left:${x1*100}%;top:${y1*100}%;width:${(x2-x1)*100}%;height:${(y2-y1)*100}%"></span></figure></details>`;}).join('')}${result.uncertainties.length?`<div class="ocr-warning"><strong>확인이 필요한 부분</strong><ul>${result.uncertainties.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`:''}<p class="field-tip">학습자료의 다음 의미 분석에서 이 그림과 문맥을 함께 사용합니다. 교사 중요도는 별도 단계에서 계산합니다.</p></section>`;
}

async function refreshVisualReview(job){
 const v=state.perception;if(!v||v.fileId!==job.file_id)return;
 recordDrafts();const doc=await api('/api/perception/'+encodeURIComponent(v.fileId));
 if(state.perception!==v)return;v.doc=doc;showPerception();
}

document.addEventListener('click',async e=>{
 const button=e.target.closest('[data-analyze-visual]');if(!button)return;
 const v=state.perception;if(!v||state.job)return;
 recordDrafts();if(reviewDirty()){toast('수정 중인 글자를 먼저 저장한 뒤 그림을 분석하세요.');return;}
 try{await startJob('visual',{file_id:v.fileId,locator:button.dataset.analyzeVisual});button.disabled=true;}
 catch(error){toast(error.message);}
});
function closeReview(force=false,continuation=null){
  if(state.perception?.saving){toast('원문 저장이 끝난 뒤 닫아주세요.');return false;}
  if(reviewDirty()&&!force){state.reviewContinuation=continuation;$('#discard-dialog').showModal();return false;}
  const fid=state.perception?.fileId;state.perception=null;$('#dialog').classList.remove('review-dialog');$('#dialog').close();if(fid)$(`[data-perception-file="${CSS.escape(fid)}"]`)?.focus({preventScroll:true});return true;
}
async function openPerception(fileId,locator){if(state.perception&&!closeReview(false,()=>openPerception(fileId,locator)))return;const doc=await api('/api/perception/'+encodeURIComponent(fileId));state.perception={fileId,doc,locator:locator||doc.pages.find(p=>p.pending_blocks)?.locator||doc.pages[0]?.locator,drafts:new Map(),filter:'pending',tab:'text',selected:null,error:'',saving:false};showPerception();}
function recordDrafts(){const v=state.perception;if(!v)return;$$('[data-ocr-edit]').forEach(el=>{const block=v.doc.pages.flatMap(p=>p.blocks).find(b=>b.id===el.dataset.ocrEdit);if(block&&el.value!==block.text)v.drafts.set(block.id,el.value);else v.drafts.delete(el.dataset.ocrEdit);});}
function reviewDirtyLabel(){const el=$('.review-dirty');if(el)el.textContent=reviewDirty()?`미저장 수정 ${state.perception.drafts.size}개`:'모든 수정이 저장됐습니다.';}
function showPerception(){const v=state.perception;if(!v)return;const previousFocus=document.activeElement?.id;const page=v.doc.pages.find(p=>p.locator===v.locator);if(!page){state.perception=null;modal('원문 검토','<p>읽은 페이지가 없습니다.</p>');return;}
  const blocks=page.blocks.filter(b=>v.filter==='all'||b.status==='needs_review'||v.drafts.has(b.id));
  const assets=page.assets.map(a=>{const box=a.bbox||[0,0,a.width,a.height],w=box[2]-box[0]||1,h=box[3]-box[1]||1;return `<figure class="ocr-figure"><div class="ocr-image"><img src="/api/perception/${encodeURIComponent(v.fileId)}/assets/${encodeURIComponent(a.id)}" alt="${esc(a.label)} 원본" width="${a.width||Math.round(w)}" height="${a.height||Math.round(h)}" decoding="async">${page.blocks.filter(b=>b.asset_id===a.id&&b.bbox).map(b=>`<button class="ocr-box ${b.status==='needs_review'?'uncertain':''} ${v.selected===b.id?'active':''}" data-ocr-pick="${esc(b.id)}" aria-label="${esc(b.text.slice(0,40))} 글자 영역" style="left:${100*(b.bbox[0]-box[0])/w}%;top:${100*(b.bbox[1]-box[1])/h}%;width:${100*(b.bbox[2]-b.bbox[0])/w}%;height:${100*(b.bbox[3]-b.bbox[1])/h}%"></button>`).join('')}</div><figcaption>${esc(a.label)} · 주황: 확인 대기 / 진한 테두리: 선택</figcaption></figure>`;}).join('');
  $('#dialog-title').textContent='원문 검토';$('#dialog').classList.add('review-dialog');
  $('#dialog-body').innerHTML=`<div class="perception-heading"><p>원본과 비교해 글자를 수정하세요.</p><label class="visually-hidden" for="perception-page">페이지 / 슬라이드</label><select id="perception-page">${v.doc.pages.map(p=>`<option value="${esc(p.locator)}" ${p.locator===page.locator?'selected':''}>${esc(p.locator)}${p.pending_blocks?' · 확인 대기 '+p.pending_blocks:''}</option>`).join('')}</select><span class="review-dirty"></span></div><div class="review-tabs" role="group" aria-label="원문 검토 보기"><button data-review-tab="image" class="${v.tab==='image'?'active':''}">원본 이미지</button><button data-review-tab="text" class="${v.tab==='text'?'active':''}">수정 텍스트</button></div><div class="review-layout" data-tab="${v.tab}"><section class="review-original" aria-label="보존된 원본">${assets||`<div class="eyebrow" style="color:#526645">ORIGINAL TEXT</div><div class="review-source-text">${esc(page.blocks.map(b=>b.raw_text).join('\n\n'))||'표시할 원본 이미지가 없습니다.'}</div>`}</section><section class="review-editor" aria-label="인식 텍스트 수정"><div class="review-filter"><button data-review-filter="pending" class="${v.filter==='pending'?'active':''}">확인 대기 ${page.pending_blocks}</button><button data-review-filter="all" class="${v.filter==='all'?'active':''}">전체 ${page.blocks.length}</button></div><p class="review-save-error" role="alert">${esc(v.error)}</p>${page.errors.map(e=>`<p class="ocr-warning">${esc(e)}</p>`).join('')}${blocks.map(b=>`<section class="ocr-block ${b.status==='needs_review'?'needs-review':''} ${v.selected===b.id?'active':''}" data-block="${esc(b.id)}" data-flip-id="ocr-${esc(b.id)}"><div class="source-line">${b.method==='native'?'직접 추출':'로컬 OCR'} · ${b.confidence==null?'신뢰도 미산정':(b.confidence*100).toFixed(1)+'%'} · ${({needs_review:'확인 대기',human_verified:'직접 확인',excluded:'제외',accepted:'채택'}[b.status]||b.status)}</div><label class="visually-hidden" for="ocr-${esc(b.id)}">${esc(page.locator)} 인식 글자 수정</label><textarea id="ocr-${esc(b.id)}" data-ocr-edit="${esc(b.id)}" rows="${Math.max(3,Math.min(7,b.text.split('\n').length+1))}">${esc(v.drafts.get(b.id)??b.text)}</textarea><button class="button small" data-ocr-save="${esc(b.id)}" ${v.saving?'disabled':''}>수정·확정 저장</button>${(b.candidates||[]).filter(c=>c.engine==='surya').map(c=>`<p class="field-tip">보조 인식 후보: ${esc(c.text)} (${(c.confidence*100).toFixed(1)}%)</p>`).join('')}<details><summary>최초 인식 결과 · 수정 이력 ${(b.edits||[]).length}건</summary><pre>${esc(b.raw_text)}</pre>${(b.edits||[]).map(e=>`<p>${esc(e.at||e.timestamp||'수정 기록')} · ${esc(e.text??e.new_text??JSON.stringify(e))}</p>`).join('')}</details></section>`).join('')||'<div class="empty-state">확인 대기 글자 영역이 없습니다.<br>전체 결과에서 인식 글자를 확인할 수 있어요.</div>'}${page.assets.length?`<div class="ocr-warning">그림·수식·그래프의 의미는 직접 확인해야 합니다.${page.visual_acknowledged?' 원본 확인 기록이 있습니다.':`<button class="button small" data-visual-ack="${esc(page.locator)}">시각 영역 확인 기록</button>`}</div>`:''}${visualPanel(page)}<details><summary>분석에 전달할 텍스트 보기</summary><pre class="ocr-transcript">${esc(page.text)}</pre></details></section></div>`;
  if(!$('#dialog').open)$('#dialog').showModal();reviewDirtyLabel();if(previousFocus&&$('#'+CSS.escape(previousFocus)))$('#'+CSS.escape(previousFocus)).focus({preventScroll:true});
  $('#perception-page').onchange=e=>{recordDrafts();v.locator=e.target.value;v.selected=null;showPerception();};
  $$('[data-ocr-edit]').forEach(el=>{el.oninput=()=>{recordDrafts();reviewDirtyLabel();};el.onfocus=()=>pickBlock(el.dataset.ocrEdit,false);});
}
function pickBlock(id,focus=true){const v=state.perception;if(!v)return;v.selected=id;$$('.ocr-box').forEach(el=>el.classList.toggle('active',el.dataset.ocrPick===id));$$('.ocr-block').forEach(el=>el.classList.toggle('active',el.dataset.block===id));if(focus){recordDrafts();v.filter='all';v.tab='text';showPerception();$(`[data-ocr-edit="${CSS.escape(id)}"]`)?.focus();}else $(`[data-ocr-pick="${CSS.escape(id)}"]`)?.scrollIntoView({block:'nearest',behavior:'instant'});}
document.addEventListener('click',async e=>{const v=state.perception;if(!v)return;const filter=e.target.closest('[data-review-filter]'),tab=e.target.closest('[data-review-tab]'),pick=e.target.closest('[data-ocr-pick]'),save=e.target.closest('[data-ocr-save]'),ack=e.target.closest('[data-visual-ack]');
  if(tab){v.tab=tab.dataset.reviewTab;$('.review-layout').dataset.tab=v.tab;$$('[data-review-tab]').forEach(b=>b.classList.toggle('active',b.dataset.reviewTab===v.tab));return;}if(filter){const before=window.Flip&&Motion.enabled()?Flip.getState('.ocr-block'):null;recordDrafts();v.filter=filter.dataset.reviewFilter;showPerception();if(before)Flip.from(before,{targets:$$('.ocr-block'),duration:.35,ease:'power2.inOut'});return;}if(pick){pickBlock(pick.dataset.ocrPick);return;}if(!save&&!ack||v.saving)return;
  recordDrafts();const text=save?$(`[data-ocr-edit="${CSS.escape(save.dataset.ocrSave)}"]`).value:null;v.saving=true;save?.setAttribute('disabled','');try{v.doc=await post('/api/perception/review',{file_id:v.fileId,revision:v.doc.revision,...(save?{block_id:save.dataset.ocrSave,text}:{locator:ack.dataset.visualAck,acknowledge_visual:true})});recordDrafts();if(save&&v.drafts.get(save.dataset.ocrSave)===text)v.drafts.delete(save.dataset.ocrSave);v.error='';await reload(false);recordDrafts();v.saving=false;refreshReviewStatus();toast('원문 수정을 저장했습니다. 최초 인식 결과와 이력은 보존됩니다.');}catch(error){v.saving=false;v.error=error.message;const err=$('.review-save-error');if(err)err.textContent=error.message;save?.removeAttribute('disabled');reviewDirtyLabel();}
});
window.addEventListener('beforeunload',e=>{if(reviewDirty()){e.preventDefault();e.returnValue='';}});

document.getElementById('keep-review').onclick=()=>{$('#discard-dialog').close();state.reviewContinuation=null;$('[data-ocr-edit]')?.focus();};
document.getElementById('discard-review').onclick=()=>{const next=state.reviewContinuation;state.reviewContinuation=null;$('#discard-dialog').close();closeReview(true);next?.();};
document.getElementById('discard-dialog').addEventListener('cancel',()=>{state.reviewContinuation=null;});

// Keep the live textarea (including Korean IME composition and selection) mounted.
function refreshReviewStatus(){
 const v=state.perception;if(!v)return;
 const page=v.doc.pages.find(p=>p.locator===v.locator);if(!page)return;
 const error=$('.review-save-error');if(error)error.textContent=v.error;
 const pending=$('[data-review-filter="pending"]');if(pending)pending.textContent='확인 대기 '+page.pending_blocks;
 for(const b of page.blocks){
  const section=$(`[data-block="${CSS.escape(b.id)}"]`);if(!section)continue;
  section.classList.toggle('needs-review',b.status==='needs_review');
  const status={needs_review:'확인 대기',human_verified:'직접 확인',excluded:'제외',accepted:'채택'}[b.status]||b.status;
  $('.source-line',section).textContent=(b.method==='native'?'직접 추출':'로컬 OCR')+' · '+(b.confidence==null?'신뢰도 미산정':(b.confidence*100).toFixed(1)+'%')+' · '+status;
  $('[data-ocr-save]',section).disabled=false;
  const history=$('details',section);history.innerHTML=`<summary>최초 인식 결과 · 수정 이력 ${(b.edits||[]).length}건</summary><pre>${esc(b.raw_text)}</pre>${(b.edits||[]).map(e=>`<p>${esc(e.at||e.timestamp||'수정 기록')} · ${esc(e.text??e.new_text??JSON.stringify(e))}</p>`).join('')}`;
 }
 const transcript=$('.ocr-transcript');if(transcript)transcript.textContent=page.text;
 const visual=$('.visual-analysis');if(visual)visual.outerHTML=visualPanel(page);
 syncJobControls();
 if(page.visual_acknowledged){const ack=$('[data-visual-ack]');if(ack){ack.disabled=true;ack.textContent='시각 영역 확인 기록됨';}}
 reviewDirtyLabel();
}
