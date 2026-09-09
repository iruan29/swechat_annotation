/* File:// compatible adapter. Conversation text is data, never executable markup. */
(() => {
  'use strict';
  const bundle = JSON.parse(document.getElementById('offline-data').textContent);
  const cases = new Map(bundle.cases.map(item => [item.case_id, item]));
  const key = 'swe-chat-offline-v1:' + bundle.package_id + ':' + bundle.rater;
  const copy = value => JSON.parse(JSON.stringify(value));
  const empty = () => ({format: 'swe_chat_backup_v1', package_id: bundle.package_id, annotator: bundle.rater,
    rubric_version: bundle.version, records: {}});
  let memory = empty(), storageAvailable = true;
  function warnStorage() {
    const banner = document.getElementById('offline-notice');
    if (banner) banner.textContent = '浏览器无法持久保存：当前进度只在本页内存中。关闭前必须点击「备份全部进度」，下次用「导入进度」。';
  }
  function read() {
    if (!storageAvailable) return copy(memory);
    let raw;
    try { raw = localStorage.getItem(key); }
    catch { storageAvailable = false; warnStorage(); return copy(memory); }
    if (raw) {
      const value = JSON.parse(raw);
      if (value.format !== 'swe_chat_backup_v1' || value.package_id !== bundle.package_id || value.annotator !== bundle.rater || !value.records) throw new Error('本机进度格式异常，请通过备份文件恢复；不会覆盖原数据。');
      memory = value;
    }
    return copy(memory);
  }
  function write(value) {
    // One storage write keeps restore and submit atomic within a browser document.
    try { localStorage.setItem(key, JSON.stringify(value)); storageAvailable = true; }
    catch { storageAvailable = false; warnStorage(); }
    memory = copy(value);
  }
  function shape(spec, value, complete, path = '') {
    const label = spec.label || path;
    if (spec.type === 'object') {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(label + '：必须是对象');
      for (const [name, child] of Object.entries(spec.properties)) shape(child, value[name], complete, path + '.' + name);
    } else if (spec.type === 'array') {
      if (!Array.isArray(value) || value.length > 500) throw new Error(label + '：必须是数组，最多 500 项');
      value.forEach(item => shape(spec.items, item, complete, path));
    } else if (spec.type === 'integer') {
      if (!(!complete && (value === null || typeof value === 'string')) && !Number.isSafeInteger(value)) throw new Error(label + '：请填写整数 T 编号');
    } else if (typeof value !== 'string') throw new Error(label + '：请填写文本');
    if (spec.enum && complete && !spec.enum.includes(value)) throw new Error(label + '：请选择合法类别');
    if (complete && ['project', 'requirement', 'rationale'].includes(spec.field) && !value.trim()) throw new Error(label + '：请填写具体内容；未知也请说明原因');
  }
  function validate(value, item) {
    shape(bundle.schema, value, true);
    const turns = new Set(item.events.map(event => event.turn));
    function walk(node, field = '') {
      if (Array.isArray(node)) {
        if (field === 'evidence_turns' && !node.length) throw new Error('每个判断至少需要一个证据 T 编号');
        node.forEach(child => walk(child, field === 'evidence_turns' ? 'turn' : field));
      } else if (node && typeof node === 'object') {
        Object.entries(node).forEach(([name, child]) => walk(child, name));
      } else if (field === 'turn' && !turns.has(node)) throw new Error('T' + node + ' 不在本会话中');
    }
    walk(value);
    for (const options of [value.evolution.behaviors, value.gap.drivers]) {
      if (!options.length) throw new Error('请选择 Agent 行为和指令问题原因，可选无法判断 / 不适用');
      if (new Set(options).size !== options.length || options.length > 1 && options.some(v => ['无法判断', '不适用'].includes(v))) throw new Error('选项不可重复，无法判断 / 不适用不能与其他选项并选');
    }
    const initial = Math.min(...item.user_turns);
    if (value.updates.some(update => update.turn <= initial)) throw new Error('需求事件应在初始用户指令之后');
    const real = value.updates.filter(update => update.change !== '既有要求的实现修复');
    const extent = value.evolution.update_extent;
    if (extent === '无更新' && real.length || ['少量补充或调整', '实质变化'].includes(extent) && !real.length) throw new Error('更新程度与需求事件不一致；真实更新须至少记录一项');
    return copy(value);
  }
  function save(caseId, revision, annotation, complete) {
    if (!cases.has(caseId)) throw new Error('未知样本');
    if (!annotation || Array.isArray(annotation) || typeof annotation !== 'object' || !Number.isSafeInteger(revision) || typeof complete !== 'boolean') throw new Error('非法标注结构');
    const db = read(), prior = db.records[caseId];
    if (revision !== (prior?.revision || 0)) throw new Error('版本冲突：另一标签页已保存。请先备份当前进度，再刷新页面。');
    const normalized = complete ? validate(annotation, cases.get(caseId)) : null;
    const record = {revision: revision + 1, status: complete ? 'complete' : 'draft', annotation: copy(annotation), updated: Date.now(), input_fingerprint: cases.get(caseId).input_fingerprint};
    db.records[caseId] = record; write(db);
    return {revision: record.revision, status: record.status, normalized, volatile: !storageAvailable};
  }
  function metrics(item, annotation) {
    const updates = annotation.updates.filter(u => ['初始遗漏的既有要求', '用户真正新增或改变目标'].includes(u.change));
    const first = updates.length ? Math.min(...updates.map(u => u.turn)) : null;
    const unknown = annotation.evolution.update_extent === '无法判断' || annotation.updates.some(u => u.change === '无法判断');
    return {late_requirement: first !== null ? true : unknown ? null : false, first_late_requirement_turn: first,
      requirement_update_count: updates.length, user_rounds: item.user_turns.length,
      visible_characters: item.events.reduce((n,e) => n + [...e.text].length, 0),
      observed_tool_events: item.events.filter(e => e.kind === 'tool_use').length,
      user_rounds_after_first_update: first === null ? null : item.events.filter(e => e.kind === 'user_prompt' && e.turn > first).length,
      tool_events_from_first_update: first === null ? null : item.events.filter(e => e.kind === 'tool_use' && e.turn >= first).length,
      ...Object.fromEntries(['api_call_count','tool_call_count','total_tokens','duration_seconds'].map(name => [name,item.observed_costs[name] ?? null]))};
  }
  function summarize(rows) {
    const keys = ['user_rounds','observed_tool_events','api_call_count','tool_call_count','total_tokens','duration_seconds'];
    function stats(group) {
      const result = {sessions: group.length};
      for (const name of keys) {
        const values = group.map(row => row.metrics[name]).filter(v => typeof v === 'number' && Number.isFinite(v)).sort((a,b) => a-b);
        const n = values.length, mid = Math.floor(n/2);
        result[name] = {n, mean: n ? values.reduce((a,b) => a+b,0)/n : null, median: n ? n%2 ? values[mid] : (values[mid-1]+values[mid])/2 : null};
      }
      return result;
    }
    const groups = group => Object.fromEntries([['有晚出现需求',true],['无晚出现需求',false],['无法判断',null]].map(([label, flag]) => [label,stats(group.filter(row => row.metrics.late_requirement === flag))]));
    const quality = [...new Set(rows.map(row => row.annotation.gap.instruction_quality))].sort();
    const strata = new Map();
    rows.forEach(row => {const k=JSON.stringify([row.agent,row.annotation.evolution.initial_coverage]);if(!strata.has(k))strata.set(k,[]);strata.get(k).push(row);});
    return {cost_comparison: groups(rows), cost_by_instruction_quality: Object.fromEntries(quality.map(q => [q, stats(rows.filter(row => row.annotation.gap.instruction_quality === q))])),
      instruction_quality: Object.fromEntries(quality.map(q => [q,rows.filter(row => row.annotation.gap.instruction_quality === q).length])),
      by_agent_and_initial_coverage: [...strata].map(([k,group]) => {const [agent,initial_coverage]=JSON.parse(k); const g=groups(group);delete g['无法判断'];return {agent,initial_coverage,groups:g};}),
      interpretation: '仅已提交会话的描述性关联；旧要求修复不计作新增。缺失成本不填零，不能计算清晰初始指令的反事实节省。最终汇总会重新校验并计算指标。'};
  }
  function delivery() {
    const db=read(), rows=[];
    for (const item of bundle.cases) {
      const record=db.records[item.case_id];
      if (record?.status !== 'complete') continue;
      const annotation=validate(record.annotation,item);
      rows.push({session_id:item.case_id,repo_id:item.repo_id,agent:item.agent,annotator:bundle.rater,
        annotation_source:'human',rubric_version:bundle.version,input_fingerprint:item.input_fingerprint,
        revision:record.revision,annotation,raw_annotation:copy(annotation),observed_costs:item.observed_costs,
        turn_timestamps:item.turn_timestamps,metrics:metrics(item,annotation)});
    }
    const received=new Set(rows.map(row => row.session_id));
    return {delivery:{format:'swe_chat_delivery_v1',package_id:bundle.package_id,assignment_id:bundle.rater,
      expected_count:cases.size,completed_count:rows.length,complete:rows.length===cases.size,
      missing_case_ids:bundle.cases.filter(item => !received.has(item.case_id)).map(item => item.case_id).sort()},
      summary:{human_version:bundle.version,annotator:bundle.rater,run_completeness:{session_count:cases.size,completed:rows.length},...summarize(rows)},
      annotations:{review:rows}};
  }
  window.offlineValidateDraft = value => shape(bundle.schema, value, false);
  window.offlineAPI = async (path, payload) => {
    const url=new URL(path,'https://offline.invalid');
    if (window.offlineStorageError) throw new Error(window.offlineStorageError);
    if (url.pathname === '/api/config') return {assigned_annotator:bundle.rater,package_id:bundle.package_id};
    const annotator=payload ? payload.annotator : url.searchParams.get('annotator');
    if (annotator !== bundle.rater) throw new Error('本文件固定属于 '+bundle.rater);
    if (url.pathname === '/api/save') {
      if(payload.stage!=='review')throw new Error('未知阶段');
      return save(payload.case_id,payload.revision,payload.annotation,payload.complete);
    }
    if (url.pathname === '/api/export') return delivery();
    const db=read();
    if (url.pathname === '/api/tasks') return {cases:bundle.cases.map(item => ({case_id:item.case_id,statuses:{review:db.records[item.case_id]?.status || 'new'}})),total:cases.size,completed_stages:Object.values(db.records).filter(row => row.status==='complete').length,human_version:bundle.version,stages:['review']};
    if (url.pathname === '/api/case') {
      const item=cases.get(url.searchParams.get('case_id'));
      if(!item || url.searchParams.get('stage')!=='review')throw new Error('未知样本或阶段');
      const record=db.records[item.case_id];
      return {case_id:item.case_id,stage:'review',target_instruction_turn:item.target_instruction_turn,schema:copy(bundle.schema),
        annotation:copy(record?.annotation || bundle.blank),revision:record?.revision || 0,status:record?.status || 'new',
        events:copy(item.events),commits:item.commits,rubric:bundle.rubric,rubric_version:bundle.version,
        simple:true,reading_stats:item.reading_stats,trace_scope:item.trace_scope};
    }
    throw new Error('未知离线操作');
  };
  window.offlineAutoSave = state => {
    const result=save(state.view.case_id,state.view.revision,state.annotation,false);
    state.view.revision=result.revision;state.view.status='draft';
    // Keep unload protection when storage is unavailable.
    return storageAvailable;
  };
  function download(value, filename) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  document.getElementById('backup-progress').addEventListener('click',() => {
    try {download(read(),'backup_'+bundle.rater+'.json');window.offlineMessage?.('已备份全部草稿和已提交进度。换电脑时打开同一人的 HTML，再导入此文件。');}
    catch(error){window.offlineMessage?.(error.message,true);}
  });
  function restore(value) {
    let candidate;
    if (value.format==='swe_chat_backup_v1') {
      if (value.package_id!==bundle.package_id || value.annotator!==bundle.rater || value.rubric_version!==bundle.version) throw new Error('备份不属于当前批次 / 标注员 / 版本');
      candidate=copy(value);
    } else if (value.delivery?.format==='swe_chat_delivery_v1') {
      if(value.delivery.package_id!==bundle.package_id || value.delivery.assignment_id!==bundle.rater)throw new Error('提交文件不属于当前批次或标注员');
      if(!Array.isArray(value.annotations?.review))throw new Error('缺少 review 标注');
      candidate=empty();
      for(const row of value.annotations.review){
        if(!cases.has(row.session_id) || row.annotator!==bundle.rater || row.rubric_version!==bundle.version || Object.hasOwn(candidate.records,row.session_id))throw new Error('未知或重复样本 / 错误标注员或版本');
        candidate.records[row.session_id]={annotation:row.annotation,status:'complete',revision:row.revision,input_fingerprint:row.input_fingerprint,updated:Date.now()};
      }
    } else throw new Error('请选择备份 JSON 或当前批次的 submission JSON');
    if(!candidate.records || typeof candidate.records!=='object' || Array.isArray(candidate.records))throw new Error('非法备份结构');
    for(const [id,record] of Object.entries(candidate.records)){
      const item=cases.get(id);
      if(!item || record.input_fingerprint!==item.input_fingerprint || !['draft','complete'].includes(record.status) || !Number.isSafeInteger(record.revision) || record.revision<1)throw new Error('备份中有未知样本、指纹或状态错误');
      if(record.status==='complete')validate(record.annotation,item);
      else shape(bundle.schema,record.annotation,false);
    }
    return candidate;
  }
  document.getElementById('restore-progress').addEventListener('change',async event => {
    const file=event.target.files[0];if(!file)return;
    try{
      if(file.size>20_000_000)throw new Error('进度文件过大，请选择正确的 JSON');
      const candidate=restore(JSON.parse(await file.text()));
      if(!confirm(`导入 ${Object.keys(candidate.records).length} 条进度，将替换本浏览器中 ${bundle.rater} 的当前进度。建议先备份。继续？`))return;
      // Monotonic revisions also invalidate another tab's stale form after restoration.
      let prior;try{prior=read();}catch{prior=empty();}
      for(const [id,record] of Object.entries(candidate.records))record.revision=Math.max(record.revision,prior.records[id]?.revision || 0)+1;
      write(candidate);delete window.offlineStorageError;window.offlineReload?.();
      window.offlineMessage?.(storageAvailable?'已导入进度。':'已导入到本页内存，请在关闭前再次备份。');
    }catch(error){window.offlineMessage?.('导入失败，未改写当前进度：'+error.message,true);}
    finally{event.target.value='';}
  });
  // Browser storage is a convenience; downloaded backups remain portable across browsers and paths.
  try{read();const probe=key+':probe';localStorage.setItem(probe,'1');localStorage.removeItem(probe);}catch(error){if(error instanceof SyntaxError){window.offlineStorageError='本机进度 JSON 损坏，请导入备份恢复。';}else{storageAvailable=false;warnStorage();}}
})();
