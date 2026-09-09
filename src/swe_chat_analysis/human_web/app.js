"use strict";

let stageNames = {behavior: "① 行为前缀", requirements: "② 要求演化", study2: "③ 指令与现实"};
let stageOrder = Object.keys(stageNames);
const state = {annotator: "", tasks: [], view: null, annotation: null, dirty: false, page: 0, saving: false, assigned: null};
const element = id => document.getElementById(id);
const tabStorage = {
  getItem(key) { try {return sessionStorage.getItem(key);} catch {return null;} },
  setItem(key, value) { try {sessionStorage.setItem(key, value);} catch {} }
};
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.get("token")) {
  tabStorage.setItem("human-token", fragment.get("token"));
  history.replaceState(null, "", location.pathname);
}
element("annotator").value = tabStorage.getItem("human-annotator") || "";

function message(text, error = false) {
  element("message").textContent = text;
  element("message").className = error ? "error" : "";
}

async function api(path, payload) {
  if (window.offlineAPI) return window.offlineAPI(path, payload);
  const response = await fetch(path, {method: payload ? "POST" : "GET", headers: {
    "Authorization": "Bearer " + (tabStorage.getItem("human-token") || ""),
    "Content-Type": "application/json"
  }, body: payload ? JSON.stringify(payload) : undefined});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败");
  return result;
}

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function button(text, action, className) {
  const result = node("button", text, className);
  result.type = "button";
  result.addEventListener("click", action);
  return result;
}

function dirty() {
  state.dirty = true;
  element("save-state").textContent = "未保存更改";
  if (window.offlineAutoSave && state.view) {
    try {
      const durable = window.offlineAutoSave(state);
      state.dirty = !durable;
      element("save-state").textContent = durable ? "草稿已自动保存在本浏览器" : "仅保存在本页内存，请备份进度";
      element("next-stage").hidden = true;
      const task = state.tasks.find(item => item.case_id === state.view.case_id);
      if (task) task.statuses.review = "draft";
      renderQueue();
      element("progress").textContent = `${state.tasks.length} 条 · ${state.tasks.filter(item => item.statuses.review === "complete").length} 条已提交`;
    } catch(error) { message("自动保存失败：" + error.message, true); }
  }
}

function defaultValue(spec) {
  if (spec.nullable) return null;
  if (spec.type === "object") return Object.fromEntries(Object.entries(spec.properties).map(([key, child]) => [key, defaultValue(child)]));
  if (spec.type === "array") return [];
  return spec.type === "string" ? "" : null;
}

function renderField(spec, value, update, path) {
  if (state.view.simple && path === 'evolution.source' && state.annotation.evolution.new_requirements !== '有') return node('div');
  const threadMatch = /^task_threads\.(\d+)\.([^.]+)$/.exec(path);
  if (state.view.stage === "study2" && threadMatch) {
    const thread = state.annotation.task_threads[Number(threadMatch[1])];
    const key = threadMatch[2];
    const noActual = thread.actual_situation_identifiable === false;
    const noMismatch = noActual || thread.material_instruction_reality_mismatch === false;
    const gapFields = ["mismatch_types", "mismatch_discovery", "gap_driver", "gap_driver_evidence_strength", "belief_basis_scope", "driver_evidence", "literal_counterfactual", "agent_gap_response"];
    if ((noMismatch && gapFields.includes(key)) || (noActual && ["actual_project_situation", "actual_situation_evidence", "material_instruction_reality_mismatch"].includes(key)) ||
        (thread.user_belief_identifiable === false && ["user_belief", "belief_evidence", "gap_driver", "gap_driver_evidence_strength", "belief_basis_scope", "driver_evidence"].includes(key))) return node("div");
  }
  const fieldId = "field-" + path.replace(/[^a-zA-Z0-9_-]/g, "-");
  if (spec.type === "object") {
    const container = node(path ? "details" : "div");
    if (path) { container.open = true; container.append(node("summary", spec.label)); }
    value = value || defaultValue(spec);
    for (const [key, child] of Object.entries(spec.properties)) {
      container.append(renderField(child, value[key], next => {value[key] = next; update(value);}, path ? path + "." + key : key));
    }
    return container;
  }
  if (spec.type === "array" && spec.items.enum && state.view.simple) {
    const container = node("fieldset"); container.append(node("legend", spec.label));
    for (const option of spec.items.enum) {
      const label = node("label", undefined, "check-option");
      const input = node("input"); input.type = "checkbox"; input.checked = (value || []).includes(option);
      input.addEventListener("change", () => {
        const selected = [...container.querySelectorAll("input:checked")].map(control => control.value);
        update(selected); dirty();
      });
      input.value = option; label.append(input, node("span", option)); container.append(label);
    }
    return container;
  }
  if (spec.type === "array" && spec.items.type === "integer" && state.view.simple) {
    const container = node("div", undefined, "field");
    const label = node("label", spec.label + "（例如 0, 4, 12）"); label.htmlFor = fieldId;
    const input = node("input"); input.id = fieldId; input.value = (value || []).join(", ");
    input.addEventListener("input", () => {
      const parts = input.value.trim().split(/[,，\s]+/).filter(Boolean);
      const valid = parts.every(part => /^\d+$/.test(part));
      input.setCustomValidity(valid ? "" : "请输入逗号分隔的非负整数");
      update(valid ? parts.map(Number) : parts); dirty();
    });
    container.append(label, input); return container;
  }
  if (spec.type === "array") {
    const container = node("details");
    container.open = true;
    value = Array.isArray(value) ? value : [];
    container.append(node("summary", spec.label + " · " + value.length));
    value.forEach((item, index) => {
      const card = node("div", undefined, "array-item");
      card.append(node("strong", "#" + (index + 1)));
      card.append(renderField(spec.items, item, next => {value[index] = next; update(value);}, path + "." + index));
      card.append(button("删除这一项", () => {
        if (!confirm("删除此项？提交前仍需重新检查 ID 与证据引用。")) return;
        value.splice(index, 1); update(value); dirty(); renderForm();
      }, "remove"));
      container.append(card);
    });
    container.append(button("＋ 添加" + spec.label, () => {
      const item = defaultValue(spec.items);
      if (spec.field === "task_threads") item.task_id = "task_" + (value.length + 1);
      if (spec.field === "final_requirements") item.requirement_id = "R" + (value.length + 1);
      value.push(item); update(value); dirty(); renderForm();
    }));
    return container;
  }
  const container = node("div", undefined, "field");
  const label = node("label", spec.label);
  label.htmlFor = fieldId;
  container.append(label);
  let input;
  if (spec.type === "boolean" || spec.enum) {
    input = node("select");
    input.append(new Option(spec.nullable && !state.view.simple ? "未知 / 不可识别（null）" : "请选择（未回答）", ""));
    const choices = spec.type === "boolean" ? [["true", "是"], ["false", "否"]] : spec.enum.map(choice => [choice, choice]);
    for (const [key, title] of choices) input.append(new Option(title, key));
    input.value = value === null || value === undefined ? "" : String(value);
    input.addEventListener("change", () => {
      update(spec.type === "boolean" ? (input.value === "" ? null : input.value === "true") : (spec.nullable && input.value === "" ? null : input.value));
      if (state.view.simple && spec.field === "new_requirements") {
        state.annotation.evolution.source = null;
      }
      dirty();
      if (["new_requirements", "actual_situation_identifiable", "material_instruction_reality_mismatch", "user_belief_identifiable"].includes(spec.field)) renderForm();
    });
  } else if (spec.type === "integer" || spec.type === "number") {
    input = node("input"); input.type = "number";
    input.step = spec.type === "integer" ? "1" : "0.05";
    input.min = "0";
    if (spec.field === "confidence") input.max = "1";
    if (spec.field === "score") input.max = "4";
    input.value = value === null || value === undefined ? "" : value;
    input.placeholder = spec.nullable ? "留空 = 未观察到 / 不适用" : "必填数字，不填 T 前缀";
    input.addEventListener("input", () => {update(input.value === "" ? null : Number(input.value)); dirty();});
  } else {
    input = node("textarea"); input.rows = 2; input.value = value || "";
    input.addEventListener("input", () => {update(input.value); dirty();});
  }
  input.id = fieldId;
  if (spec.field === "instruction_turn" && state.view.stage === "behavior") input.disabled = true;
  container.append(input);
  if (!state.view.simple) container.append(node("small", path));
  return container;
}

function renderForm() {
  element("annotation-form").replaceChildren(renderField(state.view.schema, state.annotation, value => {state.annotation = value;}, ""));
  const locked = state.view.status === "complete" && !state.view.simple;
  if (locked || state.saving) element("annotation-form").querySelectorAll("input,textarea,select,button").forEach(control => {control.disabled = true;});
  element("save-draft").disabled = locked || state.saving;
  element("submit").disabled = locked || state.saving;
  element("apply-json").disabled = locked || state.saving;
  element("json-editor").disabled = locked || state.saving;
  element("enter").disabled = state.saving || Boolean(state.assigned);
  element("annotator").disabled = state.saving || Boolean(state.assigned);
  element("next-stage").hidden = state.view.status !== "complete";
}

function renderEvents() {
  const quality = state.view.interaction_quality;
  const excludedLabels = {automatic_or_context:"自动通知 / 上下文",acknowledgement_only:"简短确认",short_or_menu_choice:"短选择",command_only:"快捷命令",duplicate_prompt:"重复消息",empty:"空消息",review_template:"模板"};
  const promptInfo = new Map((quality?.prompts || []).map(p => [p.turn,p]));
  const exchangeInfo = new Map();
  let exchangeIndex = 0;
  for (const block of quality?.exchanges || []) {
    if (block.substantive_turns.length && block.activity_turns.length) {
      exchangeIndex++;
      for (const turn of block.user_turns) exchangeInfo.set(turn,exchangeIndex);
    }
  }
  const query = element("search").value.trim().toLowerCase();
  const onlyUsers = element("users-only").checked;
  const groups = [];
  for (const event of state.view.events) {
    if (event.kind === "user_prompt" || !groups.length) groups.push([]);
    groups[groups.length - 1].push(event);
  }
  const promptGroups = groups.filter(group => group.some(event => event.kind === "user_prompt"));
  const covered = promptGroups.filter(group => group.some(event => ["assistant_response", "tool_use", "tool_result"].includes(event.kind))).length;
  element("trace-help").textContent = (quality ? `${quality.effective_interactions} 次有效交互（实质请求 + 后续 Agent 活动；连续补充合并，自动消息、纯确认和重复内容不计）。T 是原始事件证据编号，不是交互轮次。` : "") + `${promptGroups.length} 条用户消息；其中 ${covered} 段之后有 Agent / 工具记录，${promptGroups.length - covered} 段没有可见响应。每段截止下一条用户消息，分组不是因果对应。`;
  const matches = event => !query || ("t" + event.turn) === query || event.text.toLowerCase().includes(query);
  const matching = groups.filter(group => group.some(event => (!onlyUsers || event.kind === "user_prompt") && matches(event)));
  const pageSize = Math.max(1, matching.length); // Show every user prompt; lazy agent bodies keep rendering light.
  const pages = Math.max(1, Math.ceil(matching.length / pageSize));
  state.page = Math.max(0, Math.min(state.page, pages - 1));
  const userCount = state.view.events.filter(event => event.kind === "user_prompt").length;
  element("event-page").textContent = query ? `共 ${userCount} 个用户 prompt · 搜索匹配 ${matching.length} 组（含上下文组）` : `全部 ${userCount} 条用户消息（不含自动续接）`;
  element("previous-events").hidden = true; element("next-events").hidden = true;
  element("previous-events").disabled = state.page === 0;
  element("next-events").disabled = state.page >= pages - 1;
  function card(event) {
    const result = node("article", undefined, "event " + event.kind);
    const heading = node("div", undefined, "event-head");
    heading.append(button("T" + event.turn, async () => {
      try { await navigator.clipboard.writeText(String(event.turn)); message("已复制证据编号 " + event.turn); }
      catch { message("证据编号：" + event.turn); }
    }), node("strong", event.kind), node("span", event.source_turn !== event.turn ? "原编号 " + event.source_turn : ""));
    if (event.kind === "user_prompt" && quality) {
      const info = promptInfo.get(event.turn);
      const exchange = exchangeInfo.get(event.turn);
      heading.append(node("span", info?.reason ? `${excludedLabels[info.reason] || info.reason} · 不单独计入有效交互` : exchange ? `有效交互 ${exchange}` : "实质请求 · 未见后续响应", "interaction-label"));
    }
    result.append(heading);
    if (event.kind === "user_prompt" && promptInfo.get(event.turn)?.reason === "automatic_or_context") {
      const detail = node("details"); detail.append(node("summary", "自动记录原文 · 不计入有效交互"), node("pre", event.text)); result.append(detail);
    } else if (event.kind !== "user_prompt" && event.text.length > 3500) {
      const detail = node("details"); detail.append(node("summary", "完整正文 · " + event.text.length + " 字符"), node("pre", event.text)); result.append(detail);
    } else result.append(node("pre", event.text));
    return result;
  }
  element("events").replaceChildren(...matching.slice(state.page * pageSize, (state.page + 1) * pageSize).map(group => {
    const container = node("section", undefined, "round");
    const prompt = group.find(event => event.kind === "user_prompt");
    const round = state.view.events.filter(event => event.kind === "user_prompt").findIndex(event => event === prompt) + 1;
    container.append(node("h3", prompt ? "用户消息 " + round + " · T" + prompt.turn : "首条用户消息之前的上下文"));
    if (prompt) container.append(card(prompt));
    const agent = group.filter(event => event !== prompt);
    const visibleResponse = agent.some(event => ["assistant_response", "tool_use", "tool_result"].includes(event.kind));
    if (prompt && !visibleResponse && !onlyUsers) {
      const next = groups[groups.indexOf(group) + 1]?.find(event => event.kind === "user_prompt");
      container.append(node("p", next ? `T${prompt.turn} → T${next.turn}：此区间未收录 Agent 回复或工具记录。下一条是用户消息，不能据此判定 Agent 忽略了本条。` : `T${prompt.turn} → 会话记录结束：未收录后续 Agent 回复或工具记录，处理结果未知。`, "missing-response"));
    }
    if (!onlyUsers && agent.length) {
      const detail = node("details", undefined, "agent-fold");
      detail.open = Boolean(query && agent.some(matches));
      const replies = agent.filter(event => event.kind === "assistant_response").length;
      const tools = agent.filter(event => ["tool_use", "tool_result"].includes(event.kind)).length;
      detail.append(node("summary", `展开此后记录 · ${replies} 条 Agent 回复 · ${tools} 条工具记录`));
      // Build full bodies only when opened, preserving raw text without truncation.
      let rendered = false;
      const populate = () => {if (detail.open && !rendered) {detail.append(...agent.map(card)); rendered = true;}};
      detail.addEventListener("toggle", populate); populate(); container.append(detail);
    }
    return container;
  }));
}

function renderQueue() {
  const unfinished = element("unfinished").checked;
  const done = state.tasks.filter(task => stageOrder.every(stage => task.statuses[stage] === "complete")).length;
  element("overall-progress").max = state.tasks.length || 1;
  element("overall-progress").value = done;
  element("queue").replaceChildren(...state.tasks.map((task, index) => {
    const completed = stageOrder.every(stage => task.statuses[stage] === "complete");
    if (unfinished && completed) return null;
    const status = completed ? "已提交" : Object.values(task.statuses).includes("draft") ? "草稿" : "待标注";
    const control = button("", () => openCase(task.case_id), "queue-item" + (completed ? " completed" : "") +
      (state.view && state.view.case_id === task.case_id ? " active" : ""));
    control.append(node("strong", String(index + 1).padStart(2, "0")), node("span", status));
    control.title = task.case_id;
    control.setAttribute("aria-label", `样本 ${index + 1} · ${status} · ${task.case_id}`);
    if (state.view?.case_id === task.case_id) control.setAttribute("aria-current", "true");
    return control;
  }).filter(Boolean));
}

async function refreshTasks() {
  const result = await api("/api/tasks?annotator=" + encodeURIComponent(state.annotator));
  stageOrder = result.stages || ["behavior", "requirements", "study2"];
  stageNames = stageOrder.includes("review") ? {review: "会话标注 · 需求演化 + 指令缺口"} : {behavior: "① 行为前缀", requirements: "② 要求演化", study2: "③ 指令与现实"};
  state.tasks = result.cases;
  element("progress").textContent = `${result.total} 个 session · ${result.completed_stages}/${result.total * stageOrder.length} 阶段完成`;
  renderQueue();
}

async function openCase(caseId, stage) {
  if (state.saving) return;
  if (state.dirty && !confirm("当前有未保存更改，确定放弃并切换？")) return;
  const task = state.tasks.find(item => item.case_id === caseId);
  stage = stage || stageOrder.find(item => task.statuses[item] !== "complete") || stageOrder[stageOrder.length - 1];
  try {
    const query = new URLSearchParams({annotator: state.annotator, case_id: caseId, stage});
    const view = await api("/api/case?" + query);
    state.view = view; state.annotation = view.annotation; state.dirty = false; state.page = 0;
    element("workspace").hidden = false; element("welcome").hidden = true;
    element("case-title").textContent = "样本 " + String(state.tasks.findIndex(item => item.case_id === caseId) + 1).padStart(2, "0");
    element("case-id").textContent = caseId;
    element("stage-help").textContent = view.simple ?
      `逐轮阅读，完成一张表即可。${view.reading_stats ? (view.reading_stats.effective_interactions !== undefined ? view.reading_stats.effective_interactions + " 次有效交互 · " : "") + view.reading_stats.user_rounds + " 条用户消息 · " + view.reading_stats.characters.toLocaleString() + " 字符 · " + view.reading_stats.events + " 条记录。" : ""}全部用户 prompt 已展示；Agent 默认折叠。${view.trace_scope ? "保留原始 session 中 " + view.trace_scope.included_event_count + " 条所选类型事件（共 " + view.trace_scope.source_event_count + " 条源记录）。" : ""}这是数据集记录的会话，不保证项目始终完整。` : stage === "behavior" ?
      `只评价 T${view.target_instruction_turn} 这条指令的响应。可见其结束前的历史；未来消息与 commit 在服务器端被隐藏。提交后不可回改。` :
      "现在可以查看完整会话。要求可识别不等于实现成功；用户真正改变目标不等于最初错误；提交后本阶段锁定。";
    element("rubric").textContent = view.rubric;
    element("commits").textContent = view.commits.join("\n\n") || "未提供 commit 证据。";
    element("commits-block").hidden = stage === "behavior";
    element("search").value = ""; element("users-only").checked = false;
    element("stages").replaceChildren(...stageOrder.map((name, index) => {
      const control = button(stageNames[name], () => openCase(caseId, name), stage === name ? "active" : "");
      control.disabled = stageOrder.slice(0, index).some(earlier => task.statuses[earlier] !== "complete");
      return control;
    }));
    element("submit").textContent = view.simple ? "提交标注" : "校验并提交（锁定本阶段）";
    element("save-state").textContent = view.status === "complete" ? (view.simple ? "已提交，可修订" : "已提交并锁定") : view.status === "draft" ? (window.offlineAPI ? "已恢复浏览器草稿" : "已恢复服务器草稿") : "尚未保存";
    renderEvents(); renderForm(); renderQueue();
    element("case-title").scrollIntoView({block: "start"});
    message("已载入 " + stageNames[stage] + " · " + view.rubric_version);
  } catch (error) {message(error.message, true);}
}

async function save(complete) {
  if (!state.view || state.saving) return;
  if (complete && !state.view.simple && !confirm("提交后本阶段不可修改，并将解锁后续证据。确认已完成判断和证据检查？")) return;
  state.saving = true; renderForm();
  try {
    const result = await api("/api/save", {annotator: state.annotator, case_id: state.view.case_id,
      stage: state.view.stage, revision: state.view.revision, annotation: state.annotation, complete});
    state.view.revision = result.revision; state.view.status = result.status; state.dirty = Boolean(result.volatile);
    element("save-state").textContent = complete ? (state.view.simple ? "已提交，可修订" : "已提交并锁定") : "草稿已保存 " + new Date().toLocaleTimeString();
    message(complete ? "提交成功。统计仅纳入已提交记录；可继续下一项。" : (window.offlineAPI ? "草稿已保存。请定期下载备份，换浏览器或移动文件后用导入进度恢复。" : "草稿已保存至服务器，可以关闭后继续。 "));
    if (result.volatile) message("浏览器未能持久保存，关闭前请点击备份全部进度。", true);
    await refreshTasks();
    if (complete) {
      element("stages").querySelectorAll("button").forEach((control, index) => {
        const task = state.tasks.find(item => item.case_id === state.view.case_id);
        control.disabled = stageOrder.slice(0, index).some(name => task.statuses[name] !== "complete");
      });
    }
  } catch (error) {message("未提交 / 未保存：" + error.message, true);}
  finally {state.saving = false; renderForm();}
}

element("annotation-form").addEventListener("submit", event => event.preventDefault());
element("enter").addEventListener("click", async () => {
  if (state.dirty && !confirm("切换标注员将放弃未保存更改，继续？")) return;
  const id = element("annotator").value.trim();
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) {message("请输入字母、数字、下划线或连字符组成的标注员 ID。", true); return;}
  state.annotator = id; state.view = null; state.annotation = null; state.dirty = false;
  element("workspace").hidden = true; element("welcome").hidden = false;
  tabStorage.setItem("human-annotator", id);
  try {await refreshTasks(); element("export").disabled = false; element("summary").disabled = false; message("任务已载入，点击左侧样本开始。");}
  catch (error) {message(error.message, true);}
});
element("save-draft").addEventListener("click", () => save(false));
element("submit").addEventListener("click", () => save(true));
element("next-stage").addEventListener("click", () => {
  const next = stageOrder[stageOrder.indexOf(state.view.stage) + 1];
  if (next) openCase(state.view.case_id, next);
  else {
    const task = state.tasks.find(item => stageOrder.some(stage => item.statuses[stage] !== "complete"));
    if (task) openCase(task.case_id); else message("全部阶段已提交！可导出你的结果。 ");
  }
});
element("search").addEventListener("input", () => {state.page = 0; if (state.view) renderEvents();});
element("users-only").addEventListener("change", () => {state.page = 0; if (state.view) renderEvents();});
element("unfinished").addEventListener("change", renderQueue);
element("previous-events").addEventListener("click", () => {state.page--; renderEvents();});
element("next-events").addEventListener("click", () => {state.page++; renderEvents();});
element("show-json").addEventListener("click", () => {element("json-editor").value = JSON.stringify(state.annotation, null, 2);});
element("apply-json").addEventListener("click", () => {
  try {
    const value = JSON.parse(element("json-editor").value);
    if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("顶层必须是对象");
    if (window.offlineValidateDraft) window.offlineValidateDraft(value);
    state.annotation = value; dirty(); renderForm(); message("JSON 已应用，仍需保存或提交。 ");
  } catch (error) {message("JSON 无效：" + error.message, true);}
});
element("export").addEventListener("click", async () => {
  try {
    const result = await api("/api/export?annotator=" + encodeURIComponent(state.annotator));
    const blob = new Blob([JSON.stringify(result, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob); const anchor = node("a"); anchor.href = url;
    anchor.download = (result.delivery?.package_id ? "submission_" : "human_") + state.annotator + ".json"; anchor.click(); URL.revokeObjectURL(url);
    message(result.delivery && !result.delivery.complete ? `已导出部分结果：${result.delivery.completed_count}/${result.delivery.expected_count} 条。还有未提交样本，不能作为最终交付。` : "已导出全部已提交标注，可将 JSON 文件交给汇总负责人。");
  } catch (error) {message(error.message, true);}
});
window.addEventListener("beforeunload", event => {if (state.dirty) {event.preventDefault(); event.returnValue = "";}});

element("close-summary").addEventListener("click", () => element("summary-dialog").close());
element("summary").addEventListener("click", async () => {
  try {
    const result = await api("/api/export?annotator=" + encodeURIComponent(state.annotator));
    element("summary-completeness").textContent = JSON.stringify(result.summary.run_completeness, null, 2);
    const table = node("table");
    function visit(value, path) {
      if (value !== null && typeof value === "object") {
        for (const [key, child] of Object.entries(value)) visit(child, path + "." + key);
      } else {
        const line = node("tr");
        line.append(node("td", path), node("td", value === null ? "不可计算 / 缺失" : typeof value === "number" ? String(Math.round(value * 10000) / 10000) : String(value)));
        table.append(line);
      }
    }
    if (result.summary.cost_comparison) {
      const content = node("div");
      const metricNames = {user_rounds: "用户轮数", observed_tool_events: "工具调用（日志）", api_call_count: "API 调用（元数据）", tool_call_count: "工具调用（元数据）", total_tokens: "总 token", duration_seconds: "时长（秒）"};
      function comparison(title, groups) {
        content.append(node("h3", title));
        const grid = node("table"); const head = node("tr");
        ["分组 / 样本数", "指标", "有效 n", "均值", "中位数"].forEach(label => head.append(node("th", label)));
        grid.append(head);
        for (const [group, stats] of Object.entries(groups)) {
          for (const [key, label] of Object.entries(metricNames)) {
            const value = stats[key], line = node("tr");
            [group + " / " + stats.sessions, label, value.n, value.mean, value.median].forEach(item => line.append(node("td", item === null ? "缺失" : typeof item === "number" ? String(Math.round(item * 100) / 100) : item)));
            grid.append(line);
          }
        }
        content.append(grid);
      }
      comparison("有无晚出现需求：实际成本", result.summary.cost_comparison);
      comparison("按初始指令质量比较", result.summary.cost_by_instruction_quality);
      content.append(node("p", result.summary.interpretation));
      const strata = node("details"); strata.append(node("summary", "按 Agent 与初始覆盖程度分组（完整结果也在导出文件中）"), node("pre", JSON.stringify(result.summary.by_agent_and_initial_coverage, null, 2))); content.append(strata);
      element("summary-completeness").textContent = `已提交 ${result.summary.run_completeness.completed} / ${result.summary.run_completeness.session_count} 条会话`;
      element("summary-table").replaceChildren(content);
    } else {
      visit(result.summary.study1, "Study 1"); visit(result.summary.study2, "Study 2");
      element("summary-table").replaceChildren(table);
    }
    element("summary-dialog").showModal();
  } catch (error) {message(error.message, true);}
});

// Team packages bind identity on the server and open the assigned queue automatically.
(async () => {
  try {
    const config = await api("/api/config");
    if (config.assigned_annotator) {
      state.assigned = config.assigned_annotator;
      element("annotator").value = state.assigned;
      element("enter").click();
      element("annotator").disabled = true; element("enter").disabled = true;
    }
  } catch (error) { message(error.message, true); }
})();

window.offlineMessage = message;
window.offlineReload = async () => {
  state.view = null; state.annotation = null; state.dirty = false;
  element("workspace").hidden = true; element("welcome").hidden = false;
  await refreshTasks();
};

function setReadingLayout(wide) {
  document.body.classList.toggle("reading-wide", wide);
  element("layout-toggle").setAttribute("aria-pressed", String(wide));
  element("layout-toggle").textContent = wide ? "切换为并排标注" : "切换为通栏阅读";
  tabStorage.setItem("human-reading-wide", wide ? "1" : "0");
}
element("layout-toggle").addEventListener("click", () => setReadingLayout(!document.body.classList.contains("reading-wide")));
setReadingLayout(tabStorage.getItem("human-reading-wide") === "1");
