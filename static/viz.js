/* =========================================================
   viz.js — 真实数据驱动的可视化层
   所有数字均来自 /api/runs/{id} 的当前 run 状态，不进行二次计算。
   ========================================================= */
(function () {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const $ = (sel, root = document) => root.querySelector(sel);

  // ---------- 1. 数字滚动 (rAF count-up，从当前值增量滚到新值) ----------
  // 每个元素记住上次展示值，重复调用时从旧值平滑过渡，而不是每次从 0 重来。
  const counterState = new WeakMap();

  function formatValue(v, decimals) {
    return decimals > 0 ? Number(v).toFixed(decimals) : Math.round(v).toLocaleString('zh-CN');
  }

  function countUp(el, target, opts = {}) {
    const duration = opts.duration ?? 800;
    const decimals = opts.decimals ?? 0;
    const suffix = opts.suffix ?? '';
    const targetNum = Number(target);
    if (!Number.isFinite(targetNum)) { el.textContent = String(target ?? ''); return; }

    const prev = counterState.get(el);
    const from = (prev && Number.isFinite(prev.target)) ? prev.target : 0;
    counterState.set(el, { target: targetNum, raf: prev?.raf });

    // 值没变就不重播动画，避免无谓抖动
    if (from === targetNum) {
      el.textContent = formatValue(targetNum, decimals) + suffix;
      return;
    }
    if (prev?.raf) cancelAnimationFrame(prev.raf);

    const start = performance.now();
    const fmt = (v) => formatValue(v, decimals) + suffix;
    el.textContent = fmt(from);
    function frame(now) {
      const t = Math.min(1, (now - start) / duration);
      const e = 1 - Math.pow(1 - t, 3); // easeOutCubic
      const v = from + (targetNum - from) * e;
      el.textContent = fmt(v);
      if (t < 1) {
        const st = counterState.get(el);
        if (st) st.raf = requestAnimationFrame(frame);
      } else {
        el.textContent = fmt(targetNum);
        const st = counterState.get(el);
        if (st) st.raf = null;
      }
    }
    const st = counterState.get(el);
    if (st) st.raf = requestAnimationFrame(frame);
  }

  // 对容器里所有 [data-count] 元素执行增量 count-up
  function mountCounters(root = document) {
    root.querySelectorAll('[data-count]').forEach((el) => {
      const raw = el.dataset.count;
      const value = Number(raw);
      if (!Number.isFinite(value)) { el.textContent = raw; return; }
      const decimals = Number(el.dataset.decimals || 0);
      const suffix = el.dataset.suffix || '';
      countUp(el, value, { decimals, suffix });
    });
  }

  // ---------- 2. 环形图 (severity donut) ----------
  // data: {P0: n, P1: n, P2: n, total: n}
  function donut(data) {
    const R = 58, C = 2 * Math.PI * R;
    const total = data.total || 0;
    const parts = [
      { key: 'P0', n: data.P0 || 0, cls: 'p0' },
      { key: 'P1', n: data.P1 || 0, cls: 'p1' },
      { key: 'P2', n: data.P2 || 0, cls: 'p2' },
    ].filter((p) => p.n > 0);
    let offset = 0;
    const segs = parts.map((p) => {
      const len = total ? (p.n / total) * C : 0;
      const dash = `${len} ${C - len}`;
      const dashoffset = `${-offset}`;
      offset += len;
      return `<circle class="seg ${p.cls}" cx="75" cy="75" r="${R}"
        stroke-dasharray="0 ${C}" data-final="${dash}" data-offset="${dashoffset}"></circle>`;
    }).join('');
    const legend = [
      { key: 'P0', n: data.P0 || 0, cls: '#ff5f56' },
      { key: 'P1', n: data.P1 || 0, cls: '#ffb020' },
      { key: 'P2', n: data.P2 || 0, cls: '#4dd0e1' },
    ].map((p) => `
      <div class="viz-legend-row">
        <i style="background:${p.cls}"></i>
        <span class="lbl">${p.key}</span>
        <span class="num" data-count="${p.n}">${p.n}</span>
      </div>`).join('');
    return `
      <div class="viz-donut-wrap">
        <div class="viz-donut">
          <svg viewBox="0 0 150 150" aria-hidden="true">
            <circle class="track" cx="75" cy="75" r="${R}"></circle>
            ${segs}
          </svg>
          <div class="center">
            <div>
              <b data-count="${total}">${total}</b>
              <span>FINDINGS</span>
            </div>
          </div>
        </div>
        <div class="viz-legend">${legend}</div>
      </div>`;
  }

  // 在节点挂载后触发动画（延迟到下一帧，保证浏览器完成布局）
  function playDonut(root) {
    const circles = root.querySelectorAll('.viz-donut .seg');
    requestAnimationFrame(() => {
      circles.forEach((c, i) => {
        setTimeout(() => {
          // 用 inline style 覆盖 CSS 的 .seg{stroke-dasharray:0 999}
          c.style.strokeDasharray = c.dataset.final;
          c.style.strokeDashoffset = c.dataset.offset;
        }, 120 + i * 160);
      });
    });
  }

  // ---------- 3. 横向条形图 ----------
  // items: [{label, value, cls?}]
  function bars(items, opts = {}) {
    const max = Math.max(1, ...items.map((i) => i.value));
    const rows = items.map((it) => `
      <div class="viz-bar-row">
        <div class="viz-bar-track">
          <div class="viz-bar-fill ${it.cls || ''}" data-final-pct="${((it.value / max) * 100).toFixed(2)}"></div>
          <span class="viz-bar-label">${escapeHtml(it.label)}</span>
        </div>
        <div class="viz-bar-val" data-count="${it.value}">${it.value}</div>
      </div>`).join('');
    return `<div class="viz-bars">${rows}</div>`;
  }

  function playBars(root) {
    const fills = root.querySelectorAll('.viz-bar-fill[data-final-pct]');
    requestAnimationFrame(() => {
      fills.forEach((f, i) => {
        setTimeout(() => { f.style.width = f.dataset.finalPct + '%'; }, 80 + i * 90);
      });
    });
  }

  // ---------- 检查项中文名 ----------
  const CHECK_NAMES = {
    geometry_outlier: '几何异常',
    near_duplicate_image: '近重复图像',
    duplicate_image: '重复图像',
    duplicate_box: '重复标注框',
    overlap_conflict: '框重叠冲突',
    label_density_outlier: '标注密度异常',
    class_id_out_of_range: '类别编号越界',
    coord_out_of_range: '坐标越界',
    box_zero_area: '零面积框',
    label_missing: '漏标注',
    label_malformed: '标注格式错误',
    empty_label: '空标注文件',
    missing_class_table: '缺少类别表',
    image_unreadable: '图像不可读',
    dataset_note: '数据集说明',
    findings_truncated: '结果已截断',
    label_coverage_missing: '缺少覆盖度数据',
    spec_class_missing: '规范缺类别',
  };
  function checkName(key) { return CHECK_NAMES[key] || key; }

  // 增量更新横向条形图：条数一致时复用 DOM，只更新标签/宽度/数值（平滑过渡）。
  function updateBars(container, items) {
    if (!container) return;
    const rows = [...container.querySelectorAll(':scope > .viz-bar-row')];
    if (rows.length !== items.length) return false; // 交由调用方整体重建
    const max = Math.max(1, ...items.map((i) => i.value));
    items.forEach((it, i) => {
      const row = rows[i];
      const fill = row.querySelector('.viz-bar-fill');
      const label = row.querySelector('.viz-bar-label');
      const val = row.querySelector('.viz-bar-val');
      const targetPct = ((it.value / max) * 100).toFixed(2) + '%';
      if (fill) {
        fill.dataset.finalPct = targetPct.replace('%', '');
        fill.style.width = targetPct;
        const cls = 'viz-bar-fill' + (it.cls ? ' ' + it.cls : '');
        if (fill.className !== cls) fill.className = cls;
      }
      if (label && label.textContent !== it.label) label.textContent = it.label;
      if (val) {
        val.dataset.count = String(it.value);
        countUp(val, it.value, {});
      }
    });
    return true;
  }

  // 增量更新类别实例分布：结构稳定，按行复用。
  function updateClassBars(container, items) {
    if (!container) return false;
    const rows = [...container.querySelectorAll(':scope > .viz-class-row')];
    if (rows.length !== items.length) return false;
    const max = Math.max(1, ...items.map((i) => i.count));
    const palette = ['#c6f36a', '#6ee7f9', '#ffb020', '#ff5f56', '#a78bfa', '#34d399'];
    items.forEach((it, i) => {
      const row = rows[i];
      const fill = row.querySelector('.viz-bar-fill');
      const val = row.querySelector('.count');
      if (fill) {
        const targetPct = ((it.count / max) * 100).toFixed(2) + '%';
        fill.style.width = targetPct;
      }
      if (val) {
        val.dataset.count = String(it.count);
        countUp(val, it.count, {});
      }
    });
    return true;
  }

  // ---------- 4. 半环覆盖仪表 ----------
  function gauge(score, max = 100) {
    const pct = Math.max(0, Math.min(1, (Number(score) || 0) / max));
    // 半圆弧：半径 80，中心 (100, 100)，起点 (20,100)，终点 (180,100)
    // 弧长 = π * r = 251.33
    const LEN = Math.PI * 80;
    const dash = (pct * LEN).toFixed(2);
    return `
      <div class="viz-gauge">
        <svg viewBox="0 0 200 110" aria-hidden="true">
          <defs>
            <linearGradient id="gaugeGrad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stop-color="#4dd0e1"/>
              <stop offset="100%" stop-color="#c6f36a"/>
            </linearGradient>
          </defs>
          <path class="gauge-track" d="M 20 100 A 80 80 0 0 1 180 100"></path>
          <path class="gauge-fill" d="M 20 100 A 80 80 0 0 1 180 100"
            stroke-dasharray="0 ${LEN}" data-final="${dash} ${LEN}"></path>
        </svg>
        <div class="gauge-center">
          <b data-count="${score}" data-decimals="1" data-suffix="">${Number(score || 0).toFixed(1)}</b>
          <span>COVERAGE&nbsp;/&nbsp;${max}</span>
        </div>
      </div>`;
  }

  function playGauge(root) {
    const path = root.querySelector('.viz-gauge .gauge-fill');
    if (!path) return;
    requestAnimationFrame(() => {
      setTimeout(() => { path.style.strokeDasharray = path.dataset.final; }, 200);
    });
  }

  // ---------- 5. 流水线 pipeline ----------
  // steps: [{title, status, detail, duration}]
  function pipeline(steps) {
    if (!steps || !steps.length) return '<div class="empty-note">等待开始…</div>';
    const rows = steps.map((s, i) => {
      const status = s.status || '';
      const meta = stepMeta(s);
      return `
        <li class="viz-pipe-step ${escapeHtml(status)}" style="animation-delay:${i * 60}ms">
          <span class="viz-pipe-dot"></span>
          <span class="viz-pipe-name">${escapeHtml(s.title || '')}</span>
          <span class="viz-pipe-meta">${escapeHtml(meta)}</span>
        </li>`;
    }).join('');
    return `<ol class="viz-pipeline-ol">${rows}</ol>`;
  }

  function stepMeta(step) {
    const d = step.detail || {};
    const time = step.duration != null ? `${Number(step.duration).toFixed(1)}s` : '…';
    if (d.images !== undefined) return `${d.images} 图 · ${d.objects || 0} 实例 · ${time}`;
    if (d.total !== undefined) return `${d.total} 条 · ${time}`;
    if (d.canonical_classes !== undefined) return `${d.canonical_classes} 类 · ${d.conflicts || 0} 冲突 · ${time}`;
    if (d.score !== undefined) return `覆盖 ${d.score}% · ${time}`;
    if (d.items !== undefined) return `${d.items} 项 · ${time}`;
    if (d.changed_files !== undefined) return `${d.changed_files} 文件 · ${time}`;
    if (d.artifacts !== undefined) return `${d.artifacts} 个交付物 · ${time}`;
    if (d.calls !== undefined) return `${d.calls} 次 · ${time}`;
    if (d.method) return `${d.method} · ${(d.classes || []).length} 类 · ${time}`;
    if (d.provided) return `${d.provided.length} 项 · ${time}`;
    return time;
  }

  // ---------- 6. 打字机 ----------
  function typeIn(el, text, opts = {}) {
    const speed = opts.speed ?? 14;
    el.textContent = '';
    let i = 0;
    const caret = document.createElement('span');
    caret.className = 'viz-caret';
    el.appendChild(caret);
    function tick() {
      if (i < text.length) {
        caret.insertAdjacentText('beforebegin', text[i]);
        i++;
        setTimeout(tick, speed);
      } else {
        setTimeout(() => caret.remove(), 600);
      }
    }
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.textContent = text;
    } else {
      tick();
    }
  }

  // ---------- 7. KPI 卡片 ----------
  // items: [{label, value, unit, cls?, decimals?}]
  function kpis(items) {
    return items.map((it, i) => `
      <div class="kpi ${it.cls || ''}" style="animation-delay:${i * 60}ms">
        <b data-count="${it.value ?? ''}" data-decimals="${it.decimals || 0}">${it.value ?? '—'}</b>
        <span>${escapeHtml(it.label)} · ${escapeHtml(it.unit || '')}</span>
      </div>`).join('');
  }

  // 增量更新 KPI：复用现有 DOM，只把数字从旧值平滑滚到新值，不整块重建。
  // 首次（容器为空）时构建结构；之后仅更新数值与状态类，动画记忆得以保留。
  function updateKpis(container, items) {
    if (!container) return;
    const existing = container.querySelectorAll(':scope > .kpi');
    if (existing.length !== items.length) {
      container.innerHTML = kpis(items);
      mountCounters(container);
      return;
    }
    items.forEach((it, i) => {
      const card = existing[i];
      const cls = it.cls || '';
      if (card.className !== `kpi ${cls}`.trim()) card.className = `kpi ${cls}`.trim();
      const numEl = card.querySelector('b');
      if (numEl) {
        numEl.dataset.count = String(it.value ?? '');
        numEl.dataset.decimals = String(it.decimals || 0);
      }
      const spanEl = card.querySelector('span');
      const label = `${it.label} · ${it.unit || ''}`;
      if (spanEl && spanEl.textContent !== label) spanEl.textContent = label;
    });
    mountCounters(container);
  }

  // ---------- 8. 类别分布 ----------
  function classBars(items) {
    const max = Math.max(1, ...items.map((i) => i.count));
    const palette = ['#c6f36a', '#6ee7f9', '#ffb020', '#ff5f56', '#a78bfa', '#34d399'];
    return items.map((it, i) => `
      <div class="viz-class-row">
        <div class="name" title="${escapeHtml(it.name)}">${escapeHtml(it.name)}</div>
        <div class="viz-bar-track">
          <div class="viz-bar-fill" style="background:linear-gradient(90deg,${palette[i % palette.length]}44,${palette[i % palette.length]});"
            data-final-pct="${((it.count / max) * 100).toFixed(2)}"></div>
        </div>
        <div class="count" data-count="${it.count}">${it.count}</div>
      </div>`).join('');
  }

  // ---------- 9. 加载界面 ----------
  function loaderHTML(progress = 0, title = '正在准备质检', step = '等待开始…', steps = null) {
    const C = 2 * Math.PI * 56;
    const dash = ((Math.max(0, Math.min(1, progress))) * C).toFixed(2);
    return `
      <div class="viz-loader">
        <div class="viz-loader-inner">
          <div class="viz-loader-ring">
            <svg viewBox="0 0 130 130" aria-hidden="true">
              <defs>
                <linearGradient id="loaderGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#4dd0e1"/>
                  <stop offset="100%" stop-color="#c6f36a"/>
                </linearGradient>
              </defs>
              <circle class="ring-track" cx="65" cy="65" r="56"></circle>
              <circle class="ring-prog" cx="65" cy="65" r="56"
                stroke-dasharray="${dash} ${C}" data-circ="${C.toFixed(4)}"></circle>
            </svg>
            <div class="ring-center"><span data-count="${Math.round(progress * 100)}" data-suffix="%">0%</span></div>
          </div>
          <div class="viz-loader-title">${escapeHtml(title)}</div>
          <div class="viz-loader-step" id="vizLoaderStep">${escapeHtml(step)}</div>
          ${steps ? `<div class="viz-loader-pipe viz-pipeline">${steps}</div>` : ''}
        </div>
      </div>`;
  }

  function updateLoader(root, progress, step) {
    const circle = root.querySelector('.viz-loader-ring .ring-prog');
    const center = root.querySelector('.viz-loader-ring .ring-center span');
    const stepEl = root.querySelector('#vizLoaderStep');
    if (circle) {
      const C = parseFloat(circle.getAttribute('data-circ')) || 0;
      const dash = (Math.max(0, Math.min(1, progress)) * C).toFixed(2);
      circle.setAttribute('stroke-dasharray', `${dash} ${C}`);
    }
    if (center && progress != null) center.textContent = Math.round(progress * 100) + '%';
    if (stepEl && step != null) stepEl.textContent = step;
  }

  // ---------- 实时计时 ticker ----------
  // 运行中步骤的 duration 恒为 0（后端只在结束时回填），这里用本地时钟
  // 对 status=running 的步骤实时计算 now-started，让秒数真正跳动。
  let tickerHandle = null;
  function startTicker(renderFn, intervalMs = 200) {
    stopTicker();
    const tick = () => { renderFn(); tickerHandle = setTimeout(tick, intervalMs); };
    tickerHandle = setTimeout(tick, intervalMs);
  }
  function stopTicker() {
    if (tickerHandle) { clearTimeout(tickerHandle); tickerHandle = null; }
  }
  // 运行中步骤的实时已耗时（秒）
  // 后端心跳方案：app.js 在每次 poll 时用相邻快照增量累加得到 _baseElapsed，
  // 并记下锚点时刻 _baseAt（performance.now()）。这里在两次 poll 之间用本地时钟
  // 平滑插值，让秒数连续跳动；完成步骤直接用后端真实 duration。
  function liveElapsed(step) {
    if (!step) return null;
    if (step._baseElapsed != null && step._baseAt != null && typeof performance !== 'undefined') {
      const drift = Math.max(0, (performance.now() - step._baseAt) / 1000);
      return Math.max(0, step._baseElapsed + drift);
    }
    if (step._startedAt != null && typeof performance !== 'undefined') {
      return Math.max(0, (performance.now() - step._startedAt) / 1000);
    }
    if (typeof step.duration === 'number' && step.duration > 0) return step.duration;
    if (step.started) return Math.max(0, Date.now() / 1000 - step.started);
    return null;
  }
  // 格式化秒数为可读时长
  function fmtElapsed(sec) {
    if (sec == null) return '…';
    if (sec < 60) return `${sec.toFixed(1)}s`;
    const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
    return `${m}m${String(s).padStart(2, '0')}s`;
  }

  // ---------- 10. 骨架屏 ----------
  function skeletonRows(n = 5) {
    let rows = '';
    for (let i = 0; i < n; i++) {
      rows += `
        <div class="viz-skel-row">
          <div class="viz-skel-thumb"></div>
          <div class="viz-skel-block"></div>
          <div class="viz-skel-block" style="width:${70 - i * 5}%"></div>
          <div class="viz-skel-block"></div>
          <div class="viz-skel-block"></div>
        </div>`;
    }
    return `<div class="viz-skeleton">${rows}</div>`;
  }

  function skeletonTiles(n = 3) {
    let t = '';
    for (let i = 0; i < n; i++) {
      t += `<div class="viz-skel-row" style="grid-template-columns:1fr;gap:6px">
        <div class="viz-skel-block" style="height:32px;width:60%"></div>
        <div class="viz-skel-block" style="height:14px;width:90%"></div>
        <div class="viz-skel-block" style="height:14px;width:40%"></div>
      </div>`;
    }
    return `<div class="viz-skeleton">${t}</div>`;
  }

  // ---------- helpers ----------
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function mount(root = document) {
    mountCounters(root);
    playDonut(root);
    playBars(root);
    playGauge(root);
  }

  window.Viz = {
    countUp, mountCounters, donut, playDonut,
    bars, playBars, gauge, playGauge,
    pipeline, stepMeta, typeIn, kpis, updateKpis,
    classBars, updateClassBars, updateBars,
    checkName, CHECK_NAMES,
    loaderHTML, updateLoader, skeletonRows, skeletonTiles,
    startTicker, stopTicker, liveElapsed, fmtElapsed,
    mount, escapeHtml,
  };
})();
