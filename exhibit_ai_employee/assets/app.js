/* 展览互动内容制作员 · 展项内容工作台
   视觉与排版来自上传设计包的 assets/ 四件套（原样保留），本文件是接真实后端后的实现。
   原则：页面上的每个数字都来自 studio_server 的接口或磁盘实测；没有示例用例、没有假进度、
   没有「演示数据」标记。取不到数据时写明取不到，不用占位数字顶替。 */
(() => {
  'use strict';

  const TOKEN_KEY = 'studio_token';
  const PROJECT_KEY = 'studio_project';
  const CHATW_KEY = 'studio_chat_width';
  const VIEWS = [
    ['project', '项目与报价'], ['live', '执行现场'], ['content', '内容成果'],
    ['tests', '测试审核'], ['voice', '语音终端'], ['release', '发布验收'], ['feedback', '反馈改进']
  ];
  const STATUS = {
    draft: ['草稿', ''], running: ['生成中', 'blue'], awaiting_confirmation: ['等待确认', 'amber'],
    tested: ['已自测', 'green'], approved: ['已批准', 'green'], published: ['已发布', 'green'], failed: ['失败', 'red']
  };
  const KIND = {
    receive: '资料接收', locate: '来源定位', cards: '知识卡', draft: '讲解与问答', step: '生成步骤',
    'run.finished': '生成结束', 'run.failed': '生成失败', tests: '自测', review: '审核', voice: '语音',
    publish: '发布', quote: '报价', feedback: '反馈', acceptance: '签收', exhibit: '内容改写',
    authorization: '资料授权', material: '资料导入', issue: '问题处理', chat: '对话'
  };
  const TABS = ['知识卡', '主讲解', '简化版', '追问', '资料外兜底'];

  /* ================= 口令与请求 ================= */
  let TOKEN = (() => {
    let fromQuery = '';
    try { fromQuery = new URLSearchParams(location.search).get('token') || ''; } catch (e) { fromQuery = ''; }
    if (fromQuery) { try { localStorage.setItem(TOKEN_KEY, fromQuery); } catch (e) {} return fromQuery; }
    try { return localStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; }
  })();

  function authHeaders(extra) {
    const out = Object.assign({}, extra || {});
    if (TOKEN) out['X-Access-Token'] = TOKEN;
    return out;
  }
  function withToken(path) {
    if (!TOKEN) return path;
    return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
  }
  function askToken() {
    const value = window.prompt('这个服务启用了访问口令。请输入启动时设置的 STUDIO_ACCESS_TOKEN：', '');
    if (value) { TOKEN = value.trim(); try { localStorage.setItem(TOKEN_KEY, TOKEN); } catch (e) {} location.reload(); }
  }

  let busy = 0;
  function setBusy(on) {
    busy = Math.max(0, busy + (on ? 1 : -1));
    document.body.classList.toggle('is-busy', busy > 0);
  }

  async function request(path, options, silent) {
    const opt = Object.assign({}, options || {});
    opt.headers = authHeaders(opt.body ? { 'Content-Type': 'application/json' } : {});
    if (!silent) setBusy(true);
    let res;
    try {
      res = await fetch(path, opt);
    } catch (error) {
      if (!silent) setBusy(false);
      const err = new Error('连不上本机 studio_server（' + error.message + '）');
      err.offline = true;
      throw err;
    }
    if (!silent) setBusy(false);
    const raw = await res.text();
    let data = null;
    if (raw) { try { data = JSON.parse(raw); } catch (e) { data = { error: raw.slice(0, 300) }; } }
    if (res.status === 401) { const err = new Error('需要访问口令'); err.unauthorized = true; throw err; }
    if (!res.ok) throw new Error((data && data.error) || ('服务返回 HTTP ' + res.status));
    return data || {};
  }

  const api = {
    get: (path) => request(path),
    post: (path, body) => request(path, { method: 'POST', body: JSON.stringify(body || {}) }),
    quiet: (path) => request(path, null, true)
  };

  /* ================= 状态 ================= */
  const S = {
    health: null, projects: [], project: null, events: [], lastEventId: 0,
    view: 'live', exhibitIndex: 0, contentTab: '主讲解', feedbackId: null,
    readerSize: 20, connError: null, chatPending: false, pendingRun: false,
    chatTools: [], chatBusy: false
  };

  /* ================= 小工具 ================= */
  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = (v) => {
    const n = Number(v);
    if (!isFinite(n)) return '—';
    return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  };
  const money = (v) => (v === null || v === undefined || v === '' ? '—' : '¥ ' + num(v));
  const byteText = (n) => {
    const v = Number(n) || 0;
    if (!v) return '—';
    if (v < 1024) return v + ' B';
    if (v < 1048576) return (v / 1024).toFixed(1) + ' KB';
    return (v / 1048576).toFixed(2) + ' MB';
  };
  const timeOf = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(11, 19) || '—';
    return d.toLocaleTimeString('zh-CN', { hour12: false });
  };
  const dateTimeOf = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString('zh-CN', { hour12: false });
  };
  const secOf = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(2) + ' 秒');
  const pill = (text, kind) => `<span class="pill ${kind || ''}">${esc(text)}</span>`;
  // 成组出现的小指标用 stat：只有一个小圆点加文字，不占一块底色。
  // 一屏十几个 pill 会让版面看起来到处是标签，stat 是同一信息的更轻写法。
  const stat = (text, tone) => `<span class="stat${tone ? ' is-' + tone : ''}">${esc(text)}</span>`;
  const note = (html, kind) => `<div class="notice ${kind || ''}">${html}</div>`;
  const act = (action, label, cls, extra) =>
    `<button type="button" class="${cls || ''}" data-action="${action}" ${extra || ''}>${label}</button>`;
  const field = (label, name, value, type, extra) => `<label class="field"><span>${esc(label)}</span>` +
    `<input name="${name}" type="${type || 'text'}" value="${esc(value)}" ` +
    `${type === 'number' ? 'min="0" step="any" inputmode="decimal"' : ''} ${extra || ''}></label>`;

  /* ================= 派生数据 ================= */
  const P = () => S.project;
  const exs = () => (S.project && S.project.exhibits) || [];
  const cur = () => exs()[S.exhibitIndex] || exs()[0] || null;
  const issues = () => (S.project && S.project.issues) || [];
  const testsOf = () => (S.project && S.project.tests) || [];
  const passedCount = () => testsOf().filter((t) => t.status === 'passed').length;
  const allPassed = () => testsOf().length > 0 && passedCount() === testsOf().length;
  const audioOf = (id) => ((S.project && S.project.audio) || {})[id] || null;
  const audioCount = () => exs().filter((e) => audioOf(e.id)).length;
  const paraCount = () => ((S.project && S.project.sources) || [])
    .reduce((sum, s) => sum + (s.paragraphs || []).length, 0);
  const statusMeta = () => STATUS[(S.project && S.project.status) || 'draft'] || [S.project.status, ''];

  function gates() {
    const p = P();
    return {
      authorized: !!(p && p.authorization),
      drafted: exs().length > 0,
      tested: testsOf().length > 0,
      allPassed: allPassed(),
      approved: !!(p && p.review && p.review.decision === 'approved'),
      audio: exs().length > 0 && audioCount() === exs().length,
      clean: issues().length === 0,
      published: !!(p && p.status === 'published'),
      accepted: !!(p && p.acceptance)
    };
  }

  function pipeline(steps, current) {
    return `<ol class="pipeline">${steps.map((s, i) => `<li class="${i < current ? 'done' : i === current ? 'current' : ''}">` +
      `<span class="step-circle">${i < current ? '✓' : i === current ? '•' : i + 1}</span>` +
      `<strong>${s[0]}</strong><small>${s[1] || ''}</small></li>`).join('')}</ol>`;
  }

  function header(title, subtitle, meta) {
    const sm = statusMeta();
    return `<div class="page-header"><div><h2>${esc(title)}</h2><p>${subtitle}</p></div>` +
      `<div class="header-meta">${meta || pill(sm[0], sm[1])}</div></div>`;
  }

  function exhibitTray() {
    return `<div class="exhibit-tray">${exs().map((e, i) => {
      const art = ['<i class="glass"></i><i class="straw"></i>',
        '<i class="speaker"></i>', '<i class="mirror-plane"></i><i class="ray"></i>'][i % 3];
      const a = audioOf(e.id);
      const state = a ? '已合成 · 实测 ' + secOf(a.duration_s) : '无音频';
      const pending = (e.issues || []).length ? stat('待核验', 'fail') : stat('引用可定位', 'pass');
      return `<button type="button" class="exhibit-tile ${S.exhibitIndex === i ? 'active' : ''}" ` +
        `data-action="exhibit" data-value="${i}"><span class="exhibit-art ${['refraction', 'sound', 'colour'][i % 3]}" aria-hidden="true">${art}</span>` +
        `<span><strong>${esc(e.id)} ${esc(e.title)}</strong>${pending}<small>　${state}</small></span></button>`;
    }).join('')}</div>`;
  }

  function eventsHtml(limit) {
    const rows = S.events.slice().sort((a, b) => b.id - a.id).slice(0, limit || 40);
    if (!rows.length) return `<p class="small muted">还没有运行记录。执行任意动作后，这里会按时间倒序出现真实事件。</p>`;
    return `<ul class="event-list">${rows.map((e) => {
      const detail = e.detail || {};
      const ok = detail.ok === false;
      const label = KIND[e.kind] || e.kind;
      const message = detail.message || detail.label || detail.step || '';
      return `<li><span class="event-mark ${ok ? 'wait' : ''}">${ok ? '!' : '✓'}</span><div>` +
        `<time>${timeOf(e.created_at)}</time><strong>${esc(label)}</strong>` +
        `<p>${esc(message || '（无说明）')}</p></div></li>`;
    }).join('')}</ul>`;
  }

  /* ================= 视图：项目与报价 ================= */
  function projectView() {
    const p = P();
    const q = p.quote || {};
    const g = gates();
    const qText = (k, d) => (q[k] === undefined || q[k] === null ? d : q[k]);
    const phases = [
      p.brief ? 'brief 已记录' : '未记录需求',
      q.confirmed ? '范围已确认' : '待确认',
      '未接入',
      '未接入'
    ];
    const step = q.confirmed ? 2 : (p.brief ? 1 : 0);
    const milestones = [
      ['资料授权', p.authorization ? `${p.authorization.confirmed_by} · ${dateTimeOf(p.authorization.at)}` : '待登记'],
      ['草稿生成', g.drafted ? `v${p.version} · ${exs().length} 个展项` : '未生成'],
      ['自测', g.tested ? `${passedCount()}/${testsOf().length} 通过` : '未运行'],
      ['人工审核', p.review ? `${p.review.decision === 'approved' ? '通过' : '要求修改'} · ${p.review.reviewer}` : '未审核'],
      ['发布', g.published ? `已发布 v${p.version}` : '未发布'],
      ['客户签收', p.acceptance ? `${p.acceptance.decision === 'accepted' ? '已签收' : '拒收'} · ${p.acceptance.signer}` : '未签收']
    ];

    return header('项目与报价', `${esc(p.id)} · ${esc(p.name)} · 任务 #${p.task_no} · v${p.version}`,
      pill(q.confirmed ? '范围已确认' : '范围待确认', q.confirmed ? 'green' : 'amber')) +
      pipeline([['需求', phases[0]], ['范围', phases[1]], ['签约', phases[2]], ['回款', phases[3]]], step) +
      `<div class="grid cols-2">
        <section class="panel panel-pad">
          <h3>需求与交付范围</h3>
          <form data-form="quote">
            <div class="field-row">${field('客户名称', 'customer', qText('customer', ''))}${field('内容审核人', 'reviewer', qText('reviewer', ''))}</div>
            <div class="field-row">${field('目标观众', 'audience', qText('audience', p.audience || ''))}${field('讲解目标时长（秒）', 'duration', qText('duration', 45), 'number')}</div>
            ${field('服务范围', 'scope', qText('scope', ''))}
            <dl class="detail-list">
              <div><dt>交付内容</dt><dd>主讲解、简化版、追问与资料外兜底<br>来源知识卡、自测记录、交付包（含 MP3）</dd></div>
              <div><dt>设备范围</dt><dd>网页内容体验<br>眼镜接入与实机验收<b>尚未实现</b></dd></div>
              <div><dt>排除项</dt><dd>多语言、驻场、专用硬件开发及第三方授权</dd></div>
            </dl>
            <div class="inline-actions">
              <button type="submit" class="outline-green" data-mode="save">保存范围与报价</button>
              <button type="submit" class="green" data-mode="confirm">✓ 确认范围</button>
            </div>
          </form>
        </section>
        <div class="stack">
          <section class="panel panel-pad">
            <h3>报价与成本</h3>
            <div class="price">${money(q.price)}</div>
            <div class="metric-row">${stat('合同与回款未接入')}</div>
            <form data-form="money">
              <div class="field-row">${field('报价', 'price', qText('price', ''), 'number')}${field('直接人工', 'labor', qText('labor', ''), 'number')}</div>
              <div class="field-row">${field('模型与语音', 'models', qText('models', ''), 'number')}${field('其他直接费用', 'other', qText('other', ''), 'number')}</div>
              <button type="submit" class="outline-green full">更新测算</button>
            </form>
            <ul class="cost-lines">
              <li>直接成本<strong>${money(q.cost)}</strong></li>
              <li class="total">项目贡献<strong>${money(q.contribution)}</strong></li>
            </ul>
            <p class="small muted">未含获客、税费、折旧。</p>
          </section>
        </div>
      </div>
      <section class="panel panel-pad section-spacer">
        <h3>项目里程碑</h3>
        <div class="milestones">${milestones.map((m) => `<div>${esc(m[0])}<small>${esc(m[1])}</small></div>`).join('')}</div>
        <div class="footer-actions">${act('export-quote', '↓ 导出报价 JSON', 'outline-green')}</div>
      </section>`;
  }

  /* ================= 视图：执行现场 ================= */
  function paperBody(e) {
    const tab = S.contentTab;
    if (tab === '知识卡') {
      const facts = e.facts || [];
      if (!facts.length) return `<p class="small muted">这个展项还没有知识卡。</p>`;
      return `<ul class="fact-list">${facts.map((f) => {
        const bad = !f.verified;
        return `<li class="fact-item ${bad ? 'is-issue' : ''}"><div class="fact-meta">` +
          `<strong>${esc(f.id)}</strong><span class="mono">${esc(f.source_ref || '—')}</span>` +
          `${bad ? pill('待核验', 'red') : pill('引用已定位', 'green')}</div>` +
          `<p>${esc(f.text)}</p></li>`;
      }).join('')}</ul>`;
    }
    if (tab === '主讲解') return `<p class="script-body">${esc((e.main || {}).text || '')}</p>`;
    if (tab === '简化版') return `<p class="script-body">${esc((e.simplified || {}).text || '未生成')}</p>`;
    const rows = tab === '追问' ? (e.followups || []) : (e.fallback || []);
    if (!rows.length) return `<p class="small muted">这里还没有内容。</p>`;
    return `<ul class="qa-list">${rows.map((r) => `<li><q>${esc(r.q)}</q><span>${esc(r.a)}</span></li>`).join('')}</ul>`;
  }

  function liveSteps() {
    const g = gates();
    const drafts = exs().filter((x) => (x.main || {}).text).length;
    const located = exs().reduce((sum, x) => sum + (x.facts || []).filter((f) => f.verified).length, 0);
    const facts = exs().reduce((sum, x) => sum + (x.facts || []).length, 0);
    const steps = [
      ['资料接收', ((P().sources || []).length || 0) + ' 份 · ' + paraCount() + ' 段'],
      ['来源定位', located + '/' + facts + ' 条已定位'],
      ['知识卡', facts + ' 条'],
      ['讲解与问答', drafts + '/' + exs().length + ' 个展项'],
      ['自测', g.tested ? passedCount() + '/' + testsOf().length : '未运行'],
      ['审核', P().review ? (P().review.decision === 'approved' ? '已通过' : '要求修改') : '待审核'],
      ['语音', audioCount() + '/' + exs().length + ' 段'],
      ['发布', g.published ? '已发布' : '未发布']
    ];
    const done = [exs().length > 0, facts > 0 && located === facts, facts > 0, drafts === exs().length,
      g.allPassed, g.approved, g.audio, g.published];
    let current = done.findIndex((d) => !d);
    if (current < 0) current = done.length;
    return { steps, current };
  }

  function liveView() {
    const p = P();
    const { steps, current } = liveSteps();
    const e = cur();
    if (!e) {
      const hasSources = (p.sources || []).length > 0;
      const research = p.research || [];
      const plan = p.plan || [];
      const runBtn = `<div class="inline-actions section-spacer">${act('run', '▶ 生成草稿', 'primary', S.pendingRun ? 'disabled' : '')}</div>`;
      return header('执行现场', `${esc(p.id)} · v${p.version}`, pill('尚无草稿', 'amber')) +
        pipeline(steps, 0) +
        `<section class="panel panel-pad"><h3>还没有任何展项草稿</h3>` +
        (hasSources
          ? `<p class="small muted">${(p.sources || []).length} 份资料 · ${paraCount()} 个段落</p>` + runBtn
          : research.length
            ? `<p class="small muted">${research.length} 个网页 · ${plan.length ? plan.length + ' 个展项' : '未定展项'}</p>` + runBtn
            : `<p class="small muted">先给它依据：自己上网调研，或者导入原文资料。</p>` +
              `<div class="inline-actions section-spacer">${act('focus-chat', '↗ 让它先联网调研', 'primary')}${act('nav-content', '＋ 导入资料')}</div>`) +
        `</section>`;
    }
    const facts = e.facts || [];
    const firstFact = facts[0] || null;
    const a = audioOf(e.id);
    const issuesHere = (e.issues || []).length;
    const g = gates();
    return header('执行现场', `${esc(p.id)} · 运行第 ${p.run_version || 0} 轮 · ${esc(p.name)}`,
      pill(cur() ? `当前 ${cur().id}` : '', 'blue')) +
      pipeline(steps, current) +
      `<div class="grid cols-live">
        <section class="panel">
          <div class="panel-header">
            <div class="artifact-heading"><span class="eyebrow">内容成果 / 讲解文档</span>
              <h3><span>${esc(e.id)}</span>${esc(e.title)}</h3></div>
            ${act('read-content', '展开阅读', 'text-button')}${act('nav-content', '编辑内容 ↘', 'text-button')}
          </div>
          <div class="tab-line">${TABS.map((t) => `<button type="button" data-action="content-tab" data-value="${t}" class="${S.contentTab === t ? 'active' : ''}">${t}</button>`).join('')}</div>
          <div class="paper">
            <div class="paper-heading"><strong>▤ ${esc(S.contentTab)}</strong>${e.verified ? pill('引用已核验', 'green') : pill('待核验 ' + issuesHere + ' 处', 'amber')}</div>
            ${paperBody(e)}
            ${firstFact ? `<div class="citations">${act('locate-source', '▤ ' + esc(firstFact.id), 'citation', `data-ref="${esc(firstFact.source_ref || '')}"`)}</div>
              <div class="quote"><div class="quote-head"><span><span class="quote-mark">❝</span>原文引用</span>${act('locate-source', '定位原文', 'text-button', `data-ref="${esc(firstFact.source_ref || '')}"`)}</div>
              <p>“${esc(firstFact.quote || '（这条事实还没有登记原文引用）')}”</p></div>` : ''}
            <p class="subtle">主讲解 ${((e.main || {}).text || '').length} 字 · 目标 45 秒${a ? ' · 实测 ' + secOf(a.duration_s) : ' · 尚未合成音频'}</p>
          </div>
          ${exhibitTray()}
        </section>
        <aside class="panel event-inspector"><div class="panel-pad">
          <div class="panel-title">运行事件 <span class="micro-tag">真实记录</span></div>
          ${issuesHere ? note(`<strong>! 有 ${issuesHere} 处引用待处理</strong>`, 'red') : ''}
          ${issuesHere ? `<div class="notice-actions">${act('goto-issues', '查看待核验', 'primary')}</div>` : ''}
          <details class="event-history"><summary>查看运行记录 <span class="mono">${S.events.length} 条</span></summary>${eventsHtml(30)}</details>
          <h4>后续步骤</h4>
          <ul class="gate-list">
            <li>自测 ${g.allPassed ? stat(passedCount() + '/' + testsOf().length + ' 通过', 'pass') : (g.tested ? stat('有失败项', 'fail') : stat('未运行', 'warn'))}</li>
            <li>人工审核 ${g.approved ? stat('已通过', 'pass') : stat('未批准', 'warn')}</li>
            <li>音频 ${g.audio ? stat(audioCount() + '/' + exs().length + ' 段', 'pass') : stat('缺 ' + (exs().length - audioCount()) + ' 段', 'warn')}</li>
          </ul>
          <div class="stack-tight">
            ${act('run', '↻ 按当前资料重新生成', 'full', S.pendingRun ? 'disabled' : '')}
            ${act('nav-tests', '去自测 →', 'primary full')}
          </div>
        </div></aside>
      </div>`;
  }

  /* ================= 视图：内容成果 ================= */
  function researchBlock(research) {
    if (!research.length) return '';
    return `<div class="divider"></div>
      <h4>联网调研来源（${research.length} 个网页）</h4>
      ${research.map((r) => `<div class="section-spacer">
        <div class="metric-row"><strong>${esc(r.id)}</strong>${stat((r.quotes || []).length + ' 条摘录')}${r.url
          ? `<a href="${esc(r.url)}" target="_blank" rel="noreferrer noopener" class="small">原始页面 ↗</a>` : ''}</div>
        <p class="small muted">${esc(r.title || r.url || '')}${r.query ? ` · 搜索词「${esc(r.query)}」` : ''}</p>
        <ul class="para-list" id="paras-${esc(r.id)}">${(r.quotes || []).map((q) => `<li data-para="${esc(q.id)}">
          <div class="para-id">${esc(q.id)}</div><p>${esc(q.text)}</p></li>`).join('')}</ul>
      </div>`).join('')}`;
  }

  function contentView() {
    const p = P();
    const e = cur();
    const sources = p.sources || [];
    const research = p.research || [];
    if (!e) {
      const researchPanel = research.length ? `<section class="panel panel-pad">
          <h3>调研来源（${research.length} 个网页）</h3>
          ${research.map((r) => `<div class="section-spacer">
            <div class="metric-row"><strong>${esc(r.id)}</strong>${stat((r.quotes || []).length + ' 条摘录')}${r.url
              ? `<a href="${esc(r.url)}" target="_blank" rel="noreferrer noopener" class="small">原始页面 ↗</a>` : ''}</div>
            <p class="small muted">${esc(r.title || r.url || '')}</p>
            <ul class="para-list">${(r.quotes || []).map((q) => `<li data-para="${esc(q.id)}">
              <div class="para-id">${esc(q.id)}</div><p>${esc(q.text)}</p></li>`).join('')}</ul>
          </div>`).join('')}
        </section>` : '';
      if (!sources.length) {
        return header('内容成果', '引用都能回到原文', pill(research.length ? `${research.length} 个调研来源` : '还没有来源', research.length ? 'green' : 'amber')) +
          `<div class="grid cols-2">
            <section class="panel panel-pad">
              <h3>先给它依据</h3>
              ${research.length ? `<p class="small muted">${research.length} 个网页</p>` : ''}
              <div class="inline-actions section-spacer">
                ${research.length ? act('goto-live', '▶ 生成草稿', 'primary') : act('focus-chat', '↗ 让它先联网调研', 'primary')}
              </div>
              <div class="divider"></div>
              <label class="file-input">＋ 导入资料<input type="file" data-upload="material" accept=".txt,.md,.markdown,.csv,.tsv,.json,.html,.htm,.docx,.pdf" hidden></label>
              ${research.length ? `<div class="inline-actions section-spacer">${act('focus-chat', '↗ 再调研一个网页')}</div>` : ''}
              <div class="divider"></div>
              <h4>资料授权</h4>
              ${p.authorization ? `<div class="mini-code">${esc(p.authorization.confirmed_by)} · ${esc(dateTimeOf(p.authorization.at))}</div>`
                : `<form data-form="authorize"><div class="field-row">${field('确认人姓名', 'confirmed_by', '')}</div>
                  <button type="submit" class="outline-green">登记资料授权</button></form>`}
            </section>
            ${researchPanel || `<section class="panel panel-pad">
              <h3>还没有任何来源</h3>
              <p class="small muted">给一个就能起草。</p>
              <div class="choice-cards section-spacer">
                <button type="button" class="choice-card" data-action="focus-chat">
                  <strong>↗ 自己调研</strong><span>公开作品、知名展品</span>
                </button>
                <label class="choice-card">
                  <strong>＋ 导入原文</strong><span>客户自己送展、网上查不到</span>
                  <input type="file" data-upload="material" accept=".txt,.md,.markdown,.csv,.tsv,.json,.html,.htm,.docx,.pdf" hidden>
                </label>
              </div>
            </section>`}
          </div>`;
      }
      return header('内容成果', '资料已就位', pill('待生成', 'amber')) +
        `<section class="panel panel-pad"><h3>${sources.length} 份资料 · ${paraCount()} 个段落</h3>
          <div class="inline-actions section-spacer">${act('goto-live', '▶ 生成草稿', 'primary')}</div></section>` +
        researchPanel;
    }
    const refs = new Set(e.source_refs || []);
    const mine = sources.filter((s) => !refs.size || refs.has(s.id));
    const list = mine.length ? mine : sources;
    const rMine = research.filter((r) => !refs.size || refs.has(r.id)
      || (r.quotes || []).some((q) => refs.has(q.id)));
    const rList = rMine.length ? rMine : research;
    return header('每一句讲解，都能回到来源', `${esc(e.id)} · v${p.version}`) +
      `<section class="panel panel-pad" style="margin-bottom:16px">${exhibitTray()}</section>
      <div class="grid content-two">
        <section id="source-panel" class="panel panel-pad">
          <h3>来源（只读）：${esc(e.id)} 用到 ${[
            list.length ? `${list.length} 份资料` : '',
            rList.length ? `${rList.length} 个网页` : '',
          ].filter(Boolean).join(' + ') || '（暂无依据）'}</h3>
          ${list.map((s) => `<div class="section-spacer">
            <div class="metric-row"><strong>${esc(s.id)}</strong>${stat(byteText(s.bytes))}${stat((s.paragraphs || []).length + ' 段')}</div>
            <p class="small muted">${esc(s.name)}</p>
            <ul class="para-list" id="paras-${esc(s.id)}">${(s.paragraphs || []).map((x) => `<li data-para="${esc(x.id)}">
              <div class="para-id">${esc(x.id)}</div><p>${esc(x.text)}</p></li>`).join('')}</ul>
          </div>`).join('')}
          ${researchBlock(rList)}
          <div class="divider"></div>
          <h4>资料授权</h4>
          ${p.authorization ? `<div class="mini-code">${esc(p.authorization.confirmed_by)} · ${esc(dateTimeOf(p.authorization.at))}<br>${esc(p.authorization.scope || '')}</div>`
            : `<form data-form="authorize"><div class="field-row">${field('确认人姓名', 'confirmed_by', '')}</div>
              <button type="submit" class="outline-green">登记资料授权</button></form>`}
          <div class="divider"></div>
          <label class="file-input">＋ 导入资料<input type="file" data-upload="material" accept=".txt,.md,.markdown,.csv,.tsv,.json,.html,.htm,.docx,.pdf" hidden></label>
        </section>
        <section class="panel">
          <div class="panel-header"><h3>知识卡与脚本</h3>
            ${stat('v' + p.version)}${e.verified ? stat('引用已核验', 'pass') : stat('待核验', 'warn')}</div>
          <div class="tab-line">${TABS.map((t) => `<button type="button" class="${S.contentTab === t ? 'active' : ''}" data-action="content-tab" data-value="${t}">${t}</button>`).join('')}</div>
          <div class="panel-pad">
            <div class="paper-heading"><strong>${esc(e.id)} ${esc(e.title)}</strong><span class="mono">v${p.version} · ${((e.main || {}).text || '').length} 字</span></div>
            ${S.contentTab === '主讲解'
              ? `<form data-form="exhibit"><label class="field"><span>讲解内容（可编辑）</span>
                 <textarea id="script-editor" name="text" class="editor" maxlength="2000">${esc((e.main || {}).text || '')}</textarea></label>
                 <div class="inline-actions"><button type="submit" class="outline-green">保存为新版本</button>${act('nav-tests', '提交审核 →', 'primary')}</div></form>`
              : `<div>${paperBody(e)}</div>${act('jump-main', '去主讲解编辑 →', 'outline-green section-spacer')}`}
          </div>
        </section>
      </div>`;
  }

  /* ================= 视图：测试审核 ================= */
  function testsView() {
    const p = P();
    const g = gates();
    const rows = testsOf();
    const step = g.published ? 5 : g.approved ? 4 : g.allPassed ? 3 : g.tested ? 2 : 1;
    const blockReasons = [];
    if (!g.tested) blockReasons.push('还没有运行自测');
    if (g.tested && !g.allPassed) blockReasons.push(`自测有 ${testsOf().length - passedCount()} 项未通过`);
    if (!g.clean) blockReasons.push(`仍有 ${issues().length} 处引用待核验`);
    return header('测试与人工审核', `v${p.version} · ${p.id}`) +
      pipeline([['草稿', 'v' + p.version], ['自测', g.tested ? `${passedCount()}/${testsOf().length}` : '未运行'],
        ['引用', g.clean ? '全部定位' : issues().length + ' 处待核验'], ['人工批准', g.approved ? '已通过' : '待审核'],
        ['发布', g.published ? '已发布' : '未发布']], step) +
      `<div class="grid cols-2">
        <section class="panel panel-pad">
          <div class="paper-heading"><h3>自测结果</h3>
            ${act('run-tests', rows.length ? '↻ 重新自测' : '▶ 运行自测', 'outline-green')}</div>
          <div class="metric-row">${stat(`${rows.length} 条用例`)}${rows.length
            ? (g.allPassed ? stat(`${passedCount()} 通过`, 'pass') : stat(`${testsOf().length - passedCount()} 未通过`, 'fail'))
            : stat('未运行', 'warn')}</div>
          ${rows.length ? `<div class="table-wrap"><table><thead><tr><th>用例</th><th>结果</th><th class="wrap">说明</th></tr></thead><tbody>
            ${rows.map((t) => `<tr><td>${esc(t.name)}</td><td>${t.status === 'passed' ? stat('通过', 'pass') : stat('未通过', 'fail')}</td><td class="wrap">${esc(t.detail || '')}</td></tr>`).join('')}
          </tbody></table></div>` : `<p class="small muted">还没运行自测。</p>`}
        </section>
        <section class="panel panel-pad">
          <h3>人工审核</h3>
          <div class="metric-row">${stat('v' + p.version)}${stat('版本绑定', 'pass')}${g.approved ? stat('已批准', 'pass') : stat('未批准', 'warn')}</div>
          ${p.review ? `<div class="mini-code">${p.review.decision === 'approved' ? '通过' : '要求修改'} · ${esc(p.review.reviewer)}<br>${esc(dateTimeOf(p.review.at))} · 绑定 v${p.review.version}</div>` : ''}
          ${blockReasons.length ? note(`<strong>${esc(blockReasons.join('；'))}</strong>`, 'red') : ''}
          <form data-form="review" class="section-spacer">
            ${field('审核人', 'reviewer', (p.review && p.review.reviewer) || '')}
            <label class="field"><span>审核意见</span><textarea name="note" rows="3" maxlength="2000" placeholder="写下事实、语气或来源方面的修改意见…">${esc((p.review && p.review.note) || '')}</textarea></label>
            <div class="inline-actions">
              <button type="submit" class="outline-green" data-decision="needs_revision">保存退回意见</button>
              <button type="submit" class="primary" data-decision="approved" ${blockReasons.length ? 'disabled' : ''}>批准 v${p.version}</button>
            </div>
          </form>
        </section>
      </div>
      <section class="panel panel-pad section-spacer">
        <h3>待核验引用 <span class="micro-tag">${issues().length} 处</span></h3>
        ${issues().length ? `<ul class="fact-list">${issues().map((it) => `<li class="fact-item is-issue">
          <div class="fact-meta"><strong>${esc(it.id)}</strong><span class="mono">${esc(it.source_ref || '')}</span>${pill('无法逐字定位', 'red')}</div>
          <p>${esc(it.title || it.message || '')}</p>
          <div class="notice-actions">${act('fix-issue', '补充资料后重新核', 'primary', `data-value="${esc(it.id)}" data-choice="补充资料"`)}${act('fix-issue', '删除该事实', '', `data-value="${esc(it.id)}" data-choice="删除该事实"`)}</div>
        </li>`).join('')}</ul>` : `<p class="small muted">当前没有待核验引用。</p>`}
      </section>`;
  }

  /* ================= 视图：语音终端 ================= */
  function voiceView() {
    const p = P();
    const target = 45;
    const tol = 0.25;
    const low = (target * (1 - tol)).toFixed(2);
    const high = (target * (1 + tol)).toFixed(2);
    const rows = exs().map((e) => {
      const a = audioOf(e.id);
      const d = a && a.duration_s;
      const ok = d ? (d >= low && d <= high) : null;
      return { e, a, d, ok };
    });
    const step = rows.length && rows.every((r) => r.a) ? (rows.every((r) => r.ok) ? 3 : 2) : (rows.some((r) => r.a) ? 1 : 0);
    return header('语音制作与终端', `${esc(p.name)} · ${audioCount()}/${exs().length} 段已合成`) +
      pipeline([['内容就绪', exs().length ? '已就绪' : '无草稿'], ['Breeze 合成', audioCount() + '/' + exs().length],
        ['音频校验', rows.filter((r) => r.ok === true).length + '/' + rows.length], ['人工试听', '未记录']], step) +
      `<div class="grid cols-2">
        <div class="stack">
          <section class="panel panel-pad">
            <h3>合成与试听</h3>
            <div class="metric-row">${stat('引擎 breeze（BREEZE_MODEL_ID）')}${stat('指定引擎失败即报错，不静默降级', 'pass')}</div>
            <div class="table-wrap section-spacer"><table><thead><tr><th>展项</th><th>文本</th><th>音频</th><th>状态</th></tr></thead><tbody>
              ${rows.map((r) => `<tr><td><strong>${esc(r.e.id)}</strong><br><small>${esc(r.e.title)}</small></td>
                <td class="num">${((r.e.main || {}).text || '').length} 字</td>
                <td class="wrap">${r.a ? `${esc(r.a.filename)}<br><small>${byteText(r.a.bytes)} · ${r.a.format} · 实测 ${secOf(r.d)}</small>` : '—'}</td>
                <td>${r.a ? stat('已合成', 'pass') : stat('待合成', 'warn')}
                  <div class="section-spacer">${act('synth', r.a ? '重新合成' : '合成', 'outline-green', `data-value="${esc(r.e.id)}"`)}</div></td></tr>`).join('')}
            </tbody></table></div>
            ${rows.filter((r) => r.a).map((r) => `<div class="audio-line section-spacer"><strong>${esc(r.e.id)}</strong>
              <audio controls preload="metadata" src="${esc(withToken('/api/studio/projects/' + p.id + '/audio/' + encodeURIComponent(r.a.filename)))}"></audio></div>`).join('')}
          </section>
          <section class="panel panel-pad">
            <h3>实时双向语音 <span class="micro-tag">未接入</span></h3>
            <div class="voice-flow">${[['♩', '麦克风'], ['〰', 'VAD'], ['▤', 'ASR'], ['◇', '来源约束问答'], ['〰', 'TTS'], ['◖', '播放']].map((n) => `<div class="voice-node"><span class="circle">${n[0]}</span><strong>${n[1]}</strong><small>未实现</small></div>`).join('')}</div>
            <p class="small muted section-spacer">ASR、实时打断与设备端播报都还没有接。</p>
          </section>
        </div>
        <section class="panel panel-pad">
          <h3>时长门 <span class="micro-tag">ffprobe 实测</span></h3>
          <div class="metric-row">${stat(`窗口 ${low}~${high} 秒`)}${stat(`目标 ${target} 秒 ±${tol * 100}%`)}</div>
          <ul class="fact-list">${rows.map((r) => `<li class="fact-item ${r.ok === false ? 'is-issue' : ''}">
            <div class="fact-meta"><strong>${esc(r.e.id)}</strong><span class="mono">${r.a ? esc(r.a.engine || '') + ' · ' + (r.a.sample_rate || '—') + ' Hz' : '未合成'}</span>
              ${r.ok === null ? stat('无音频', 'warn') : r.ok ? stat('落在窗口内', 'pass') : stat('超出窗口', 'fail')}</div>
            <p>${r.d ? '实测 ' + secOf(r.d) + '（' + (r.a.bitrate_kbps || '—') + ' kbps）' : '还没有实测值'}</p></li>`).join('')}</ul>
          ${rows.some((r) => r.ok === false) ? note(`<strong>有 ${rows.filter((r) => r.ok === false).length} 段超出时长窗口</strong>改稿重合成，或在交付说明里写明实际时长。`, 'red') : ''}
        </section>
      </div>`;
  }

  /* ================= 视图：发布验收 ================= */
  function releaseView() {
    const p = P();
    const g = gates();
    const files = [];
    files.push({ name: '交付稿.md', note: '主讲解、简化版、知识卡与审核结论', ok: true });
    files.push({ name: '交付清单.json', note: '版本、测试通过数、每个文件的字节数与 sha256', ok: true });
    exs().forEach((e) => files.push({
      name: '音频/' + (audioOf(e.id) ? audioOf(e.id).filename : e.id + '-（未合成）'),
      note: audioOf(e.id) ? byteText(audioOf(e.id).bytes) + ' · 实测 ' + secOf(audioOf(e.id).duration_s) : '尚未合成',
      ok: !!audioOf(e.id)
    }));
    files.push({ name: '音频/README.md', note: '自动生成：引擎、音色、sha256 与已验证/未验证边界', ok: audioCount() > 0 });
    const reasons = [];
    if (!g.approved) reasons.push('人工审核未批准');
    if (!g.allPassed) reasons.push('自测未全部通过');
    if (!g.audio) reasons.push('音频未全部合成');
    if (!g.clean) reasons.push(`还有 ${issues().length} 处引用待核验`);
    const step = g.published ? (g.accepted ? 5 : 4) : (g.approved ? 3 : (g.allPassed ? 2 : 1));
    return header('发布与交付验收', `${esc(p.name)} · v${p.version} · ${esc(p.id)}`, pill(g.published ? '已发布' : '未发布', g.published ? 'green' : 'amber')) +
      pipeline([['内容批准', g.approved ? '已通过' : '未通过'], ['自测', g.allPassed ? '全通过' : '未全通过'],
        ['音频', audioCount() + '/' + exs().length], ['发布', g.published ? '已发布' : '未发布'],
        ['客户签收', g.accepted ? '已登记' : '未登记']], step) +
      `<div class="grid cols-3">
        <section class="panel panel-pad">
          <h3>交付包文件结构</h3>
          <div class="file-tree"><h4>⌄ ${esc(p.name)}_v${p.version}</h4>
            ${files.map((f) => `<details${f.ok ? '' : ' open'}><summary>▤ ${esc(f.name)} ${f.ok ? stat('真实生成', 'pass') : stat('缺', 'fail')}</summary><p>${esc(f.note)}</p></details>`).join('')}
          </div>
          <div class="section-spacer">${act('download-zip', '↓ 下载交付包（含 MP3）', 'primary full')}</div>
          <div class="section-spacer">${act('download-md', '↓ 只下载交付稿 .md', 'outline-green full')}</div>
        </section>
        <section class="panel panel-pad">
          <h3>发布门禁检查</h3>
          <ul class="gate-list">
            <li>资料授权 ${g.authorized ? stat('已登记', 'pass') : stat('未登记', 'warn')}</li>
            <li>人工审核 ${g.approved ? stat('已批准', 'pass') : stat('未批准', 'fail')}</li>
            <li>自测 ${g.allPassed ? stat(passedCount() + '/' + testsOf().length, 'pass') : stat(g.tested ? '有未通过' : '未运行', 'fail')}</li>
            <li>引用 ${g.clean ? stat('全部定位', 'pass') : stat(issues().length + ' 处待核验', 'fail')}</li>
            <li>音频 ${g.audio ? stat(audioCount() + '/' + exs().length, 'pass') : stat('缺 ' + (exs().length - audioCount()) + ' 段', 'fail')}</li>
          </ul>
          ${reasons.length ? note(`<strong>${esc(reasons.join('；'))}</strong>`, 'red') : ''}
          <div class="section-spacer">${g.published ? act('download-zip', '↓ 已发布版本交付包', 'primary full') : act('publish', '⌑ 发布 v' + p.version, 'primary full', reasons.length ? 'disabled' : '')}</div>
          ${p.review ? `<h4>审核记录</h4><div class="mini-code">${p.review.decision === 'approved' ? '通过' : '要求修改'} · ${esc(p.review.reviewer)} · v${p.review.version}<br>${esc(dateTimeOf(p.review.at))}<br>${esc(p.review.note || '（无意见）')}</div>` : ''}
        </section>
        <section class="panel panel-pad">
          <h3>客户验收</h3>
          <dl class="detail-list">
            <div><dt>客户</dt><dd>${esc((p.quote && p.quote.customer) || '未填写')}</dd></div>
            <div><dt>交付范围</dt><dd>${esc((p.quote && p.quote.scope) || '未填写')}</dd></div>
            <div><dt>报价</dt><dd>${money(p.quote && p.quote.price)} ${p.quote && p.quote.confirmed ? stat('已确认', 'pass') : stat('未确认', 'warn')}</dd></div>
            <div><dt>发布状态</dt><dd>${g.published ? stat('已发布', 'pass') : stat('未发布', 'warn')}</dd></div>
            <div><dt>签收记录</dt><dd>${p.acceptance ? `${p.acceptance.decision === 'accepted' ? '已签收' : '拒收'} · ${esc(p.acceptance.signer)} · v${p.acceptance.version}` : '未登记'}</dd></div>
          </dl>
          ${g.published
            ? `<form data-form="acceptance" class="section-spacer">${field('签收人', 'signer', (p.acceptance && p.acceptance.signer) || '')}
               <label class="field"><span>结论</span><select name="decision"><option value="accepted">接受</option><option value="rejected">拒收</option></select></label>
               ${field('备注', 'note', (p.acceptance && p.acceptance.note) || '')}
               <button type="submit" class="outline-green full">登记签收</button></form>`
            : `<button type="button" class="outline-green full section-spacer" disabled>登记签收（未发布）</button>`}
        </section>
      </div>`;
  }

  /* ================= 视图：反馈改进 ================= */
  function feedbackView() {
    const p = P();
    const list = p.feedbacks || [];
    const chosen = list.find((f) => f.id === S.feedbackId) || list[0] || null;
    const g = gates();
    return header('反馈与改进', `${list.length} 条反馈 · v${p.version}`) +
      pipeline([['运行', `${S.events.length} 条事件`], ['发现问题', list.length + ' 条反馈'],
        ['形成候选', list.filter((f) => f.state === 'candidate').length + ' 条'],
        ['回归', g.tested ? `${passedCount()}/${testsOf().length}` : '未运行'],
        ['发布', g.published ? '已发布' : '未发布']], list.length ? 2 : 1) +
      `<div class="grid cols-3">
        <section class="panel panel-pad">
          <div class="paper-heading"><h3>反馈列表（${list.length}）</h3>${pill('真实台账', 'green')}</div>
          ${list.length ? list.map((f) => `<button type="button" class="feedback-item ${chosen && chosen.id === f.id ? 'active' : ''}" data-action="feedback-select" data-value="${esc(f.id)}">
            <strong>${esc(f.id)}</strong><span>${esc(f.title)}</span><small>${esc(f.state === 'candidate' ? '候选' : f.state === 'closed' ? '已关闭' : '已记录')} · ${esc(timeOf(f.recorded_at))}</small></button>`).join('')
            : `<div class="empty-action"><p class="small muted">还没有反馈。</p></div>`}
          <div class="divider"></div>
          <form data-form="feedback"><h4>记录一条反馈</h4>
            <label class="field"><span>展项</span><select name="exhibit_id">${exs().map((e) => `<option value="${esc(e.id)}">${esc(e.id)} ${esc(e.title)}</option>`).join('')}</select></label>
            ${field('标题', 'title', '')}
            ${field('观众问题', 'question', '')}
            <label class="field"><span>现象描述（至少 4 字）</span><textarea name="problem" rows="3" maxlength="2000" placeholder="观众说讲得太快跟不上…"></textarea></label>
            <button type="submit" class="outline-green full">记录反馈</button>
          </form>
        </section>
        <section class="panel panel-pad">
          <h3>候选详情</h3>
          ${chosen ? `<div class="metric-row">${stat(chosen.exhibit_id || '未指定展项')}${stat(chosen.state)}${stat(timeOf(chosen.recorded_at))}</div>
            <dl class="detail-list">
              <div><dt>观众问题</dt><dd>${esc(chosen.question || '—')}</dd></div>
              <div><dt>现象描述</dt><dd>${esc(chosen.problem)}</dd></div>
              <div><dt>原说法</dt><dd>${esc(chosen.old || '—')}</dd></div>
              <div><dt>改成什么</dt><dd>${esc(chosen.suggestion || '尚未写')}</dd></div>
            </dl>
            <form data-form="candidate"><input type="hidden" name="feedback_id" value="${esc(chosen.id)}">
              <label class="field"><span>候选说法（至少 4 字）</span><textarea name="suggestion" rows="3" maxlength="1000">${esc(chosen.suggestion || '')}</textarea></label>
              <button type="submit" class="outline-green full">登记改进候选</button></form>`
            : `<p class="small muted">选中左侧任意一条反馈查看详情。</p>`}
        </section>
        <section class="panel panel-pad">
          <h3>回归测试台</h3>
          <div class="device-check"><span>当前用例</span><strong>${testsOf().length} 条</strong></div>
          <div class="device-check"><span>通过</span><strong>${passedCount()} 条</strong></div>
          <div class="device-check"><span>最近结果</span>${g.allPassed ? stat('全通过', 'pass') : g.tested ? stat('有未通过', 'fail') : stat('未运行', 'warn')}</div>
          <div class="section-spacer">${act('run-tests', '▶ 执行回归自测', 'primary full')}</div>
        </section>
      </div>
      <section class="panel panel-pad section-spacer">
        <h3>运行证据 <span class="micro-tag">只填实测值</span></h3>
        <div class="metrics-strip">
          <div class="metric"><small>事件</small><strong>${S.events.length}</strong><em>服务端记录</em></div>
          <div class="metric"><small>自测通过</small><strong>${passedCount()}/${testsOf().length || 0}</strong><em>最近一次</em></div>
          <div class="metric"><small>音频</small><strong>${audioCount()}/${exs().length}</strong><em>Breeze 合成</em></div>
          <div class="metric"><small>反馈</small><strong>${list.length}</strong><em>台账条数</em></div>
          <div class="metric"><small>调用费用</small><strong>—</strong><em>未采集</em></div>
        </div>
        <div class="inline-actions">${act('events', '查看事件记录 ↗', 'text-button')}</div>
      </section>`;
  }

  /* ================= 聊天区 ================= */
  function openingText() {
    const p = P();
    if (!p) return '正在读取项目…';
    const sm = statusMeta();
    return `${p.name} v${p.version}，状态${sm[0]}。${exs().length} 个展项、${(p.sources || []).length} 份资料、` +
      `自测 ${testsOf().length ? passedCount() + '/' + testsOf().length + ' 通过' : '未运行'}、音频 ${audioCount()}/${exs().length}。` +
      `${issues().length ? '另有 ' + issues().length + ' 处引用待核验。' : ''}`;
  }

  // 模型回话会带 **粗体**、换行和裸链接。这里做最小渲染：先转义，再放开这三样。
  function fmtText(text) {
    let out = esc(text);
    out = out.replace(/\*\*([^*\n]{1,120})\*\*/g, '<strong>$1</strong>');
    out = out.replace(/(https?:\/\/[^\s<）)】"'，。；]+)/g,
      '<a href="$1" target="_blank" rel="noreferrer noopener">$1</a>');
    return out.replace(/\n{3,}/g, '\n\n').replace(/\n/g, '<br>');
  }

  function toolChips(tools) {
    if (!tools || !tools.length) return '';
    const items = tools.map((t) => {
      const label = t.ok === false ? '没成功' : '已完成';
      return `<span class="tool-chip${t.ok === false ? ' is-fail' : ''}" title="${esc(t.summary || '')}">${esc(t.tool)} · ${esc(label)}</span>`;
    }).join('');
    return `<div class="tool-chips">${items}</div>`;
  }

  function pendingBubble() {
    if (!S.chatPending) return '';
    const items = S.chatTools.map((t) => `<span class="tool-chip${t.state === 'fail' ? ' is-fail' : ''}">${esc(t.message || t.tool)}</span>`);
    const tail = items.length ? items.join('') : '<span class="tool-chip">在读现场数据…</span>';
    return `<div class="message agent pending">
      <span class="mini-avatar"><span class="orbit"></span></span>
      <div class="message-body"><p>正在处理…</p><div class="tool-chips">${tail}</div>
      <span class="message-time">${timeOf(new Date().toISOString())}</span></div></div>`;
  }

  function renderChat() {
    const p = P();
    const log = $('#chat-log');
    if (!p) { log.innerHTML = ''; return; }
    const history = (p.chat || []).map((m) => ({ role: m.role, text: m.text, time: timeOf(m.at), tools: m.tools }));
    const all = [{ role: 'agent', text: openingText(), time: timeOf(p.updated_at), opening: true }].concat(history);
    const attachments = `<div class="reference-files">${(p.sources || []).slice(0, 3).map((s, i) => `
      <button type="button" data-action="locate-source" data-value="${esc((s.paragraphs || [])[0] ? (s.paragraphs || [])[0].id : '')}">
        <span class="file-glyph">▤</span><span><strong>${esc(s.name)}</strong><small>${(s.paragraphs || []).length} 段 · 查看原文</small></span></button>`).join('')}</div>
      <p class="reference-auth">✓ ${p.authorization ? '资料授权已登记：' + esc(p.authorization.confirmed_by) : '资料授权尚未登记'}</p>`;
    const results = `<div class="chat-result">
      <button type="button" class="chat-result-row" data-action="nav-content"><span class="result-icon">▤</span>
        <span><strong>来源整理</strong><small>${(p.sources || []).length} 份资料 · ${paraCount()} 个段落</small></span>
        <span class="result-check">✓</span><span class="chevron">›</span></button>
      <button type="button" class="chat-result-row" data-action="nav-content"><span class="result-icon">▥</span>
        <span><strong>知识卡</strong><small>${exs().reduce((n, e) => n + (e.facts || []).length, 0)} 条 · ${issues().length} 处待核验</small></span>
        <span class="chevron">›</span></button></div>`;
    log.innerHTML = all.map((m, i) => `<div class="message ${m.role}">
      <span class="mini-avatar">${m.role === 'user' ? esc(avatarText()) : '<span class="orbit"></span>'}</span>
      <div class="message-body"><p class="${m.role === 'agent' ? 'rich' : ''}">${fmtText(m.text)}</p>${toolChips(m.tools)}${m.actions && m.actions.length
        ? `<div class="message-actions">${m.actions.map((a) => act(a[0], a[1], a[2] || '')).join('')}</div>` : ''}
        <span class="message-time">${m.time}</span></div></div>${i === 0 && !S.chatPending ? attachments : i === 1 ? results : ''}`).join('') + pendingBubble();
    log.scrollTop = log.scrollHeight;
  }

  function avatarText() {
    const name = ($('#user-name') || {}).textContent || '本';
    return name.trim().slice(0, 1) || '本';
  }

  /* ================= 顶栏与外壳 ================= */
  function renderChrome() {
    const p = P();
    const chip = $('#conn-chip');
    const text = $('#conn-text');
    const noteEl = $('#session-note');
    const dot = $('#session-dot');
    const state = $('#employee-state');
    if (S.connError) {
      chip.className = 'demo-label is-down';
      text.textContent = '服务连接失败';
      noteEl.textContent = S.connError;
      dot.className = 'status-dot red';
      state.innerHTML = '<i></i>连不上后端';
    } else if (S.health) {
      const tts = S.health.tts || {};
      const engines = ['breeze', 'edge-tts', 'sapi'].filter((k) => tts[k]);
      chip.className = 'demo-label is-live';
      text.textContent = '已连接 · ' + S.health.model;
      noteEl.textContent = `data ${S.health.database} · 语音 ${engines.join('/') || '不可用'} · ${S.health.auth_required ? '口令已启用' : '仅本机免口令'}`;
      dot.className = 'status-dot green';
      const running = p && p.status === 'running';
      state.innerHTML = `<i></i>${S.chatPending ? '正在调用模型' : running ? '正在生成草稿' : '等待你的指令'}`;
    } else {
      chip.className = 'demo-label is-wait';
      text.textContent = '正在连接…';
    }
    $('#project-switch').innerHTML = `${esc(p ? p.name : (S.listLoaded ? '还没有项目' : '读取中'))} <span>⌄</span>`;
    $('#context-chips').innerHTML = p
      ? `<span>${exs().length} 个展项</span><span>${esc(p.language || '中文')}</span><span>${esc(p.audience || '')}</span><span>${S.projects.length} 个项目</span>`
      : `<span>${S.listLoaded ? '无项目' : '正在读取'}</span>`;
    $('#user-name').textContent = (p && p.quote && p.quote.reviewer) || '本机操作者';
    $('#user-avatar').textContent = ((p && p.quote && p.quote.reviewer) || '本机操作者').trim().slice(0, 1) || '本';
  }

  const VIEW_FN = {
    project: projectView, live: liveView, content: contentView,
    tests: testsView, voice: voiceView, release: releaseView, feedback: feedbackView
  };

  function render() {
    const route = location.hash.slice(1);
    S.view = VIEWS.some((v) => v[0] === route) ? route : 'live';
    $('#workspace-tabs').innerHTML = VIEWS.map((v) => `<a href="#${v[0]}" class="${S.view === v[0] ? 'active' : ''}" ${S.view === v[0] ? 'aria-current="page"' : ''}>${v[1]}</a>`).join('');
    const body = $('#workspace-body');
    body.dataset.view = S.view;
    renderChrome();
    renderChat();
    if (!P()) {
      if (S.connError) {
        body.innerHTML = `<section class="panel panel-pad"><h3>连不上 studio_server</h3>` +
          note(`<strong>${esc(S.connError)}</strong>服务没起来时页面读不到任何项目数据。<div class="banner-actions">` +
            `<button type="button" data-action="retry">重试连接</button></div>`, 'red') + `</section>`;
      } else if (S.listLoaded) {
        body.innerHTML = `<section class="panel panel-pad">
          <div class="page-header"><div><h2>新建第一个项目</h2>
          <p>工作台不预置任何示例内容。填一个真实项目名，创建后到「内容成果」页导入你们的展签或教育材料文本。</p></div>
          <div class="header-meta">${pill('空数据库', 'amber')}</div></div>
          <form data-form="new-project">
            ${field('项目名称', 'name', '', 'text', 'maxlength="60" required placeholder="例如：光与声音探索展"')}
            <div class="field-row">${field('目标观众', 'audience', '', 'text', 'maxlength="40" placeholder="例如：小学三年级以上亲子观众"')}
            ${field('语言', 'language', '中文', 'text', 'maxlength="20"')}</div>
            <label class="field"><span>讲解目标（可留空）</span><textarea name="brief" rows="3" maxlength="2000" placeholder="例如：把每个展项改写成约 45 秒的现场讲解，先给草稿我审。"></textarea></label>
            <div class="inline-actions section-spacer"><button class="primary" type="submit">创建项目</button></div>
          </form></section>`;
      } else {
        body.innerHTML = `<section class="panel panel-pad"><h3>正在读取项目列表</h3>` +
          note('正在从本机服务读取项目列表…') + `</section>`;
      }
      return;
    }
    saveUi();
    body.innerHTML = VIEW_FN[S.view]();
    restoreUi();
    document.title = VIEWS.find((v) => v[0] === S.view)[1] + ' · 展项内容工作台';
  }

  /* ================= 会话内 UI 记忆 ================= */
  const ui = { drafts: new Map(), details: new Map(), scroll: new Map(), focused: false };

  function saveUi() {
    const body = $('#workspace-body');
    if (!body || !body.dataset.view) return;
    ui.scroll.set(body.dataset.view, body.scrollTop || window.scrollY || 0);
    const open = new Set();
    body.querySelectorAll('details').forEach((d, i) => { if (d.open) open.add(d.dataset.key || String(i)); });
    ui.details.set(body.dataset.view, open);
    body.querySelectorAll('input,textarea,select').forEach((el) => {
      if (!el.name || el.type === 'file') return;
      const key = body.dataset.view + ':' + el.name;
      if (el.type === 'checkbox' || el.type === 'radio') ui.drafts.set(key, el.checked);
      else ui.drafts.set(key, el.value);
    });
  }

  function restoreUi() {
    const body = $('#workspace-body');
    if (!body) return;
    const open = ui.details.get(S.view);
    body.querySelectorAll('details').forEach((d, i) => { if (open && open.has(String(i))) d.open = true; });
    body.querySelectorAll('input,textarea,select').forEach((el) => {
      if (!el.name || el.type === 'file') return;
      const key = S.view + ':' + el.name;
      if (!ui.drafts.has(key)) return;
      const v = ui.drafts.get(key);
      if (el.type === 'checkbox' || el.type === 'radio') el.checked = !!v;
      else if (v !== null && v !== undefined) el.value = v;
    });
    const top = ui.scroll.get(S.view);
    if (top) body.scrollTop = top;
  }

  function setFocused(value) {
    ui.focused = value;
    document.body.classList.toggle('focus-work', value);
    const button = document.querySelector('[data-action="focus-work"]');
    if (button) {
      button.setAttribute('aria-pressed', value ? 'true' : 'false');
      button.textContent = value ? '显示对话' : '专注工作区';
    }
  }

  /* ================= 提示与弹窗 ================= */
  let toastTimer = null;
  function toast(text, kind) {
    const el = $('#toast');
    el.textContent = text;
    el.className = 'toast show' + (kind === 'error' ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = 'toast'; }, kind === 'error' ? 5200 : 3200);
  }

  function dialog(title, html, reading) {
    const d = $('#dialog');
    $('#dialog-title').textContent = title;
    $('#dialog-body').innerHTML = html;
    d.className = reading ? 'reading-dialog' : '';
    if (!d.open) d.showModal();
  }
  function closeDialog() { const d = $('#dialog'); if (d.open) d.close(); }

  function fail(error) {
    if (error && error.unauthorized) { askToken(); return; }
    if (error && error.offline) { S.connError = error.message; render(); }
    toast(error.message || String(error), 'error');
  }

  /* ================= 数据刷新 ================= */
  async function reloadProject() {
    if (!S.project) return;
    try {
      const data = await api.get('/api/studio/projects/' + S.project.id);
      S.project = data.project;
      try { localStorage.setItem(PROJECT_KEY, S.project.id); } catch (e) {}
      render();
    } catch (error) { fail(error); }
  }

  async function reloadEvents(reset) {
    if (!S.project) return;
    try {
      const data = await api.quiet('/api/studio/projects/' + S.project.id + '/events?after=' + (reset ? 0 : S.lastEventId));
      const list = data.events || [];
      if (reset) { S.events = list; } else if (list.length) { S.events = S.events.concat(list); }
      S.lastEventId = S.events.reduce((max, e) => Math.max(max, Number(e.id) || 0), S.lastEventId);
      // 对话的现场进度：工具在干什么、回话到没到。
      const toolEvents = list.filter((e) => e.kind === 'chat.tool');
      if (toolEvents.length) {
        S.chatTools = S.chatTools.concat(toolEvents.map((e) => ({
          tool: (e.detail || {}).tool || '工具',
          message: (e.detail || {}).message || '',
          state: (e.detail || {}).state || 'done'
        })));
        if (S.chatPending) renderChat();
      }
      const answered = list.some((e) => e.kind === 'chat.agent' || e.kind === 'chat.failed');
      if (answered && S.chatPending) {
        S.chatPending = false;
        S.chatTools = [];
        await reloadProject();
        return;
      }
      const finished = list.some((e) => e.kind === 'run.finished' || e.kind === 'run.failed');
      if (finished && S.pendingRun) { S.pendingRun = false; await reloadProject(); return; }
      if (S.project.status === 'running' && list.length) { await reloadProject(); }
    } catch (error) { /* 静默：轮询失败不该打断操作 */ }
  }

  let pollTimer = null;
  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!S.project || document.hidden) return;
      const fast = S.chatPending || S.pendingRun || S.project.status === 'running';
      const before = S.events.length;
      if (fast || S.view === 'live' || S.view === 'release') await reloadEvents(false);
      if (!fast && S.events.length !== before) render();
      if (S.pendingRun || S.project.status === 'running') renderChrome();
    }, 1200);
  }

  /* ================= 动作 ================= */
  async function postAction(action, body) {
    if (!S.project) throw new Error('还没有选中项目');
    const data = await api.post('/api/studio/projects/' + S.project.id + '/' + action, body || {});
    if (data.project) S.project = data.project;
    await reloadEvents(false);
    render();
    return data;
  }

  // 上传原始字节：服务端按扩展名解析（txt/md/csv/json/html/docx/pdf），不走 multipart。
  async function uploadMaterial(file) {
    if (!S.project) throw new Error('先建一个项目，再导入资料');
    if (!file || !file.size) throw new Error('文件是空的（0 字节）');
    const url = withToken('/api/studio/projects/' + S.project.id + '/upload?name=' + encodeURIComponent(file.name));
    let res;
    try {
      res = await fetch(url, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/octet-stream' }),
        body: file
      });
    } catch (error) {
      const err = new Error('连不上本机 studio_server（' + error.message + '）');
      err.offline = true;
      throw err;
    }
    const raw = await res.text();
    let data = null;
    if (raw) { try { data = JSON.parse(raw); } catch (e) { data = { error: raw.slice(0, 300) }; } }
    if (res.status === 401) { const err = new Error('需要访问口令'); err.unauthorized = true; throw err; }
    if (!res.ok) throw new Error((data && data.error) || ('服务返回 HTTP ' + res.status));
    if (data && data.project) S.project = data.project;
    await reloadProject();
    await reloadEvents(false);
    return data || {};
  }

  async function uploadMany(files) {
    const list = Array.from(files || []);
    if (!list.length || !S.project) return;
    for (const file of list) {
      try {
        const data = await uploadMaterial(file);
        const doc = data.doc || {};
        toast(`已收下《${file.name}》${doc.chars ? '（' + doc.chars + ' 字）' : ''}${doc.note ? ' ' + doc.note : ''}`);
      } catch (error) { fail(error); }
    }
  }

  async function doRun() {
    if (S.pendingRun) return;
    const count = (P().materials || []).length || exs().length;
    if (!window.confirm(`生成草稿会为 ${count} 个展项各调用一次模型（共约 ${count} 次真实调用），并覆盖当前草稿。继续？`)) return;
    S.pendingRun = true;
    render();
    try {
      await api.post('/api/studio/projects/' + S.project.id + '/run', {});
      toast('已开始生成，事件流会实时刷新');
      await reloadProject();
      await reloadEvents(false);
    } catch (error) { S.pendingRun = false; fail(error); render(); }
  }

  async function doTests() {
    try {
      const data = await postAction('tests');
      const rows = (data.project && data.project.tests) || [];
      const passed = rows.filter((t) => t.status === 'passed').length;
      toast(`自测完成：${passed}/${rows.length} 通过`);
    } catch (error) { fail(error); }
  }

  async function doSynth(exhibitId) {
    const exhibit = exs().find((e) => e.id === exhibitId);
    if (!exhibit) { toast('展项不存在', 'error'); return; }
    const text = ((exhibit.main || {}).text || '').trim();
    if (!text) { toast('这个展项还没有主讲解，先改好文本再合成', 'error'); return; }
    toast('正在调用 Breeze 合成，通常 15~30 秒…');
    try {
      const data = await postAction('voice', { exhibit_id: exhibitId, text });
      const info = data.audio || {};
      toast(`已合成 ${exhibitId}：${info.engine || 'breeze'} · ${byteText(info.bytes)} · 实测 ${secOf(info.duration_s)}`);
    } catch (error) { fail(error); }
  }

  async function doPublish() {
    try {
      await postAction('publish');
      toast('已发布当前版本');
    } catch (error) { fail(error); }
  }

  function downloadJson(name, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function exportQuote() {
    const p = P();
    downloadJson(`${p.name}_报价_v${p.version}.json`, {
      project_id: p.id, project: p.name, version: p.version,
      exported_at: new Date().toISOString(), quote: p.quote || null,
      note: '成本与贡献为服务端计算结果；不含合同与收款。'
    });
  }

  function openReader() {
    const e = cur();
    if (!e) return;
    const text = (e.main || {}).text || '';
    const facts = e.facts || [];
    dialog(`${e.id} ${e.title} · 主讲解`,
      `<div class="reader-toolbar"><span>${text.length} 字 · v${P().version}</span>
        <div>${act('reader-smaller', 'A−', '')}${act('reader-larger', 'A+', '')}${act('close-dialog', '关闭', 'text-button')}</div></div>
       <article class="reader-document"><p>${esc(text)}</p>
       <section><h3>原文引用（${facts.length} 条）</h3>${facts.map((f) => `<p>${esc(f.id)} · ${esc(f.source_ref || '')}<br>${esc(f.quote || '（未登记引用）')}</p>`).join('') || '<p>没有登记引用。</p>'}</section></article>`,
      true);
    $('#dialog-body').style.setProperty('--reader-size', S.readerSize + 'px');
  }

  function showEvents() {
    dialog('运行事件记录', `<p class="small muted">按时间倒序，共 ${S.events.length} 条；来自服务端 events 表。</p>${eventsHtml(120)}`);
  }

  function showProjectPicker() {
    const rows = S.projects.map((p) => `<tr data-action="pick-project" data-value="${esc(p.id)}" tabindex="0">
      <td><strong>${esc(p.name)}</strong><br><small class="hint-mono">${esc(p.id)}</small></td>
      <td>${pill(...(STATUS[p.status] || [p.status, '']))}</td><td class="num">v${p.version}</td>
      <td class="num">${esc(dateTimeOf(p.updated_at))}</td>
      <td class="num">${p.id === (P() && P().id) ? '<span class="small muted">当前</span>' : act('pick-project', '打开', 'text-button', `data-value="${esc(p.id)}"`)}</td>
      </tr>`).join('');
    dialog('项目', (S.projects.length
      ? `<div class="table-wrap"><table><thead><tr><th>项目</th><th>状态</th><th>版本</th><th>更新时间</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<p class="small muted">还没有任何项目。</p>`) +
      `<div class="inline-actions section-spacer">${act('new-project', '＋ 新建项目', 'outline-green')}` +
      (P() ? act('delete-project', '删除当前项目', 'text-button') : '') + `</div>`);
  }

  function showNewProject() {
    dialog('新建项目', `<form data-form="new-project">
      ${field('项目名称', 'name', '', 'text', 'maxlength="60" required placeholder="例如：光与声音探索展"')}
      <div class="field-row">${field('目标观众', 'audience', '', 'text', 'maxlength="40" placeholder="例如：小学三年级以上亲子观众"')}
      ${field('语言', 'language', '中文', 'text', 'maxlength="20"')}</div>
      <label class="field"><span>讲解目标（可留空）</span><textarea name="brief" rows="3" maxlength="2000" placeholder="例如：把每个展项改写成约 45 秒的现场讲解，先给草稿我审。"></textarea></label>
      <div class="inline-actions section-spacer"><button class="primary" type="submit">创建项目</button>${act('close-dialog', '取消', '')}</div>
      </form>`);
  }

  function confirmDeleteProject() {
    const p = P();
    if (!p) { toast('没有当前项目', 'error'); return; }
    dialog('删除项目', `<article class="reader-document"><p>要删掉 <strong>${esc(p.name)}</strong>（${esc(p.id)}）吗？</p>
      <section><h3>这个操作会删掉</h3><p>项目档案、${(p.chat || []).length} 条对话、${S.events.length} 条事件记录、${exs().length} 个展项草稿、${Object.keys(p.audio || {}).length} 个已合成音频文件。删完无法从这里恢复。</p></section></article>
      <div class="inline-actions section-spacer">${act('delete-project-yes', '确认删除', 'danger')}${act('close-dialog', '取消', '')}</div>`);
  }

  function showHelp() {
    dialog('怎么用', `<article class="reader-document">
      <ol class="gate-list">
        <li><strong>给它依据</strong>在对话框里说「先调研一下某个作品，然后起草」，或者点「＋」导入客户给的原文。</li>
        <li><strong>起草</strong>执行现场点「▶ 生成草稿」，展项、知识卡、主讲解、问答一次生成。</li>
        <li><strong>核验与审核</strong>引用定位不到的会进「待核验」；测试审核页跑自测、填审核人批准。</li>
        <li><strong>出音频</strong>语音终端逐段合成，时长由 ffprobe 实测。</li>
        <li><strong>交付</strong>发布验收页下载交付包。</li>
      </ol></article>`);
  }

  function showSettings() {
    const h = S.health || {};
    const tts = h.tts || {};
    dialog('工作区设置', `<dl class="detail-list">
      <div><dt>服务地址</dt><dd class="hint-mono">${esc(location.origin)}</dd></div>
      <div><dt>代码版本</dt><dd class="hint-mono">${esc(h.code || '—')}</dd></div>
      <div><dt>进程</dt><dd class="hint-mono">pid ${esc(h.pid || '—')}</dd></div>
      <div><dt>数据库</dt><dd class="hint-mono">${esc(h.database || '—')}</dd></div>
      <div><dt>模型</dt><dd class="hint-mono">${esc(h.model || '—')}${h.key_configured ? '（密钥已配置）' : '（无密钥）'}</dd></div>
      <div><dt>语音引擎</dt><dd class="hint-mono">breeze=${tts.breeze} edge-tts=${tts.edge_tts} sapi=${tts.sapi} ffmpeg=${tts.ffmpeg} ffprobe=${tts.ffprobe}</dd></div>
      <div><dt>Breeze 音色</dt><dd class="hint-mono">${esc(tts.breeze_voice || '—')} · ${esc(tts.breeze_model || '—')}</dd></div>
      <div><dt>访问口令</dt><dd>${h.auth_required ? pill('已启用', 'green') : pill('未启用（仅本机监听）', 'amber')}</dd></div>
    </dl>
    <div class="inline-actions section-spacer">${act('set-token', '设置访问口令', 'outline-green')}${act('retry', '重新连接', '')}<a class="text-button" href="/classic">打开旧版工作台 ↗</a></div>`);
  }

  function go(view) {
    if (location.hash.slice(1) === view) render();
    else location.hash = view;
  }

  function locateSource(ref) {    if (!ref) { toast('这条事实没有登记来源引用', 'error'); return; }
    const paraId = String(ref).split('·')[0].trim();
    const exact = String(ref).trim();
    S.view = 'content';
    if (location.hash !== '#content') location.hash = 'content'; else render();
    setTimeout(() => {
      const body = $('#workspace-body');
      const hit = body.querySelector(`[data-para="${exact}"]`) || body.querySelector(`[data-para^="${paraId}"]`);
      if (!hit) { toast('在资料面板里没找到 ' + ref + '，可能资料已更换', 'error'); return; }
      body.querySelectorAll('.para-list li.hit').forEach((li) => li.classList.remove('hit'));
      hit.classList.add('hit');
      hit.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 60);
  }

  /* ================= 事件绑定 ================= */
  const CLICK = {
    project: () => showProjectPicker(),
    'pick-project': async (value) => {
      closeDialog();
      try {
        const data = await api.get('/api/studio/projects/' + value);
        S.project = data.project; S.exhibitIndex = 0; S.feedbackId = null;
        try { localStorage.setItem(PROJECT_KEY, value); } catch (e) {}
        await reloadEvents(true);
        render();
        toast('已切换到 ' + S.project.name);
      } catch (error) { fail(error); }
    },
    'new-project': () => showNewProject(),
    'delete-project': () => confirmDeleteProject(),
    'delete-project-yes': async () => {
      const p = P();
      if (!p) { closeDialog(); return; }
      closeDialog();
      try {
        const data = await api.post('/api/studio/projects/' + p.id + '/delete', {});
        S.project = null;
        S.exhibitsIndex = 0;
        S.lastEventId = 0;
        S.events = [];
        try { localStorage.removeItem(PROJECT_KEY); } catch (e) {}
        await bootProjects();
        if (S.project) await reloadEvents(true);
        render();
        toast(`已删除「${data.name || p.name}」${data.audio_files_removed ? '，同时删除 ' + data.audio_files_removed + ' 个音频文件' : ''}`);
      } catch (error) { fail(error); }
    },
    help: () => showHelp(),
    settings: () => showSettings(),
    'set-token': () => askToken(),
    'close-dialog': () => closeDialog(),
    events: () => showEvents(),
    retry: async () => { S.connError = null; await boot(); },
    'focus-work': () => setFocused(!ui.focused),
    'expand-all': () => $('#workspace-body').querySelectorAll('details').forEach((d) => { d.open = true; }),
    'collapse-all': () => $('#workspace-body').querySelectorAll('details').forEach((d) => { d.open = false; }),
    mobile: (value, el) => {
      document.body.classList.toggle('show-chat', value === 'chat');
      document.body.classList.toggle('show-work', value !== 'chat');
      document.querySelectorAll('[data-action="mobile"]').forEach((b) => b.classList.toggle('active', b === el));
    },
    exhibit: (value) => {
      const next = Number(value);
      if (Number.isInteger(next) && next >= 0) { S.exhibitIndex = next; render(); }
    },
    'content-tab': (value) => { S.contentTab = value || '主讲解'; render(); },
    'nav-content': () => go('content'),
    'focus-chat': () => {
      const box = document.querySelector('#message');
      if (box) { box.focus(); box.scrollIntoView({ block: 'center' }); }
      else { toast('在右侧对话框里说：先调研一下这个作品，然后起草'); }
    },
    'nav-tests': () => go('tests'),
    'goto-live': () => go('live'),
    'goto-issues': () => go('tests'),
    'read-content': () => openReader(),
    'reader-smaller': () => { S.readerSize = Math.max(14, S.readerSize - 2); $('#dialog-body').style.setProperty('--reader-size', S.readerSize + 'px'); },
    'reader-larger': () => { S.readerSize = Math.min(30, S.readerSize + 2); $('#dialog-body').style.setProperty('--reader-size', S.readerSize + 'px'); },
    'locate-source': (value, el) => locateSource(el.dataset.ref || value),
    'jump-main': () => { S.contentTab = '主讲解'; render(); },
    run: () => doRun(),
    'run-tests': () => doTests(),
    'retry-tests': () => doTests(),
    reject: async () => {
      const reviewer = (P().review && P().review.reviewer) || '';
      try { await postAction('review', { decision: 'needs_revision', reviewer, note: '退回修订', version: P().version }); toast('已记录退回意见'); }
      catch (error) { fail(error); }
    },
    publish: () => doPublish(),
    synth: (value) => doSynth(value),
    'export-quote': () => exportQuote(),
    'download-zip': () => { location.href = withToken('/api/studio/projects/' + P().id + '/export.zip'); },
    'download-md': () => { location.href = withToken('/api/studio/projects/' + P().id + '/export'); },
    'feedback-select': (value) => { S.feedbackId = value; render(); },
    'fix-issue': async (value, el) => {
      try {
        await postAction('issue', { issue_id: value, choice: el.dataset.choice });
        toast('已处理：' + el.dataset.choice);
      } catch (error) { fail(error); }
    }
  };

  document.addEventListener('click', async (ev) => {
    const el = ev.target.closest('[data-action]');
    if (!el || el.tagName === 'A') return;
    const handler = CLICK[el.dataset.action];
    if (!handler) return;
    ev.preventDefault();
    try { await handler(el.dataset.value, el); } catch (error) { fail(error); }
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || !ev.target.matches('[data-action][tabindex]')) return;
    ev.preventDefault();
    ev.target.click();
  });

  const SUBMIT = {
    quote: async (form, mode) => {
      const body = readForm(form);
      body.confirm = mode === 'confirm';
      await postAction('quote', body);
      toast(mode === 'confirm' ? '范围已确认' : '已保存范围与报价');
    },
    money: async (form) => {
      await postAction('quote', readForm(form));
      toast('测算已更新');
    },
    authorize: async (form) => {
      await postAction('authorize', readForm(form));
      toast('资料授权已登记');
    },
    exhibit: async (form) => {
      const body = readForm(form);
      body.exhibit_id = cur().id;
      const before = P().version;
      await postAction('exhibit', body);
      S.contentTab = '主讲解';
      render();
      toast(`已保存 v${P().version}（原 v${before}）：自测与审核已失效，需要重跑`);
    },
    review: async (form, mode, submitter) => {
      const body = readForm(form);
      body.decision = (submitter && submitter.dataset.decision) || 'needs_revision';
      body.version = P().version;
      await postAction('review', body);
      toast(body.decision === 'approved' ? `已批准 v${P().version}` : '已保存退回意见');
    },
    acceptance: async (form) => {
      await postAction('acceptance', readForm(form));
      toast('签收已登记');
    },
    feedback: async (form) => {
      const body = readForm(form);
      body.op = 'add';
      const data = await postAction('feedback', body);
      if (data.feedback) S.feedbackId = data.feedback.id;
      render();
      toast('已记录反馈 ' + ((data.feedback && data.feedback.id) || ''));
    },
    candidate: async (form) => {
      const body = readForm(form);
      body.op = 'candidate';
      await postAction('feedback', body);
      toast('已登记改进候选');
    },
    'new-project': async (form) => {
      const body = readForm(form);
      if (!body.name) { toast('项目名称不能为空', 'error'); return; }
      const data = await api.post('/api/studio/projects', body);
      closeDialog();
      try { localStorage.setItem(PROJECT_KEY, data.project.id); } catch (e) {}
      S.project = data.project;
      await bootProjects();
      await reloadEvents(true);
      render();
      toast('已创建「' + data.project.name + '」，下一步导入资料');
    }
  };

  function readForm(form) {
    const out = {};
    new FormData(form).forEach((value, key) => {
      out[key] = typeof value === 'string' ? value.trim() : value;
    });
    return out;
  }

  document.addEventListener('submit', async (ev) => {
    const form = ev.target.closest('form[data-form]');
    if (!form) return;
    ev.preventDefault();
    const name = form.dataset.form;
    const handler = SUBMIT[name];
    if (!handler) return;
    const submitter = ev.submitter;
    const mode = (submitter && submitter.dataset.mode) || '';
    try { await handler(form, mode, submitter); } catch (error) { fail(error); }
  });

  document.addEventListener('submit', (ev) => {
    const form = ev.target.closest('#chat-form');
    if (form) ev.preventDefault();
  });

  document.addEventListener('change', async (ev) => {
    const el = ev.target;
    if (el.id === 'chat-width') {
      document.documentElement.style.setProperty('--chat-width', el.value + '%');
      try { localStorage.setItem(CHATW_KEY, el.value); } catch (e) {}
      return;
    }
    if (el.matches('[data-upload="material"]') && el.files && el.files[0]) {
      const file = el.files[0];
      el.value = '';
      try {
        const data = await uploadMaterial(file);
        const doc = data.doc || {};
        const bits = [doc.kind ? doc.kind : '', doc.chars ? doc.chars + ' 字' : ''].filter(Boolean).join(' · ');
        toast(`已收下《${file.name}》${bits ? '（' + bits + '）' : ''}${doc.note ? ' ' + doc.note : ''}`);
      } catch (error) { fail(error); }
      return;
    }
  });

  $('#chat-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const input = $('#message');
    const message = (input.value || '').trim();
    if (!message) return;
    if (!P()) { toast('还没有读到项目', 'error'); return; }
    if (S.chatPending) { toast('我还在回上一句，稍等一下', 'error'); return; }
    input.value = '';
    S.chatPending = true;
    S.chatTools = [];
    renderChat();
    renderChrome();
    try {
      await api.post('/api/studio/projects/' + S.project.id + '/chat', { message });
      // 服务端立刻返回 202，回话与工具进度由轮询的 chat.tool / chat.agent 事件补上。
      await reloadProject();
    } catch (error) {
      S.chatPending = false;
      S.chatTools = [];
      renderChat();
      fail(error);
    }
  });

  // 拖文件到对话区就是上传资料——不用先找按钮。
  let dragDepth = 0;
  const dropZone = () => $('.composer-wrap') || document.body;
  document.addEventListener('dragenter', (ev) => {
    if (!ev.dataTransfer || !Array.from(ev.dataTransfer.types || []).includes('Files')) return;
    dragDepth += 1;
    const z = dropZone();
    if (z) z.classList.add('is-drop');
  });
  document.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) { const z = dropZone(); if (z) z.classList.remove('is-drop'); }
  });
  document.addEventListener('dragover', (ev) => {
    if (ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes('Files')) ev.preventDefault();
  });
  document.addEventListener('drop', async (ev) => {
    const files = ev.dataTransfer && ev.dataTransfer.files;
    if (!files || !files.length) return;
    ev.preventDefault();
    dragDepth = 0;
    const z = dropZone();
    if (z) z.classList.remove('is-drop');
    await uploadMany(files);
  });

  $('#message').addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.shiftKey) return;
    if (ev.key === 'Enter') { ev.preventDefault(); $('#chat-form').requestSubmit(); }
  });

  $('#dialog').addEventListener('cancel', () => { /* Esc 关闭：交给浏览器默认关闭 */ });
  window.addEventListener('hashchange', () => render());

  /* ================= 启动 ================= */
  async function bootProjects() {
    const list = await api.get('/api/studio/projects');
    S.projects = list.projects || [];
    S.listLoaded = true;
    if (!S.projects.length) {
      // 空库就是空库：不自动建任何项目，交给使用者自己新建。
      S.project = null;
      return;
    }
    let want = '';
    try { want = localStorage.getItem(PROJECT_KEY) || ''; } catch (e) { want = ''; }
    if (!want || !S.projects.some((p) => p.id === want)) want = S.projects[0].id;
    const data = await api.get('/api/studio/projects/' + want);
    S.project = data.project;
    try { localStorage.setItem(PROJECT_KEY, want); } catch (e) {}
  }

  async function boot() {
    S.connError = null;
    try {
      S.health = await api.get('/api/studio/health');
    } catch (error) {
      if (error.unauthorized) { askToken(); return; }
      S.connError = error.message;
      render();
      return;
    }
    try {
      await bootProjects();
      S.exhibitIndex = 0;
      S.feedbackId = null;
      await reloadEvents(true);
      render();
      startPolling();
    } catch (error) {
      if (error.unauthorized) { askToken(); return; }
      S.connError = error.message;
      render();
    }
  }

  let savedWidth = '';
  try { savedWidth = localStorage.getItem(CHATW_KEY) || ''; } catch (e) { savedWidth = ''; }
  if (savedWidth) {
    document.documentElement.style.setProperty('--chat-width', savedWidth + '%');
    const sel = $('#chat-width');
    if (sel) sel.value = savedWidth;
  }

  boot();
})();
