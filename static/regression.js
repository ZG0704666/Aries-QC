/* 模型回归门禁：独立的小型状态机，复用 app.js 的 $/esc/fmt/pct/toast/api 和 Viz helpers。 */
(function () {
  const RS = {
    datasets: [], profiles: [], thresholds: {},
    runId: null, run: null, tab: 'overview',
    pollTimer: null, renderKey: '',
    cases: { missed: [], falsePositive: [], loaded: false },
  };

  async function init() {
    bind();
    try {
      const options = await api('/api/regression/options');
      RS.datasets = options.datasets || [];
      RS.profiles = options.profiles || [];
      RS.thresholds = options.thresholds || {};
      renderOptions();
      const last = localStorage.getItem('ariesqc.regRun');
      if (last) {
        try { await openRun(last); } catch { /* 运行已不存在，忽略 */ }
      }
    } catch (error) {
      toast(`回归门禁服务未就绪：${error.message}`, true);
    }
  }

  function renderOptions() {
    const datasetSel = $('#regDatasetSelect');
    datasetSel.innerHTML = '<option value="">选择旧展项数据集…</option>' + RS.datasets.map((d) =>
      `<option value="${esc(d.id)}">${esc(d.name)} · ${esc(d.note)}</option>`).join('');
    const profileOptions = RS.profiles.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
    $('#regBaselineSelect').innerHTML = '<option value="">选择基线模型档案…</option>' + profileOptions;
    $('#regCandidateSelect').innerHTML = '<option value="">选择候选模型档案…</option>' + profileOptions;
    const baselineDefault = RS.profiles.find((p) => p.id === 'sim_baseline');
    if (baselineDefault) $('#regBaselineSelect').value = baselineDefault.id;
    $('#regThMap50').value = RS.thresholds.map50_min ?? 0.75;
    $('#regThDrop').value = RS.thresholds.per_class_drop_max ?? 0.05;
    $('#regThRecall').value = RS.thresholds.recall_drop_max ?? 0.1;
    if (!RS.datasets.length) toast('未发现回归门禁演示数据集，请检查 fixtures/regression/datasets', true);
  }

  function bind() {
    $('#regStartBtn').addEventListener('click', startRun);
    $('#regHeroStart').addEventListener('click', () => quickDemo('v2'));
    $$('[data-reg-demo]').forEach((button) => button.addEventListener('click', () => quickDemo(button.dataset.regDemo)));
    $('#regTabs').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-tab]');
      if (!button) return;
      RS.tab = button.dataset.tab;
      $$('#regTabs button').forEach((item) => item.classList.toggle('active', item === button));
      RS.renderKey = '';
      renderRun();
    });
  }

  function quickDemo(variant) {
    const dataset = RS.datasets.find((d) => d.id === 'old_exhibits') || RS.datasets[0];
    const baseline = RS.profiles.find((p) => p.id === 'sim_baseline');
    const candidate = RS.profiles.find((p) => p.id === `sim_candidate_${variant}`);
    if (!dataset || !baseline || !candidate) return toast('演示档案未配置，请检查 fixtures/regression', true);
    $('#regDatasetSelect').value = dataset.id;
    $('#regBaselineSelect').value = baseline.id;
    $('#regCandidateSelect').value = candidate.id;
    startRun();
  }

  async function startRun() {
    const datasetId = $('#regDatasetSelect').value;
    const baselineId = $('#regBaselineSelect').value;
    const candidateId = $('#regCandidateSelect').value;
    if (!datasetId) return toast('请选择旧展项数据集', true);
    if (!baselineId || !candidateId) return toast('请选择基线和候选模型档案', true);
    const thresholds = {
      map50_min: Number($('#regThMap50').value) || 0.75,
      per_class_drop_max: Number($('#regThDrop').value) || 0.05,
      recall_drop_max: Number($('#regThRecall').value) || 0.1,
      critical_classes: RS.thresholds.critical_classes || [],
    };
    $('#regStartBtn').disabled = true;
    try {
      const created = await api('/api/regression/runs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: datasetId, baseline_id: baselineId, candidate_id: candidateId, thresholds }),
      });
      RS.runId = created.id;
      localStorage.setItem('ariesqc.regRun', created.id);
      RS.run = null; RS.renderKey = ''; RS.tab = 'overview'; RS.cases = { missed: [], falsePositive: [], loaded: false };
      $$('#regTabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'overview'));
      $('#regWelcome').hidden = true;
      $('#regRunView').hidden = false;
      await openRun(created.id);
      toast('回归检测已接单');
    } catch (error) {
      toast(`接单失败：${error.message}`, true);
    } finally {
      $('#regStartBtn').disabled = false;
    }
  }

  async function openRun(runId) {
    RS.runId = runId;
    localStorage.setItem('ariesqc.regRun', runId);
    RS.run = await api(`/api/regression/runs/${runId}`);
    $('#regWelcome').hidden = true;
    $('#regRunView').hidden = false;
    renderTrace();
    renderRun();
    if (['running', 'queued', 'created'].includes(RS.run.status)) schedulePoll();
    else if (RS.run.status === 'done') await loadCases();
  }

  function schedulePoll() {
    clearTimeout(RS.pollTimer);
    RS.pollTimer = setTimeout(poll, 700);
  }

  async function poll() {
    if (!RS.runId) return;
    try {
      RS.run = await api(`/api/regression/runs/${RS.runId}`);
      renderTrace();
      renderRun();
      const status = RS.run.status;
      if (status === 'done') {
        await loadCases();
        renderRun();
        toast('回归检测完成');
      } else if (status === 'failed' || status === 'cancelled') {
        toast(`运行${status === 'failed' ? '失败' : '已取消'}：${RS.run.error || ''}`, status === 'failed');
      } else {
        schedulePoll();
      }
    } catch (error) {
      toast(`轮询失败：${error.message}`, true);
    }
  }

  async function loadCases() {
    try {
      const [missed, fp] = await Promise.all([
        api(`/api/regression/runs/${RS.runId}/cases?type=missed&limit=200`),
        api(`/api/regression/runs/${RS.runId}/cases?type=fp&limit=200`),
      ]);
      RS.cases = { missed: missed.items || [], falsePositive: fp.items || [], loaded: true };
    } catch (error) {
      toast(`案例加载失败：${error.message}`, true);
    }
  }

  function renderTrace() {
    const state = RS.run?.status || 'idle';
    $('#regTraceState').textContent = state.toUpperCase();
    const steps = RS.run?.steps || [];
    const trace = $('#regTrace');
    if (!steps.length) {
      trace.innerHTML = '<div class="trace-empty">等待接单…</div>';
      return;
    }
    trace.innerHTML = steps.map((step) => `
      <div class="trace-step ${esc(step.status)}">
        <span class="t-dot"></span>
        <div><div class="t-name">${esc(step.title)}</div><div class="t-meta">${esc(traceMeta(step))}</div></div>
      </div>`).join('');
    trace.scrollTop = trace.scrollHeight;
  }

  function traceMeta(step) {
    const detail = step.detail || {};
    const time = step.duration ? `${step.duration}s` : '…';
    if (detail.images !== undefined) return `${detail.images} 图 · ${detail.classes || 0} 类 · ${time}`;
    if (detail.ap50 !== undefined) return `P ${fmtNum(detail.precision)} · R ${fmtNum(detail.recall)} · AP50 ${fmtNum(detail.ap50)} · ${time}`;
    if (detail.degraded_classes !== undefined) return `退化 ${detail.degraded_classes.length} 类 · ${time}`;
    if (detail.verdict) return `${detail.verdict} · ${time}`;
    if (detail.artifacts !== undefined) return `${detail.artifacts} 个交付物 · ${time}`;
    if (detail.baseline) return `${detail.baseline} vs ${detail.candidate} · ${time}`;
    return time;
  }

  function fmtNum(n) { return n == null ? '—' : Number(n).toFixed(3); }

  function renderRun() {
    const run = RS.run;
    if (!run) return;
    $('#regRunIdLabel').textContent = `RUN ${run.id} · ${String(run.status).toUpperCase()}`;
    $('#regDatasetName').textContent = (run.dataset || {}).names ? `旧展项回归门禁 · ${run.dataset.images} 图` : '模型回归门禁';
    const decision = run.decision;
    const badge = $('#regVerdictBadge');
    if (decision) {
      badge.className = `gate ${decision.verdict.toLowerCase()}`;
      badge.textContent = { RELEASE: '可放行', WARNING: '需关注', BLOCK: '拦截发布' }[decision.verdict] || decision.verdict;
      $('#regHeadline').textContent = decision.summary;
    } else {
      badge.className = 'gate';
      badge.textContent = statusText(run.status);
      $('#regHeadline').textContent = statusText(run.status);
    }

    const busyStates = ['created', 'queued', 'running'];
    if (busyStates.includes(run.status)) {
      const steps = run.steps || [];
      const done = steps.filter((s) => s.status === 'ok').length;
      const total = steps.length || 1;
      const current = steps.find((s) => s.status === 'running');
      const label = current ? current.title : (run.progress || {}).label || '等待开始…';
      $('#regKpis').innerHTML = '';
      $('#regTabContent').innerHTML = window.Viz
        ? Viz.loaderHTML(done / total, '回归检测执行中', `▸ ${label}`)
        : `<div class="empty-note">执行中 · ${done}/${total}</div>`;
      if (window.Viz) Viz.mount($('#regTabContent'));
      return;
    }

    const comparison = run.comparison || {};
    const overall = comparison.overall || {};
    const kpiItems = [
      { label: '基线 mAP50', value: fmtPct(overall.baseline?.ap50), cls: '' },
      { label: '候选 mAP50', value: fmtPct(overall.candidate?.ap50), cls: decision?.verdict === 'BLOCK' ? 'p0' : '' },
      { label: '召回率跌幅', value: fmtPct(overall.drop?.recall), cls: (overall.drop?.recall || 0) > 0 ? 'p1' : 'pass' },
      { label: '退化类别', value: (comparison.degraded_classes || []).length, unit: '类', cls: (comparison.degraded_classes || []).length ? 'p1' : 'pass' },
      { label: '新增漏检', value: (comparison.missed_cases || []).length, unit: '条' },
      { label: '新增错检', value: (comparison.false_positive_cases || []).length, unit: '条' },
    ];
    $('#regKpis').innerHTML = kpiItems.map((it) =>
      `<div class="kpi ${it.cls || ''}"><b>${esc(it.value)}</b><span>${esc(it.label)}${it.unit ? ' · ' + esc(it.unit) : ''}</span></div>`).join('');

    const key = `${run.status}|${RS.tab}|${RS.cases.loaded}`;
    if (key === RS.renderKey) return;
    RS.renderKey = key;
    $('#regTabContent').innerHTML = renderTab();
    if (window.Viz) Viz.mount($('#regTabContent'));
    if (RS.tab === 'cases') bindCaseRows();
  }

  function statusText(status) {
    return ({ created: '已创建', queued: '排队中', running: '执行中…', done: '已完成', failed: '失败', cancelled: '已取消' }[status] || status);
  }

  function fmtPct(n) { return n == null ? '—' : `${(Number(n) * 100).toFixed(1)}%`; }

  function renderTab() {
    const run = RS.run;
    if (!run || !run.comparison) return '<div class="empty-note">运行尚未完成</div>';
    switch (RS.tab) {
      case 'overview': return renderOverview();
      case 'compare': return renderCompare();
      case 'degraded': return renderDegraded();
      case 'cases': return renderCases();
      case 'suggestions': return renderSuggestions();
      case 'delivery': return renderDelivery();
      default: return '';
    }
  }

  function renderOverview() {
    const decision = RS.run.decision;
    const comparison = RS.run.comparison;
    return `
    <div class="section"><div class="verdict-banner ${decision.verdict.toLowerCase()}">
      <div class="vb-icon">${{ RELEASE: '✓', WARNING: '!', BLOCK: '✕' }[decision.verdict] || '?'}</div>
      <div><b>${esc(decision.summary)}</b><p>基线 ${esc(comparison.baseline_backend)} vs 候选 ${esc(comparison.candidate_backend)}</p></div>
    </div></div>
    <div class="section"><h3>判定原因</h3><div class="reason-list">
      ${decision.reasons.map((r) => `<div class="rl-item">${esc(r)}</div>`).join('')}
    </div></div>
    <div class="section"><h3>退化类别</h3><div class="panel">
      ${comparison.degraded_classes.length
        ? comparison.degraded_classes.map((c) => `<span class="badge p1" style="margin:3px">${esc(c)}</span>`).join('')
        : '<div class="empty-note">没有类别退化</div>'}
    </div></div>`;
  }

  function renderCompare() {
    const comparison = RS.run.comparison;
    const names = Object.keys(comparison.per_class);
    return `
    <div class="section"><h3>逐类 AP50 对比</h3>
    <div class="compare-legend"><span><i class="baseline-dot"></i>基线</span><span><i class="candidate-dot"></i>候选</span></div>
    <div class="panel">
      ${names.map((name) => {
        const row = comparison.per_class[name];
        const baseline = row.baseline.ap50, candidate = row.candidate.ap50;
        const drop = row.drop.ap50;
        return `<div class="compare-bar-row">
          <div class="cls-name ${row.degraded ? 'degraded' : ''}">${esc(name)}</div>
          <div class="compare-bar-track"><div class="compare-bar-fill baseline" style="width:${(baseline * 100).toFixed(1)}%"></div></div>
          <div class="compare-bar-track"><div class="compare-bar-fill candidate ${row.degraded ? 'degraded' : ''}" style="width:${(candidate * 100).toFixed(1)}%"></div></div>
          <div class="compare-drop ${drop > 0 ? 'up' : 'down'}">${drop > 0 ? '↓' : '↑'} ${(Math.abs(drop) * 100).toFixed(1)}%</div>
        </div>`;
      }).join('')}
    </div></div>
    <div class="section"><h3>整体指标</h3><div class="panel"><table>
      <tr><th>指标</th><th>基线</th><th>候选</th><th>变化</th></tr>
      ${['precision', 'recall', 'f1', 'ap50'].map((key) => {
        const label = { precision: '精确率', recall: '召回率', f1: 'F1 分数', ap50: 'mAP50' }[key];
        const o = comparison.overall;
        return `<tr><td>${label}</td><td>${fmtNum(o.baseline[key])}</td><td>${fmtNum(o.candidate[key])}</td><td>${o.drop[key] > 0 ? '↓' : '↑'} ${fmtNum(Math.abs(o.drop[key]))}</td></tr>`;
      }).join('')}
    </table></div></div>`;
  }

  function renderDegraded() {
    const comparison = RS.run.comparison;
    const names = Object.keys(comparison.per_class).filter((n) => comparison.per_class[n].degraded);
    if (!names.length) return '<div class="empty-note">没有类别出现 AP50 跌幅超过阈值</div>';
    const critical = new Set((RS.run.thresholds || {}).critical_classes || []);
    return `
    <div class="section"><div class="panel"><table>
      <tr><th>类别</th><th>基线 AP50</th><th>候选 AP50</th><th>跌幅</th><th>召回率跌幅</th><th>关键类别</th></tr>
      ${names.map((name) => {
        const row = comparison.per_class[name];
        return `<tr><td><b>${esc(name)}</b></td><td>${fmtNum(row.baseline.ap50)}</td><td>${fmtNum(row.candidate.ap50)}</td>
          <td class="compare-drop up">${fmtNum(row.drop.ap50)}</td><td>${fmtNum(row.drop.recall)}</td>
          <td>${critical.has(name) ? '<span class="badge p0">关键</span>' : '<span class="badge muted">普通</span>'}</td></tr>`;
      }).join('')}
    </table></div></div>`;
  }

  function renderCases() {
    if (!RS.cases.loaded) return '<div class="empty-note">正在加载案例…</div>';
    const missed = RS.cases.missed, fp = RS.cases.falsePositive;
    return `
    <div class="section"><h3>候选模型新增漏检（${missed.length}）</h3><div id="missedCaseList">
      ${missed.length ? missed.slice(0, 50).map((c, i) => caseRow(c, 'missed', i)).join('') : '<div class="empty-note">没有新增漏检</div>'}
    </div></div>
    <div class="section"><h3>候选模型新增错检（${fp.length}）</h3><div id="fpCaseList">
      ${fp.length ? fp.slice(0, 50).map((c, i) => caseRow(c, 'fp', i)).join('') : '<div class="empty-note">没有新增错检</div>'}
    </div></div>`;
  }

  function caseRow(c, kind, index) {
    const box = kind === 'missed' ? c.gt_box : c.pred_box;
    const url = `/api/regression/runs/${RS.runId}/image?path=${encodeURIComponent(c.image)}`;
    const extra = kind === 'missed' ? `<span class="badge p1">${esc(c.severity)}</span>` : `<span class="badge candidate">conf ${fmtNum(c.conf)}</span>`;
    return `<div class="case-row" data-kind="${kind}" data-index="${index}">
      <img class="case-thumb" src="${url}" loading="lazy" alt="">
      <div><span class="badge muted">${esc(box.cls_name)}</span></div>
      <div class="f-img">${esc(c.image)}</div>
      <div>${extra}</div>
    </div>`;
  }

  function bindCaseRows() {
    $$('#regTabContent .case-row').forEach((row) => row.addEventListener('click', () => {
      const kind = row.dataset.kind;
      const index = Number(row.dataset.index);
      const item = (kind === 'missed' ? RS.cases.missed : RS.cases.falsePositive)[index];
      openCaseDrawer(item, kind);
    }));
  }

  function openCaseDrawer(item, kind) {
    const box = kind === 'missed' ? item.gt_box : item.pred_box;
    $('#drawerTitle').textContent = `${box.cls_name} · ${kind === 'missed' ? '漏检' : '错检'}`;
    $('#evidenceMeta').innerHTML = `<span class="badge muted">${esc(item.image)}</span>
      ${kind === 'missed' ? `<span class="badge p1">${esc(item.severity)}</span>` : `<span class="badge candidate">conf ${fmtNum(item.conf)}</span>`}`;
    $('#evidenceList').innerHTML = '<div class="empty-note">回归门禁案例没有裁定操作，仅供核验证据。</div>';
    $('#drawer').hidden = false;
    const canvas = $('#evidenceCanvas');
    const image = new Image();
    image.onload = () => {
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(image, 0, 0);
      const [x1, y1, x2, y2] = box.bbox;
      ctx.strokeStyle = kind === 'missed' ? '#7bd88f' : '#ff5f56';
      ctx.lineWidth = Math.max(3, canvas.width / 300);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    };
    image.src = `/api/regression/runs/${RS.runId}/image?path=${encodeURIComponent(item.image)}`;
  }

  function renderSuggestions() {
    const suggestions = RS.run.decision.suggestions || [];
    if (!suggestions.length) return '<div class="empty-note">所有检查通过，没有处理建议</div>';
    return `<div class="section">${suggestions.map((s) => `
      <div class="suggestion-card ${s.priority}">
        <div class="sc-head"><span class="badge ${s.priority === 'high' ? 'p0' : 'p1'}">${s.priority.toUpperCase()}</span><b>${esc(s.action)}</b></div>
        <p>${esc(s.detail)}</p>
        <div class="sc-classes">${(s.affected_classes || []).map((c) => `<span class="badge muted" style="margin:2px">${esc(c)}</span>`).join('')}</div>
      </div>`).join('')}</div>`;
  }

  function renderDelivery() {
    const artifacts = RS.run.artifacts || [];
    return `
    <div class="section"><div class="panel"><h3>交付包</h3><p>回归对比结果、判定与 Markdown 报告。</p>
      <a class="primary" style="width:auto;display:inline-flex;margin-top:12px" href="/api/regression/runs/${RS.runId}/download">下载完整交付包 ↓</a>
    </div></div>
    <div class="section"><h3>文件清单</h3><div class="panel">
      ${artifacts.map((a) => `<div class="artifact"><a href="/api/regression/runs/${RS.runId}/artifact/${encodeURIComponent(a.name)}" ${a.name.endsWith('.md') ? 'target="_blank"' : ''}>${esc(a.name)}</a><span class="muted mono">${(a.size / 1024).toFixed(0)} KB</span></div>`).join('') || '<div class="empty-note">尚未生成</div>'}
    </div></div>`;
  }

  window.RegressionUI = { init, openRun };
})();
