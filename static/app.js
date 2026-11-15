const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));
const fmt = (n) => (n === null || n === undefined || Number.isNaN(Number(n)))
  ? '—' : Number(n).toLocaleString('zh-CN');
const pct = (n) => (n === null || n === undefined) ? '—' : `${Math.round(Number(n) * 100)}%`;

const S = {
  health: null, batches: [], specs: [], runId: null, run: null,
  findings: [], findingsMeta: {}, findingsLoaded: false,
  tab: 'overview', filter: { severity: '', confidence: '', check: '' },
  pollTimer: null, renderKey: '', modalFor: '', sample: null, selectedFinding: null,
  drawerSampleId: null, busy: false,
  overviewKey: '', headlineKey: '',
  snapshots: [],      // 上一次轮询的步骤计时快照，供后端心跳对账，防刷新后状态丢失
  historyDurations: null, // 历史运行各步骤耗时，用作进度环预估总量
};

// ---------- 统一实时心跳 ----------
// 运行中步骤后端只在结束时回填 duration，执行中恒为 0s。这里用本地时钟
// 每 200ms 刷新一次所有"活"区域（loader 进度/秒数、侧栏轨迹秒数），
// 让已耗时平滑跳动，与轮询节奏解耦。
let liveTickHandle = null;
let liveTickRenderers = new Set();
function markLiveTick(which) {
  if (which) liveTickRenderers.add(which);
  if (liveTickHandle) return;
  const tick = () => {
    liveTickHandle = null;
    if (!window.Viz) return;
    liveTickRenderers.forEach((kind) => {
      if (kind === 'loader') tickLoader();
      if (kind === 'trace') tickTrace();
    });
    if (liveTickRenderers.size) liveTickHandle = setTimeout(tick, 200);
  };
  liveTickHandle = setTimeout(tick, 200);
}
function clearLiveTick() { liveTickRenderers.clear(); if (liveTickHandle) { clearTimeout(liveTickHandle); liveTickHandle = null; } }

// 刷新 loader：进度环 + 当前步骤 + 实时已耗时
// 进度环按"耗时加权"估算：用历史各步骤真实耗时（S.historyDurations）作权重，
// 比单纯的"完成步数/总数"更贴近真实执行进度；无历史数据时退化为步数进度。
function tickLoader() {
  const run = S.run;
  if (!run || !['created', 'queued', 'running'].includes(run.status)) { liveTickRenderers.delete('loader'); return; }
  const steps = run.steps || [];
  const total = steps.length || 1;
  const prog = run.progress || {};
  const current = steps.find((s) => s.status === 'running') || steps[steps.length - 1];
  const elapsed = Viz.liveElapsed(current);
  const elapsedText = elapsed != null ? ` · 已用 ${Viz.fmtElapsed(elapsed)}` : '';
  const stepLabel = prog.label || (current ? current.title : '');
  const stepText = (current || prog.label)
    ? `▸ ${stepLabel}${current?.detail?.error ? ' · ' + current.detail.error : ''}${elapsedText}`
    : '等待接单…';
  const fraction = estimateProgress(steps, S.historyDurations);
  Viz.updateLoader($('#tabContent'), fraction, stepText);
  const titleEl = $('#tabContent .viz-loader-title');
  if (titleEl) titleEl.textContent = `质检执行中 · ${doneCountText(steps)}`;
}

// 进度估算：优先用历史耗时加权，缺历史时按步数均分
function estimateProgress(steps, history) {
  const total = steps.length || 1;
  if (!history || typeof history !== 'object') {
    return steps.filter((s) => s.status === 'ok').length / total;
  }
  let done = 0, runningWeight = 0, totalWeight = 0;
  steps.forEach((step, i) => {
    const key = stepTitle(step, i);
    const w = Math.max(0.1, Number(history[key]) || 0); // 历史耗时秒，缺省给 0.1 权重
    totalWeight += w;
    if (step.status === 'ok') done += w;
    else if (step.status === 'running') {
      // 运行中步骤按 elapsed/history 给出部分进度，上限 0.95 避免虚满
      const e = step._elapsed || 0;
      runningWeight += Math.min(0.95, w > 0 ? e / w : 0) * w;
    }
  });
  if (totalWeight <= 0) return steps.filter((s) => s.status === 'ok').length / total;
  return Math.min(0.99, (done + runningWeight) / totalWeight);
}
function stepTitle(step, i) { return step?.title || `step-${i}`; }
function doneCountText(steps) {
  const done = steps.filter((s) => s.status === 'ok').length;
  return `${done}/${steps.length || 0}`;
}

// 刷新侧栏轨迹：运行中步骤的实时秒数
function tickTrace() {
  const run = S.run;
  if (!run) return;
  const steps = run.steps || [];
  const nodes = document.querySelectorAll('#trace .trace-step');
  let anyRunning = false;
  steps.forEach((step, i) => {
    if (step.status !== 'running') return;
    anyRunning = true;
    const node = nodes[i];
    if (!node) return;
    const metaEl = node.querySelector('.t-meta');
    const elapsed = Viz.liveElapsed(step);
    if (metaEl && elapsed != null) metaEl.textContent = `已用 ${Viz.fmtElapsed(elapsed)}`;
  });
  if (!anyRunning && !['running', 'created', 'queued'].includes(run.status)) {
    liveTickRenderers.delete('trace');
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function toast(message, bad = false) {
  const el = $('#toast');
  el.textContent = message;
  el.style.borderLeftColor = bad ? 'var(--red)' : 'var(--lime)';
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 4200);
}

async function init() {
  bind();
  bindModeSwitch();
  restoreHistoryDurations();   // 恢复历史步骤耗时权重，供进度环加权
  try {
    const [health, batches, specs, runs] = await Promise.all([
      api('/api/health'), api('/api/batches'), api('/api/specs'), api('/api/runs'),
    ]);
    S.health = health;
    S.batches = batches.items || [];
    S.specs = specs.items || [];
    renderHealth(runs.items || []);
    renderOptions();
    const last = localStorage.getItem('ariesqc.run');
    if (last && (runs.items || []).some((r) => r.id === last)) {
      await openRun(last);
    }
  } catch (error) {
    toast(`服务未就绪：${error.message}`, true);
  }
  if (window.RegressionUI) window.RegressionUI.init();
}

// ---------- 模式切换 ----------
function bindModeSwitch() {
  $('#modeSwitch').addEventListener('click', (event) => {
    const button = event.target.closest('.mode-btn');
    if (!button) return;
    setMode(button.dataset.mode);
  });
  $$('.mode-jump').forEach((button) => button.addEventListener('click', () => setMode(button.dataset.jump)));
}

function setMode(mode) {
  $$('.mode-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  $('#qualityShell').hidden = mode !== 'quality';
  $('#regressionShell').hidden = mode !== 'regression';
  localStorage.setItem('ariesqc.mode', mode);
}
(function restoreMode() {
  const saved = localStorage.getItem('ariesqc.mode');
  if (saved === 'regression') setMode('regression');
})();

function renderHealth(runs) {
  const llm = $('#llmStatus');
  if (S.health?.config?.llm_ready) {
    llm.className = 'pill ok';
    llm.innerHTML = `<i></i> LLM 已连接 · ${esc(S.health.config.model)}`;
  } else {
    llm.className = 'pill bad';
    llm.innerHTML = '<i></i> LLM 未配置（仅确定性规则）';
  }
  const model = $('#modelStatus');
  if (S.health?.config?.model_available) {
    model.className = 'pill ok';
    model.innerHTML = '<i></i> 复核权重就绪';
  } else {
    model.className = 'pill';
    model.innerHTML = '<i></i> 无复核权重';
  }
  $('#runCount').textContent = `${runs.length} 次运行`;
}

function renderOptions() {
  const batch = $('#batchSelect');
  batch.innerHTML = '<option value="">选择已发现的批次…</option>' + S.batches.map((b) =>
    `<option value="${esc(b.id)}" data-path="${esc(b.path)}">${esc(b.name)} · ${b.classes.length} 类 · ${esc(b.note)}</option>`).join('');
  const spec = $('#specSelect');
  spec.innerHTML = '<option value="">选择规范文件…</option>' + S.specs.map((s) =>
    `<option value="${esc(s.id)}" data-path="${esc(s.path)}">${esc(s.name)} · ${esc(s.kind)}</option>`).join('');
  if (!S.batches.length) $('#intakeHint').textContent = '未发现演示批次：请在 .env 配置 ARIES_QC_DATA_ROOT，或上传批次 zip。';
}

function bind() {
  $('#batchSelect').addEventListener('change', (event) => {
    const option = event.target.selectedOptions[0];
    if (option?.dataset.path) $('#batchPath').value = option.dataset.path;
  });
  $('#specSelect').addEventListener('change', () => {
    delete $('#specText').dataset.path;
    $('#specText').placeholder = '或粘贴规范文本（PDF/MD/YAML 均可选文件）';
  });
  $('#specText').addEventListener('input', () => { delete $('#specText').dataset.path; });
  $('#startBtn').addEventListener('click', startRun);
  $('#heroStart').addEventListener('click', () => quickDemo('single'));
  $$('.quick-btn').forEach((button) => button.addEventListener('click', () => quickDemo(button.dataset.demo)));
  $('#tabs').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-tab]');
    if (!button) return;
    S.tab = button.dataset.tab;
    $$('#tabs button').forEach((item) => item.classList.toggle('active', item === button));
    S.renderKey = '';
    renderRun();
  });
  $('#drawerClose').addEventListener('click', closeDrawer);
  $('#drawer .drawer-backdrop').addEventListener('click', closeDrawer);
  $('#modalCancel').addEventListener('click', () => { $('#modal').hidden = true; });
  $('#modalSubmit').addEventListener('click', submitQuestions);
  bindUploads();
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { closeDrawer(); $('#modal').hidden = true; }
  });
}

function bindUploads() {
  const wire = (drop, input, kind) => {
    drop.addEventListener('click', () => input.click());
    input.addEventListener('change', () => { if (input.files[0]) uploadFile(kind, input.files[0]); });
    ['dragenter', 'dragover'].forEach((name) => drop.addEventListener(name, (event) => {
      event.preventDefault(); drop.classList.add('over');
    }));
    ['dragleave', 'drop'].forEach((name) => drop.addEventListener(name, (event) => {
      event.preventDefault(); drop.classList.remove('over');
    }));
    drop.addEventListener('drop', (event) => {
      const file = event.dataTransfer.files[0];
      if (file) uploadFile(kind, file);
    });
  };
  wire($('#specDrop'), $('#specFile'), 'spec');
  wire($('#batchDrop'), $('#batchFile'), 'batch');
}

async function uploadFile(kind, file) {
  const form = new FormData();
  form.append('file', file, file.name);
  const label = kind === 'spec' ? '规范' : '批次';
  toast(`正在上传${label}…`);
  try {
    const data = await api(`/api/upload/${kind}`, { method: 'POST', body: form });
    if (kind === 'spec') {
      $('#specText').value = '';
      $('#specSelect').value = '';
      $('#specText').dataset.path = data.path;
      $('#specText').placeholder = `已上传：${data.name}（${Math.round(data.size / 1024)} KB）`;
    } else {
      $('#batchSelect').value = '';
      $('#batchPath').value = data.path;
    }
    toast(`${label}已就绪：${data.name}`);
  } catch (error) {
    toast(`上传失败：${error.message}`, true);
  }
}

function batchPayload() {
  const path = $('#batchPath').value.trim();
  if (path) return { batch_path: path };
  return { batch_id: $('#batchSelect').value };
}

function specPayload() {
  const text = $('#specText').value.trim();
  if (text) return { spec_text: text };
  const path = $('#specText').dataset.path;
  if (path) return { spec_path: path };
  const id = $('#specSelect').value;
  return id ? { spec_id: id } : {};
}

async function startRun() {
  if (S.busy) return;
  const batch = batchPayload();
  const spec = specPayload();
  if (!batch.batch_path && !batch.batch_id) return toast('请选择批次或填写目录', true);
  if (!spec.spec_text && !spec.spec_path && !spec.spec_id) return toast('请选择或粘贴规范', true);
  S.busy = true;
  $('#startBtn').disabled = true;
  try {
    const body = { ...batch, ...spec, use_model: $('#useModel').checked, strict_spec: $('#strictSpec').checked };
    const created = await api('/api/runs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    S.runId = created.id;
    localStorage.setItem('ariesqc.run', created.id);
    S.run = null; S.findings = []; S.findingsLoaded = false; S.renderKey = ''; S.tab = 'overview';
    const traceEl = $('#trace');
    if (traceEl) { traceEl.innerHTML = '<div class="trace-empty">等待接单…</div>'; traceEl.dataset.rendered = '0'; }
    $$('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'overview'));
    $('#welcome').hidden = true;
    $('#runView').hidden = false;
    await openRun(created.id);
    toast('已接单，开始执行');
  } catch (error) {
    toast(`接单失败：${error.message}`, true);
  } finally {
    S.busy = false;
    $('#startBtn').disabled = false;
  }
}

function quickDemo(kind) {
  const findBatch = (needle) => S.batches.find((b) => b.name.toLowerCase().includes(needle.toLowerCase()) || b.id.toLowerCase().includes(needle.toLowerCase()));
  const findSpec = (needle) => S.specs.find((s) => s.id.toLowerCase().includes(needle.toLowerCase()));
  let batch = null, spec = null;
  if (kind === 'single') {
    batch = findBatch('hr1') || S.batches.find((b) => b.id.includes('hr1'));
    spec = findSpec('robot_ops.yaml');
    $('#useModel').checked = true;
  } else if (kind === 'merge') {
    batch = findBatch('archive') || S.batches[0];
    spec = findSpec('all_batches');
    $('#useModel').checked = false;
  } else {
    batch = findBatch('hr1') || S.batches[0];
    spec = findSpec('missing_spec');
    $('#useModel').checked = false;
    $('#strictSpec').checked = false;
  }
  if (!batch || !spec) return toast('演示数据或规范未配置，请检查 .env', true);
  $('#batchSelect').value = batch.id;
  $('#batchPath').value = batch.path;
  $('#specSelect').value = spec.id;
  $('#specText').value = '';
  delete $('#specText').dataset.path;
  startRun();
}

async function openRun(runId) {
  S.runId = runId;
  localStorage.setItem('ariesqc.run', runId);
  try {
    S.run = await api(`/api/runs/${runId}`);
    restoreSnapshots(runId);   // 恢复刷新前的计时快照，防状态丢失
    reconcileStepTimers();
    S.renderKey = '';
    renderRun();
    renderTrace();
    if (S.run.status === 'needs_input') openQuestions();
    if (['running', 'queued', 'created'].includes(S.run.status)) schedulePoll();
    else if (S.run.status === 'done') await loadFindings();
  } catch (error) {
    toast(`读取运行失败：${error.message}`, true);
  }
}

// ---------- 步骤计时器心跳对账（后端心跳方案） ----------
// 思路：以每次轮询从后端取回的 duration 作为"心跳快照"，计算相邻两次轮询间
// 该步骤真实推进了多少秒，累加到 _elapsed。duration 由后端权威回填，前端只做
// 增量累加与平滑展示，不依赖前端本地时钟，避免与真实执行进度脱节。
//
// 防"灾难性遗忘"：S.snapshots 保存相邻两次轮询的快照，poll 期间页面不会丢。
// 若快照缺失（首次打开/刷新）、轮询间隔异常偏大，或 duration 一次性大幅回填，
// 都以当前 duration 为基准重新对齐，宁可短暂重置也不让秒数虚增或倒流。
function reconcileStepTimers() {
  const run = S.run;
  if (!run || !Array.isArray(run.steps)) return;
  const now = performance.now();
  const prevSnaps = S.snapshots || [];
  const snaps = [];
  run.steps.forEach((step, i) => {
    const key = `${step.index ?? i}:${step.title || ''}`;
    const status = step.status;
    const duration = typeof step.duration === 'number' ? step.duration : 0;
    const prevSnap = prevSnaps.find((s) => s.key === key);
    let elapsed;

    if (status === 'running') {
      if (prevSnap && prevSnap.status === 'running') {
        // 两次轮询都在跑：累加真实增量
        const dt = Math.max(0, now - prevSnap.at) / 1000;
        const dDuration = duration - prevSnap.duration;
        // duration 一次性回填（>1s 视为心跳丢失后的补齐），以真实值为准
        if (dDuration > 1) elapsed = duration;
        // 轮询间隔异常（>15s，可能标签页被冻结/刷新），以 duration 为准
        else if (dt > 15) elapsed = Math.max(duration, prevSnap.elapsed + dDuration);
        else elapsed = Math.max(prevSnap.elapsed + Math.max(0, dDuration), prevSnap.elapsed + dt * 0.5);
        // 平滑：增量与真实 duration 取更可信者（duration 权威但回填滞后）
        elapsed = Math.min(elapsed, prevSnap.elapsed + Math.max(dt, dDuration));
      } else if (prevSnap) {
        // 步骤刚变成 running（之前是 pending）：从零开始或承接 duration
        elapsed = duration > 0 ? duration : 0;
      } else {
        // 无快照（首次/刷新后）：以 duration 为准，若为 0 则从 0 起算
        elapsed = duration > 0 ? duration : 0;
      }
      step._elapsed = elapsed;
      // 基准锚点：以本次 poll 时刻为原点，tick 之间用本地时钟平滑插值，
      // 避免 _startedAt 每 poll 重置导致秒数回跳。
      step._baseElapsed = elapsed;
      step._baseAt = now;
    } else if (status === 'ok') {
      // 完成步骤：直接用后端真实 duration（回填后的权威值）
      step._elapsed = duration;
      step._startedAt = null;
    } else {
      step._elapsed = 0;
      step._startedAt = null;
    }

    snaps.push({ key, status, duration, elapsed: step._elapsed, at: now });
  });
  S.snapshots = snaps;
}

// ---------- 防"灾难性遗忘"：计时状态与历史权重持久化 ----------
// 页面刷新/标签页休眠会丢失内存中的 S.snapshots 与历史耗时。这里把它们写入
// sessionStorage / localStorage，init 时恢复；刷新后秒数从最近的 duration 续跑，
// 进度环也能立刻用上历史权重，而不是退化成"完成步数/总数"。
function persistSnapshots() {
  try {
    if (S.runId && S.snapshots.length) {
      sessionStorage.setItem(`ariesqc.snap.${S.runId}`, JSON.stringify({
        at: Date.now(), snaps: S.snapshots,
      }));
    }
  } catch { /* 存储不可用时静默忽略，心跳仍可用内存快照 */ }
}
function restoreSnapshots(runId) {
  if (!runId) return;
  try {
    const raw = sessionStorage.getItem(`ariesqc.snap.${runId}`);
    if (!raw) return;
    const data = JSON.parse(raw);
    // 快照超过 5 分钟视为过期（运行可能已被别处重置），不恢复
    if (data && Date.now() - data.at < 5 * 60 * 1000) S.snapshots = data.snaps || [];
  } catch { S.snapshots = []; }
}
// 从已完成运行收集各步骤真实耗时，作为进度环的历史权重
function learnHistoryDurations(steps) {
  if (!Array.isArray(steps)) return;
  const hist = S.historyDurations || {};
  steps.forEach((step, i) => {
    const key = stepTitle(step, i);
    if (step.status === 'ok' && typeof step.duration === 'number' && step.duration > 0) {
      // 多次观测取指数滑动平均，让权重随真实执行稳定收敛
      hist[key] = hist[key] == null ? step.duration : hist[key] * 0.7 + step.duration * 0.3;
    }
  });
  S.historyDurations = hist;
  try { localStorage.setItem('ariesqc.histDurations', JSON.stringify(hist)); } catch { /* ignore */ }
}
function restoreHistoryDurations() {
  try {
    const raw = localStorage.getItem('ariesqc.histDurations');
    if (raw) S.historyDurations = JSON.parse(raw);
  } catch { S.historyDurations = null; }
}

function schedulePoll() {
  clearTimeout(S.pollTimer);
  S.pollTimer = setTimeout(poll, 700);
}

async function poll() {
  if (!S.runId) return;
  try {
    S.run = await api(`/api/runs/${S.runId}`);
    // 后端心跳对账：用 S.snapshots 的相邻快照增量累加运行中步骤秒数，
    // 不再沿用 _startedAt（会跟心跳累加冲突导致重复计时）。
    reconcileStepTimers();
    persistSnapshots();
    renderTrace();
    renderRun();
    const status = S.run.status;
    if (status === 'done') {
      // 收集本次真实耗时作历史权重，供后续进度环加权
      learnHistoryDurations(S.run.steps);
      await loadFindings();
      renderRun();
      toast('质检完成，交付包已生成');
    } else if (status === 'needs_input') {
      openQuestions();
    } else if (status === 'failed' || status === 'cancelled') {
      toast(`运行${status === 'failed' ? '失败' : '已取消'}：${S.run.error || ''}`, status === 'failed');
    } else {
      schedulePoll();
    }
  } catch (error) {
    toast(`轮询失败：${error.message}`, true);
  }
}

async function loadFindings() {
  if (!S.runId) return;
  try {
    const data = await api(`/api/runs/${S.runId}/findings?limit=500&offset=0`);
    S.findings = data.items || [];
    S.findingsMeta = { total: data.total, checks: data.checks || {} };
    S.findingsLoaded = true;
  } catch (error) {
    toast(`证据加载失败：${error.message}`, true);
  }
}

function renderTrace() {
  const state = S.run?.status || 'idle';
  $('#traceState').textContent = state.toUpperCase();
  const steps = S.run?.steps || [];
  const trace = $('#trace');
  if (!steps.length) {
    if (trace.dataset.built !== 'empty') {
      trace.innerHTML = '<div class="trace-empty">等待接单…</div>';
      trace.dataset.built = 'empty';
    }
    return;
  }
  // 增量更新：已有步骤仅同步状态类（running→ok 等），新增步骤追加；不整块重建。
  const current = Number(trace.dataset.rendered || 0);
  if (current === 0 || trace.querySelector('.trace-empty')) {
    trace.innerHTML = '';
    trace.dataset.built = 'steps';
  }
  const existing = trace.querySelectorAll('.trace-step');
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    if (i < existing.length) {
      // 复用节点，仅更新状态类与元信息（保留 DOM，动画记忆不丢）
      const el = existing[i];
      const wantCls = `trace-step ${esc(step.status)}`;
      if (el.className !== wantCls) el.className = wantCls;
      const metaEl = el.querySelector('.t-meta');
      const meta = window.Viz ? Viz.stepMeta(step) : traceMeta(step);
      if (metaEl && metaEl.textContent !== meta) metaEl.textContent = meta;
      continue;
    }
    const meta = window.Viz ? Viz.stepMeta(step) : traceMeta(step);
    const el = document.createElement('div');
    el.className = `trace-step ${esc(step.status)} new`;
    el.innerHTML = `<span class="t-dot"></span>
      <div><div class="t-name">${esc(step.title)}</div><div class="t-meta">${esc(meta)}</div></div>`;
    trace.appendChild(el);
  }
  trace.dataset.rendered = String(steps.length);
  trace.scrollTop = trace.scrollHeight;
  markLiveTick();
}

function traceMeta(step) {
  const detail = step.detail || {};
  const time = step.duration ? `${step.duration}s` : '…';
  if (detail.images !== undefined) return `${detail.images} 图 · ${detail.objects || 0} 实例 · ${time}`;
  if (detail.method) return `${detail.method} · ${(detail.classes || []).length} 类 · ${time}`;
  if (detail.canonical_classes !== undefined) return `${detail.canonical_classes} 类 · ${detail.conflicts} 冲突 · ${time}`;
  if (detail.total !== undefined) return `${detail.total} 条 (P0 ${detail.by_severity?.P0 || 0}) · ${time}`;
  if (detail.score !== undefined) return `覆盖 ${detail.score ?? '—'}% · ${time}`;
  if (detail.items !== undefined) return `${detail.items} 项工单 · ${time}`;
  if (detail.total_hours !== undefined) return `${detail.total_hours}h · ${detail.headcount} 人 · ${time}`;
  if (detail.changed_files !== undefined) return `${detail.changed_files} 文件 · ${time}`;
  if (detail.artifacts !== undefined) return `${detail.artifacts} 个交付物 · ${time}`;
  if (detail.questions !== undefined) return `需确认 ${detail.questions} 项 · ${time}`;
  return time;
}

function renderRun() {
  if (!S.run) return;
  $('#welcome').hidden = true;
  $('#runView').hidden = false;
  const spec = S.run.spec?.data || {};
  const summary = S.run.summary || {};
  const stats = S.run.batch?.stats || {};
  const counts = S.run.findings || {};
  $('#runIdLabel').textContent = `RUN ${S.run.id} · ${String(S.run.status).toUpperCase()}`;
  $('#projectName').textContent = spec.project || S.run.batch_path || '数据质检';
  $('#headline').textContent = summary.headline || statusText(S.run.status);
  const gate = $('#gateBadge');
  const gateValue = summary.gate || '';
  gate.className = `gate ${gateValue}`;
  gate.textContent = gateValue ? ({ blocked: '不可交付 · P0', at_risk: '有风险 · 覆盖不足', pass: '可进入人工复核' }[gateValue] || gateValue) : statusText(S.run.status);
  const severity = counts.by_severity || {};
  const kpiItems = [
    { label: '图像', value: stats.images ?? 0, unit: '张' },
    { label: '实例', value: stats.objects ?? 0, unit: '个' },
    { label: 'P0', value: severity.P0 || 0, unit: '硬伤', cls: 'p0' },
    { label: 'P1', value: severity.P1 || 0, unit: '高风险', cls: 'p1' },
    { label: 'P2', value: severity.P2 || 0, unit: '候选/提示' },
    { label: '覆盖', value: S.run.coverage?.score ?? 0, unit: '%', cls: 'pass', decimals: 1 },
  ];
  const kpiContainer = $('#kpis');
  if (window.Viz) {
    // 首次构建结构，之后每次轮询仅增量更新，数字从旧值平滑滚到新值
    Viz.updateKpis(kpiContainer, kpiItems);
  } else {
    kpiContainer.innerHTML = kpiItems.map((it) =>
      `<div class="kpi ${it.cls || ''}"><b>${esc(it.value)}</b><span>${esc(it.label)} · ${esc(it.unit)}</span></div>`).join('');
  }

  // 运行中：在 tab 区域显示全屏 loader（含流水线动画）
  const busyStates = ['created', 'queued', 'running'];
  if (busyStates.includes(S.run.status)) {
    const steps = S.run.steps || [];
    // 流水线骨架只在结构变化时重建；进度环/秒数交给本地 ticker 高频刷新
    const pipeKey = `pipe|${S.run.status}|${steps.length}`;
    if (S.overviewKey !== pipeKey) {
      S.overviewKey = pipeKey;
      const pipeHTML = window.Viz ? Viz.pipeline(steps) : '';
      $('#tabContent').innerHTML = window.Viz
        ? Viz.loaderHTML(0.02, '质检执行中', '正在同步进度…', pipeHTML)
        : '<div class="empty-note">执行中…</div>';
      if (window.Viz) Viz.mount($('#tabContent'));
    }
    if (window.Viz) {
      const renderProgress = () => {
        const run = S.run;
        if (!run) return;
        const liveSteps = run.steps || [];
        const doneCount = liveSteps.filter((s) => s.status === 'ok').length;
        const total = liveSteps.length || 1;
        // 后端细粒度 progress（如"已扫描 N 张"）优先用于副标题
        const prog = run.progress || {};
        const current = liveSteps.find((s) => s.status === 'running') || liveSteps[liveSteps.length - 1];
        const elapsed = Viz.liveElapsed(current);
        const elapsedText = elapsed != null ? ` · 已用 ${Viz.fmtElapsed(elapsed)}` : '';
        const stepLabel = prog.label || (current ? current.title : '');
        const stepText = current || prog.label
          ? `▸ ${stepLabel}${current?.detail?.error ? ' · ' + current.detail.error : ''}${elapsedText}`
          : '等待接单…';
        Viz.updateLoader($('#tabContent'), doneCount / total, stepText);
        // 标题行显示已完成/总数
        const titleEl = $('#tabContent .viz-loader-title');
        if (titleEl) titleEl.textContent = `质检执行中 · ${doneCount}/${total}`;
      };
      renderProgress();
      markLiveTick('loader');
    }
    return;
  }
  if (window.Viz) Viz.stopTicker();

  // headline 打字机效果（一次性触发）
  if (window.Viz) {
    const headEl = $('#headline');
    const hKey = `headline|${S.run.id}|${summary.headline || ''}`;
    if (S.headlineKey !== hKey && summary.headline && S.run.status === 'done') {
      S.headlineKey = hKey;
      Viz.typeIn(headEl, summary.headline, { speed: 8 });
    }
  }

  const key = `${S.run.status}|${(S.run.steps || []).length}|${counts.total}|${summary.gate}|${S.tab}|${S.findingsLoaded}`;
  if (key === S.renderKey) return;
  S.renderKey = key;
  S.overviewKey = '';
  $('#tabContent').innerHTML = renderTab();
  if (window.Viz) Viz.mount($('#tabContent'));
  if (S.tab === 'findings') bindFindings();
}

function statusText(status) {
  return ({
    created: '已创建', queued: '排队中', running: '执行中…', needs_input: '等待人工确认',
    done: '已完成', failed: '失败', cancelled: '已取消',
  }[status] || status);
}

function renderTab() {
  const run = S.run;
  if (!run) return '';
  switch (S.tab) {
    case 'overview': return renderOverview();
    case 'tasks': return renderTasks();
    case 'classes': return renderClasses();
    case 'findings': return renderFindings();
    case 'recollect': return renderRecollect();
    case 'fix': return renderFix();
    case 'delivery': return renderDelivery();
    default: return '';
  }
}

function renderOverview() {
  const run = S.run;
  const summary = run.summary || {};
  const counts = run.findings || {};
  const sev = counts.by_severity || {};
  const total = counts.total || 0;
  const p0 = sev.P0 || 0, p1 = sev.P1 || 0, p2 = sev.P2 || 0;
  const coverage = run.coverage || {};
  const classQuota = coverage.class_quota || [];
  const classCounts = coverage.class_counts || run.batch?.stats?.class_counts || {};
  const classItems = Object.entries(classCounts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);
  const checks = Object.entries(counts.by_check || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const probe = run.probe || {};
  const llm = run.llm || {};
  const confidence = counts.by_confidence || {};

  const donutBlock = window.Viz
    ? Viz.donut({ P0: p0, P1: p1, P2: p2, total })
    : `<div class="legend"><span>P0 ${p0}</span><span>P1 ${p1}</span><span>P2 ${p2}</span></div>`;

  const gaugeBlock = window.Viz
    ? Viz.gauge(coverage.score ?? 0, 100)
    : `<div class="bar"><i style="width:${Math.min(100, coverage.score || 0)}%"></i></div>`;

  const checksBlock = (window.Viz && checks.length)
    ? Viz.bars(checks.map(([name, n]) => ({
        label: Viz.checkName(name),
        value: n,
        cls: (name.includes('duplicate') || name.includes('missing')) ? 'red' : '',
      })))
    : '';

  const classBlock = (window.Viz && classItems.length)
    ? `<div class="viz-bars">${Viz.classBars(classItems)}</div>`
    : '';

  return `
  <div class="section">
    <div class="grid3">
      <div class="panel">
        <h3>问题构成</h3><p>${total} 条证据 · ${confidence.candidate || 0} 条候选</p>
        ${donutBlock}
      </div>
      <div class="panel">
        <h3>覆盖率</h3><p>规范配额 vs 实际数据</p>
        ${gaugeBlock}
        ${(coverage.scenes || []).length ? '<div class="tiny" style="margin:4px 0 2px">场景抽样达标情况（当前 / 规范要求）</div>' : ''}
        ${(coverage.scenes || []).slice(0, 4).map((scene) => `<div class="rowline"><span>${esc(scene.name)}</span><span>${scene.actual}/${scene.required || '—'}</span></div>`).join('')}
      </div>
      <div class="panel">
        <h3>双通道质检</h3><p>确定性规则 + 模型交叉复核</p>
        <div class="viz-stat-grid">
          <div class="viz-stat"><b data-count="${confidence.deterministic || 0}">${confidence.deterministic || 0}</b><span>确定性证据</span></div>
          <div class="viz-stat"><b data-count="${confidence.candidate || 0}">${confidence.candidate || 0}</b><span>模型候选</span></div>
          <div class="viz-stat"><b data-count="${llm.calls || 0}">${llm.calls || 0}</b><span>LLM 调用</span></div>
          <div class="viz-stat"><b data-count="${llm.seconds || 0}" data-decimals="1">${llm.seconds || 0}s</b><span>LLM 耗时</span></div>
        </div>
        <div class="rowline" style="margin-top:8px"><span>推理设备</span><span>${esc(probe.device || (probe.available ? '—' : '本轮未启用模型复核'))}</span></div>
        <div class="rowline"><span>推理耗时</span><span>${probe.seconds != null ? probe.seconds + 's' : (probe.available ? '—' : '—（未执行）')}</span></div>
      </div>
    </div>
  </div>
  ${checksBlock ? `<div class="section"><h3>检查项分布</h3><div class="panel">${checksBlock}</div></div>` : ''}
  ${classBlock ? `<div class="section"><h3>类别实例分布</h3><div class="panel">${classBlock}</div></div>` : ''}
  <div class="section"><h3>类别配额</h3><div class="panel">
    ${classQuota.length ? classQuota.map((item) => {
      const ratio = item.required ? Math.min(1, item.actual / item.required) : 0;
      return `<div class="rowline"><span>${esc(item.name)} <span class="muted">${item.actual}/${item.required || '—'}</span></span><span>${item.required ? (ratio * 100).toFixed(0) + '%' : '无配额'}</span></div>
      <div class="bar ${item.gap ? 'amber' : ''}"><i style="width:${ratio * 100}%"></i></div>`;
    }).join('') : '<div class="empty-note">规范未设置类别配额</div>'}
  </div></div>
  <div class="section"><h3>方法与边界</h3><div class="panel">
    ${(summary.limitations || []).map((x) => `<div class="rowline"><span>${esc(x)}</span><span></span></div>`).join('') || '<span class="muted">运行完成后显示</span>'}
  </div></div>`;
}

function renderTasks() {
  const plan = S.run.task_plan || {};
  const effort = plan.effort || {};
  if (!plan.roles) return '<div class="empty-note">任务拆解尚未生成</div>';
  return `
  <div class="section"><div class="grid3">
    <div class="panel"><h3>总工时</h3><b style="font:700 32px/1.2 var(--mono);color:var(--cyan)">${effort.total_hours}h</b><p>按规范基准与脚本公式计算</p></div>
    <div class="panel"><h3>建议投入</h3><b style="font:700 32px/1.2 var(--mono);color:var(--lime)">${effort.headcount} 人</b><p>${plan.inputs?.deadline_days || '—'} 天交付窗口</p></div>
    <div class="panel"><h3>人工抽检</h3><b style="font:700 32px/1.2 var(--mono);color:var(--amber)">${effort.review_images} 张</b><p>${effort.review_boxes} 个实例 · ${pct(plan.inputs?.sample_rate)}</p></div>
  </div></div>
  <div class="section"><h3>人员安排</h3><div class="panel"><table>
    <tr><th>角色</th><th>人数</th><th>工时</th><th>职责</th></tr>
    ${(plan.roles || []).map((r) => `<tr><td>${esc(r.role)}</td><td>${r.headcount}</td><td>${r.hours}h</td><td>${esc(r.responsibility)}</td></tr>`).join('')}
  </table></div></div>
  <div class="section"><h3>里程碑与质量门</h3><div class="panel"><table>
    <tr><th>阶段</th><th>名称</th><th>产出</th><th>质量门</th></tr>
    ${(plan.milestones || []).map((m) => `<tr><td><code>${esc(m.day)}</code></td><td>${esc(m.name)}</td><td>${esc(m.output)}</td><td>${esc(m.gate)}</td></tr>`).join('')}
  </table></div></div>
  <div class="section"><h3>计算假设</h3><div class="panel"><pre class="trace-log">${esc(JSON.stringify(plan.assumptions || {}, null, 2))}</pre></div></div>`;
}

function renderClasses() {
  const classes = S.run.classes || {};
  const rows = classes.classes || [];
  if (!rows.length) return '<div class="empty-note">类别映射尚未生成</div>';
  const conflicts = S.findings.filter((f) => f.check.startsWith('class_') || f.check === 'spec_class_missing');
  return `
  <div class="section"><h3>Canonical 类别表</h3><div class="panel"><table>
    <tr><th>ID</th><th>类别</th><th>来源（批次:原 ID）</th><th>规范内</th></tr>
    ${rows.map((c) => `<tr><td><code>${c.canonical_id}</code></td><td><b>${esc(c.name)}</b></td>
      <td>${(c.sources || []).map((s) => `${esc(s.batch)}:${s.old_id}`).join('；') || '<span class="muted">仅规范</span>'}</td>
      <td>${c.in_spec ? '<span class="badge ok">是</span>' : '<span class="badge p1">否</span>'}</td></tr>`).join('')}
  </table></div></div>
  <div class="section"><h3>冲突与缺项</h3><div class="panel">
    ${conflicts.length ? conflicts.map((f) => `<div class="rowline"><span><span class="badge ${f.severity.toLowerCase()}">${f.severity}</span> ${esc(f.message)}</span><span>${esc(f.check)}</span></div>`).join('') : '<div class="empty-note">未发现类别表冲突</div>'}
  </div></div>
  ${(classes.missing_in_data || []).length ? `<div class="section"><h3>规范有、数据没有</h3><div class="panel">${classes.missing_in_data.map((x) => `<span class="badge muted" style="margin:3px">${esc(x)}</span>`).join('')}</div></div>` : ''}`;
}

function renderFindings() {
  if (!S.findingsLoaded) {
    return window.Viz
      ? `<div class="section"><h3>加载证据中</h3>${Viz.skeletonRows(6)}</div>`
      : '<div class="empty-note">正在加载证据…</div>';
  }
  const filtered = filteredFindings();
  const checks = Object.keys(S.findingsMeta.checks || {}).sort();
  return `
  <div class="toolbar">
    ${severityChip('', '全部')}${severityChip('P0', 'P0')}${severityChip('P1', 'P1')}${severityChip('P2', 'P2')}
    <span style="width:12px"></span>
    ${confidenceChip('', '全部置信度')}${confidenceChip('deterministic', '确定性')}${confidenceChip('candidate', '候选')}
    <span style="flex:1"></span>
    <span class="muted" style="font-size:11.5px;align-self:center">${filtered.length} / ${S.findings.length} 条</span>
  </div>
  <div class="toolbar">
    <select class="input" id="checkFilter" style="max-width:260px">
      <option value="">全部检查项</option>
      ${checks.map((c) => `<option value="${esc(c)}" ${S.filter.check === c ? 'selected' : ''}>${esc(c)} (${S.findingsMeta.checks[c]})</option>`).join('')}
    </select>
    <button class="chip" id="reloadFindings">刷新证据</button>
    <button class="chip" id="downloadReport">打开 HTML 报告</button>
  </div>
  <div id="findingList">
    ${filtered.length ? filtered.map(findingRow).join('') : '<div class="empty-note">当前筛选没有结果</div>'}
  </div>`;
}

function severityChip(value, label) {
  return `<button class="chip ${S.filter.severity === value ? 'active' : ''}" data-filter="severity" data-value="${value}">${label}</button>`;
}
function confidenceChip(value, label) {
  return `<button class="chip ${S.filter.confidence === value ? 'active' : ''}" data-filter="confidence" data-value="${value}">${label}</button>`;
}

function filteredFindings() {
  return S.findings.filter((f) => (!S.filter.severity || f.severity === S.filter.severity)
    && (!S.filter.confidence || f.confidence === S.filter.confidence)
    && (!S.filter.check || f.check === S.filter.check));
}

function findingRow(f) {
  const sampleId = f.subject?.sample_id;
  const thumb = sampleId !== undefined
    ? `<img class="thumb" src="/api/runs/${S.runId}/thumb/${sampleId}" loading="lazy" alt="">`
    : '<span class="muted">—</span>';
  const status = f.status === 'accepted' ? '<span class="badge ok">已确认</span>'
    : f.status === 'rejected' ? '<span class="badge muted">已排除</span>' : '';
  return `<div class="finding-row ${f.severity.toLowerCase()} ${f.status !== 'open' ? 'done' : ''}" data-sample="${sampleId ?? ''}" data-finding="${esc(f.id)}">
    <div>${thumb}</div>
    <div><span class="badge ${f.severity.toLowerCase()}">${f.severity}</span><div class="f-check">${esc(window.Viz ? Viz.checkName(f.check) : f.check)}</div></div>
    <div><div class="f-msg">${esc(f.message)}</div><div class="f-check"><span class="badge ${f.confidence}">${f.confidence === 'candidate' ? '候选' : '确定性'}</span></div></div>
    <div class="f-img">${esc(f.subject?.image_rel || '')}</div>
    <div class="f-status">${status || '待裁定'}</div>
  </div>`;
}

function bindFindings() {
  $$('#tabContent .chip[data-filter]').forEach((button) => button.addEventListener('click', () => {
    S.filter[button.dataset.filter] = button.dataset.value;
    S.renderKey = '';
    renderRun();
  }));
  const check = $('#checkFilter');
  if (check) check.addEventListener('change', () => {
    S.filter.check = check.value;
    S.renderKey = '';
    renderRun();
  });
  $$('#findingList .finding-row').forEach((row) => row.addEventListener('click', () => {
    const sampleId = row.dataset.sample;
    if (sampleId !== '') openDrawer(Number(sampleId), row.dataset.finding);
  }));
  const reload = $('#reloadFindings');
  if (reload) reload.addEventListener('click', async () => { await loadFindings(); S.renderKey = ''; renderRun(); });
  const report = $('#downloadReport');
  if (report) report.addEventListener('click', () => window.open(`/api/runs/${S.runId}/artifact/report.html`, '_blank'));
}

function renderRecollect() {
  const items = S.run.recollect || [];
  if (!items.length) return '<div class="empty-note">没有补采缺口，或运行尚未完成</div>';
  const counts = items.reduce((acc, x) => { acc[x.priority] = (acc[x.priority] || 0) + 1; return acc; }, {});
  return `
  <div class="section"><div class="grid3">
    <div class="panel"><h3>补采工单</h3><b style="font:700 32px/1.2 var(--mono);color:var(--cyan)">${items.length}</b><p>条可派工行动项</p></div>
    <div class="panel"><h3>P0 缺口</h3><b style="font:700 32px/1.2 var(--mono);color:var(--red)">${counts.P0 || 0}</b><p>需优先补齐</p></div>
    <div class="panel"><h3>P1 缺口</h3><b style="font:700 32px/1.2 var(--mono);color:var(--amber)">${counts.P1 || 0}</b><p>按计划补齐</p></div>
  </div></div>
  <div class="section"><div class="panel"><table>
    <tr><th>编号</th><th>优先级</th><th>目标</th><th>当前/要求</th><th>原因</th><th>动作</th><th>验收标准</th></tr>
    ${items.map((x) => `<tr><td><code>${esc(x.id)}</code></td><td><span class="badge ${x.priority.toLowerCase()}">${x.priority}</span></td>
      <td>${esc(x.target)}</td><td>${x.current} / ${x.required || '—'}</td><td>${esc(x.reason)}</td>
      <td>${esc(x.action)}</td><td>${esc(x.acceptance)}</td></tr>`).join('')}
  </table></div></div>
  <div class="section"><div class="panel"><h3>导出</h3><p>补采清单同时写入交付包 <code>recollect.csv</code>，可直接派工。</p>
    <a class="chip" style="display:inline-block;margin-top:8px" href="/api/runs/${S.runId}/artifact/recollect.csv">下载 CSV</a></div></div>`;
}

function renderFix() {
  const fix = S.run.fix || {};
  if (!fix.note) return '<div class="empty-note">修复预览尚未生成</div>';
  const actions = fix.actions || {};
  const diff = fix.diff_preview || [];
  return `
  <div class="section"><div class="grid3">
    <div class="panel"><h3>可修复文件</h3><b style="font:700 32px/1.2 var(--mono);color:var(--lime)">${fix.changed_files || 0}</b><p>只写入新目录，不覆盖原标签</p></div>
    <div class="panel"><h3>动作</h3>${Object.entries(actions).map(([k, v]) => `<div class="rowline"><span>${esc(k)}</span><span>${v}</span></div>`).join('') || '<p class="muted">无自动动作</p>'}</div>
    <div class="panel"><h3>转人工</h3><b style="font:700 32px/1.2 var(--mono);color:var(--amber)">${fix.manual_count || 0}</b><p>格式错误/无法安全映射</p></div>
  </div></div>
  <div class="section"><div class="panel"><h3>修复预览</h3><p>${esc(fix.note)}</p>
    ${fix.available ? `<a class="chip" style="display:inline-block;margin-top:8px" href="/api/runs/${S.runId}/fixed.zip">下载修复包 zip</a>` : ''}
    <table style="margin-top:10px"><tr><th>图片</th><th>标签</th><th>动作</th><th>行数 前→后</th></tr>
    ${diff.map((d) => `<tr><td>${esc(d.image_rel)}</td><td>${esc(d.label_rel || '')}</td>
      <td>${d.actions.map((a) => `${esc(a.kind)}${a.line ? ' L' + a.line : ''}`).join('；')}</td>
      <td>${d.before_lines} → ${d.after_lines}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">无变更</td></tr>'}
    </table></div></div>`;
}

function renderDelivery() {
  const artifacts = S.run.artifacts || [];
  const summary = S.run.summary || {};
  return `
  <div class="section"><div class="grid2">
    <div class="panel"><h3>交付包</h3><p>报告、证据、补采清单、修复预览与审计轨迹。</p>
      <a class="primary" style="width:auto;display:inline-flex;margin-top:12px" href="/api/runs/${S.runId}/download">下载完整交付包 ↓</a>
      <div class="hint">包含 HTML/Markdown 报告、JSON 证据、CSV 工单、证据缩略图；不含原始图片。</div>
    </div>
    <div class="panel"><h3>结论</h3>
      <div class="rowline"><span>质量门</span><span>${esc(summary.gate || '—')}</span></div>
      <div class="rowline"><span>P0 / P1 / P2</span><span>${summary.p0 || 0} / ${summary.p1 || 0} / ${summary.p2 || 0}</span></div>
      <div class="rowline"><span>覆盖率</span><span>${summary.coverage_score ?? '—'}%</span></div>
      <div class="rowline"><span>运行耗时</span><span>${summary.duration_seconds ?? '—'}s</span></div>
      <div class="rowline"><span>LLM 调用</span><span>${summary.llm?.calls ?? 0} 次</span></div>
    </div>
  </div></div>
  <div class="section"><h3>文件清单</h3><div class="panel">
    ${artifacts.map((a) => `<div class="artifact"><a href="/api/runs/${S.runId}/artifact/${encodeURIComponent(a.name)}" ${a.name.endsWith('.html') ? 'target="_blank"' : ''}>${esc(a.name)}</a><span class="muted mono">${(a.size / 1024).toFixed(0)} KB</span></div>`).join('') || '<div class="empty-note">尚未生成</div>'}
  </div></div>
  <div class="section"><h3>审计轨迹</h3><div class="panel"><a class="chip" href="/api/runs/${S.runId}/artifact/trace.jsonl">下载 trace.jsonl</a></div></div>`;
}

// ---------- 证据抽屉 ----------
async function openDrawer(sampleId, findingId) {
  if (!S.runId) return;
  try {
    const data = await api(`/api/runs/${S.runId}/sample/${sampleId}`);
    S.sample = data;
    S.drawerSampleId = sampleId;
    S.selectedFinding = findingId || data.findings[0]?.id || null;
    $('#drawer').hidden = false;
    renderDrawer();
  } catch (error) {
    toast(`证据加载失败：${error.message}`, true);
  }
}

function closeDrawer() {
  $('#drawer').hidden = true;
  S.sample = null;
}

function renderDrawer() {
  const data = S.sample;
  if (!data) return;
  const sample = data.sample;
  $('#drawerTitle').textContent = `${sample.stem} · ${sample.scene}`;
  $('#evidenceMeta').innerHTML = `
    <span class="badge muted">${sample.width}×${sample.height}</span>
    <span>批次 ${esc(sample.batch)}</span><span>split ${esc(sample.split)}</span>
    <span>标注 ${data.objects.length} 个</span><span>问题 ${data.findings.length} 条</span>`;
  const list = $('#evidenceList');
  list.innerHTML = data.findings.length ? data.findings.map((f) => `
    <div class="evidence-item ${f.severity.toLowerCase()} ${f.id === S.selectedFinding ? 'active' : ''}" data-id="${esc(f.id)}">
      <div class="row"><span class="badge ${f.severity.toLowerCase()}">${f.severity}</span>
        <span class="badge ${f.confidence}">${f.confidence === 'candidate' ? '候选' : '确定性'}</span>
        <code class="muted">${esc(f.check)}</code><span class="badge muted">${esc(f.status)}</span></div>
      <p>${esc(f.message)}</p>
      <div class="adjudicate">
        <input placeholder="裁定备注（可选）" data-note="${esc(f.id)}">
        <button class="acc" data-action="accept" data-id="${esc(f.id)}">确认</button>
        <button class="rej" data-action="reject" data-id="${esc(f.id)}">排除</button>
      </div>
    </div>`).join('') : '<div class="empty-note">该图没有关联问题，可查看标注本身</div>';
  list.querySelectorAll('.evidence-item').forEach((item) => item.addEventListener('click', (event) => {
    if (event.target.closest('button') || event.target.closest('input')) return;
    S.selectedFinding = item.dataset.id;
    renderDrawer();
  }));
  list.querySelectorAll('button[data-action]').forEach((button) => button.addEventListener('click', () => {
    const note = list.querySelector(`input[data-note="${button.dataset.id}"]`)?.value || '';
    adjudicate(button.dataset.id, button.dataset.action, note);
  }));
  drawEvidence();
}

function drawEvidence() {
  const data = S.sample;
  if (!data) return;
  const canvas = $('#evidenceCanvas');
  const image = new Image();
  image.onload = () => {
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0);
    const w = canvas.width, h = canvas.height;
    // GT
    data.objects.forEach((obj) => {
      ctx.strokeStyle = 'rgba(123,216,143,.95)';
      ctx.fillStyle = 'rgba(123,216,143,.10)';
      ctx.lineWidth = Math.max(2, w / 900);
      if (obj.kind === 'polygon') {
        const pts = [];
        for (let i = 0; i < obj.coords.length; i += 2) pts.push([obj.coords[i] * w, obj.coords[i + 1] * h]);
        if (pts.length > 2) {
          ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
          pts.slice(1).forEach((p) => ctx.lineTo(p[0], p[1]));
          ctx.closePath(); ctx.fill(); ctx.stroke();
        }
      } else {
        const [cx, cy, bw, bh] = obj.bbox;
        ctx.strokeRect((cx - bw / 2) * w, (cy - bh / 2) * h, bw * w, bh * h);
      }
    });
    // findings
    data.findings.forEach((f) => {
      if (!f.subject?.bbox) return;
      const [cx, cy, bw, bh] = f.subject.bbox;
      const selected = f.id === S.selectedFinding;
      const color = f.severity === 'P0' ? '#ff5f56' : f.severity === 'P1' ? '#ffb020' : '#4dd0e1';
      ctx.strokeStyle = color;
      ctx.lineWidth = selected ? Math.max(4, w / 420) : Math.max(2, w / 800);
      ctx.setLineDash(selected ? [] : [Math.max(6, w / 260), Math.max(4, w / 500)]);
      ctx.strokeRect((cx - bw / 2) * w, (cy - bh / 2) * h, bw * w, bh * h);
      ctx.setLineDash([]);
      if (selected) {
        ctx.fillStyle = 'rgba(0,0,0,.72)';
        const text = `${f.severity} ${f.check}`;
        ctx.font = `${Math.max(12, w / 55)}px Consolas,monospace`;
        const tw = ctx.measureText(text).width;
        const x = Math.max(4, (cx - bw / 2) * w);
        const y = Math.max(6, (cy - bh / 2) * h - 6);
        ctx.fillRect(x, y - Math.max(14, w / 50), tw + 10, Math.max(16, w / 44));
        ctx.fillStyle = color;
        ctx.fillText(text, x + 5, y);
      }
    });
  };
  image.src = data.image_url;
}

async function adjudicate(findingId, action, note) {
  try {
    const updated = await api(`/api/runs/${S.runId}/adjudicate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ finding_id: findingId, action, note }),
    });
    const index = S.findings.findIndex((f) => f.id === findingId);
    if (index >= 0) S.findings[index] = updated;
    if (S.sample) {
      const local = S.sample.findings.find((f) => f.id === findingId);
      if (local) { local.status = updated.status; local.note = updated.note; }
    }
    toast(action === 'accept' ? `已确认 ${findingId}` : `已排除 ${findingId}`);
    renderDrawer();
    S.renderKey = '';
    renderRun();
  } catch (error) {
    toast(`裁定失败：${error.message}`, true);
  }
}

// ---------- 人工确认 ----------
function openQuestions() {
  const run = S.run;
  if (!run || run.status !== 'needs_input') return;
  if (S.modalFor === run.id) return;
  S.modalFor = run.id;
  const questions = run.questions || [];
  $('#questionList').innerHTML = questions.map((q) => `<div class="question"><b>${esc(q.question)}</b><span>${esc(q.why || '')}</span></div>`).join('');
  const classes = [];
  (run.batch_names || []).forEach((item) => Object.values(item.names || {}).forEach((name) => {
    if (!classes.includes(name)) classes.push(name);
  }));
  $('#questionForm').innerHTML = `
    <div class="def-row" style="margin-top:14px"><label>项目名</label><input class="input" id="qProject" value="${esc(run.spec?.data?.project || '')}" placeholder="项目名称"></div>
    <div class="def-row"><label>标签格式</label><select class="input" id="qLabelFormat">
      <option value="segmentation" ${run.spec?.data?.label_format === 'segmentation' ? 'selected' : ''}>segmentation（分割多边形）</option>
      <option value="detection" ${run.spec?.data?.label_format === 'detection' ? 'selected' : ''}>detection（检测框）</option>
      <option value="either">either（两者都允许）</option></select></div>
    ${classes.length ? `<div style="margin-top:14px"><div class="tiny">从批次类别表补齐（可留空）</div>
      ${classes.map((name) => `<div class="def-row"><label>${esc(name)}</label><input class="input" data-class="${esc(name)}" placeholder="判定标准（包含/排除）"></div>`).join('')}</div>` : ''}`;
  $('#modal').hidden = false;
}

async function submitQuestions() {
  const classes = [];
  $$('#questionForm input[data-class]').forEach((input) => {
    classes.push({ name: input.dataset.class, definition: input.value.trim() });
  });
  const answers = {
    project: $('#qProject')?.value.trim() || '',
    label_format: $('#qLabelFormat')?.value || 'either',
  };
  if (classes.length) answers.classes = classes;
  else {
    const names = [];
    (S.run.batch_names || []).forEach((item) => Object.values(item.names || {}).forEach((n) => names.includes(n) || names.push(n)));
    if (names.length) answers.classes = names.map((name) => ({ name, definition: '' }));
  }
  $('#modal').hidden = true;
  S.modalFor = '';
  try {
    await api(`/api/runs/${S.runId}/resume`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(answers),
    });
    toast('已确认，继续执行');
    S.run.status = 'running';
    S.renderKey = '';
    renderRun();
    schedulePoll();
  } catch (error) {
    toast(`继续失败：${error.message}`, true);
  }
}

init();