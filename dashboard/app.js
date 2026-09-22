/**
 * EvalsBench Dashboard Client Application
 * Supports zero-CORS file:// local loading, interactive size-class filtering,
 * pinned model baseline comparisons, dynamic KV cache calculations, and Radar visualization.
 *
 * Wave 7a additions are isolated to the helper block at the bottom of this
 * file (``EDS_TRIAXIS_HELPERS``). The renderTable / setupEventListeners
 * surface below remains the canonical academic-benchmark pipeline; EDS
 * extensions only attach extras to existing rows and never mutate the
 * legacy academic column structure.
 */

let leaderboardData = null;
let currentFilter = 'all';
let currentSubcat = 'overall';
let pinnedModelId = '';
let radarChartInstance = null;

// Initial Load
document.addEventListener('DOMContentLoaded', async () => {
  await loadData();
  setupEventListeners();
  initKVCalculator();
  initRadarChart();
  if (typeof EDS_TRIAXIS_HELPERS !== 'undefined') {
    EDS_TRIAXIS_HELPERS.init();
  }
});

async function loadData() {
  if (window.LEADERBOARD_DATA && window.LEADERBOARD_DATA.models) {
    leaderboardData = window.LEADERBOARD_DATA;
    populatePinSelector();
    renderTable();
    updateKVCalculator();
    updateRadarChart();
    return;
  }
  try {
    const res = await fetch('data/leaderboard.json');
    leaderboardData = await res.json();
    populatePinSelector();
    renderTable();
    updateKVCalculator();
    updateRadarChart();
  } catch (err) {
    console.error('Failed to load leaderboard data:', err);
  }
}

function setupEventListeners() {
  // Size Class Filter Tabs
  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.addEventListener('click', (e) => {
      document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      currentFilter = e.target.getAttribute('data-filter');
      renderTable();
    });
  });

  // Subcategory Metric Dropdown
  document.getElementById('subcat-select').addEventListener('change', (e) => {
    currentSubcat = e.target.value;
    renderTable();
  });

  // Pin Model Dropdown
  document.getElementById('pin-model-select').addEventListener('change', (e) => {
    pinnedModelId = e.target.value;
    renderTable();
    updateRadarChart();
  });

  // Refresh Button
  document.getElementById('refresh-btn').addEventListener('click', () => {
    loadData();
  });

  // Context Slider
  document.getElementById('context-slider').addEventListener('input', (e) => {
    updateKVCalculator();
  });
}

function populatePinSelector() {
  const pinSelect = document.getElementById('pin-model-select');
  pinSelect.innerHTML = '<option value="">None (Absolute Scores)</option>';
  if (!leaderboardData || !leaderboardData.models) return;

  Object.values(leaderboardData.models).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = `${m.name} ${m.is_cloud ? '(Cloud)' : '(Local)'}`;
    pinSelect.appendChild(opt);
  });
}

function getBenchScores(benchmarks, name) {
  if (!benchmarks) return {};
  const target = name.toLowerCase();
  for (const k of Object.keys(benchmarks)) {
    if (k.toLowerCase() === target) {
      const b = benchmarks[k];
      return b.scores || b;
    }
  }
  return {};
}

function renderTable() {
  const tbody = document.getElementById('leaderboard-tbody');
  tbody.innerHTML = '';
  if (!leaderboardData || !leaderboardData.models) return;

  const pinnedModel = pinnedModelId ? leaderboardData.models[pinnedModelId] : null;

  Object.values(leaderboardData.models).forEach(model => {
    const specs = model.specs || {};
    const sizeClass = specs.size_class || '';

    // Filter matching
    if (currentFilter === 'cloud' && !model.is_cloud) return;
    if (currentFilter === 'edge' && !sizeClass.toLowerCase().includes('edge') && !sizeClass.includes('8B') && !sizeClass.includes('4B')) return;
    if (currentFilter === 'mid' && !sizeClass.toLowerCase().includes('mid') && !sizeClass.includes('35B') && !sizeClass.includes('27B')) return;
    if (currentFilter === 'moe' && !sizeClass.toLowerCase().includes('moe')) return;
    if (currentFilter === 'titan' && !sizeClass.toLowerCase().includes('titan') && !sizeClass.includes('70B')) return;

    const tr = document.createElement('tr');

    // Model Column
    const badgeClass = model.is_cloud ? 'cloud' : 'local';
    const badgeText = model.is_cloud ? 'Cloud Frontier' : 'Local Node';
    const nameHtml = `
      <div class="model-cell">
        <span class="model-name">${model.name}</span>
        <span class="model-meta">${specs.architecture || 'Transformer'} • ${specs.context_window ? (specs.context_window/1024).toFixed(0) + 'k ctx' : ''}</span>
      </div>
    `;

    // Benchmark Scores Extraction (Case-Insensitive)
    const bm = model.benchmarks || {};
    const ifeval = getBenchScores(bm, 'ifeval');
    const humaneval = getBenchScores(bm, 'humaneval');
    const ifevalcode = getBenchScores(bm, 'ifevalcode');
    const agentbench = getBenchScores(bm, 'agentbench');

    const ifevalStrict = ifeval.prompt_strict_acc ?? ifeval.strict_acc ?? ifeval.final_acc ?? null;
    const humanevalP1 = humaneval["pass@1"] ?? humaneval.accuracy ?? null;
    const ifevalCodePy = ifevalcode.python_correctness ?? ifevalcode.overall_accuracy ?? ifevalcode.correctness ?? null;
    const agentbenchAcc = agentbench.accuracy ?? null;

    // Selected Subcat Value
    let selScore = null;
    if (currentSubcat === 'ifeval_strict') selScore = ifevalStrict;
    else if (currentSubcat === 'ifeval_inst') selScore = ifeval.inst_strict_acc ?? null;
    else if (currentSubcat === 'code_python') selScore = ifevalcode.python_correctness ?? null;
    else if (currentSubcat === 'code_ts') selScore = ifevalcode.typescript_correctness ?? null;
    else if (currentSubcat === 'code_java') selScore = ifevalcode.java_correctness ?? null;
    else if (currentSubcat === 'agentbench_os') selScore = agentbenchAcc;
    else if (currentSubcat === 'humaneval_p1') selScore = humanevalP1;
    else {
      const validScores = [ifevalStrict, humanevalP1, ifevalCodePy, agentbenchAcc].filter(v => v !== null);
      selScore = validScores.length ? (validScores.reduce((a, b) => a + b, 0) / validScores.length) : null;
    }

    // Delta Computation against Pinned Model
    function formatScoreWithDelta(val, pinVal) {
      if (val === null || val === undefined) return '<span style="color:#6b7280">—</span>';
      const pct = (val * 100).toFixed(1) + '%';
      if (pinnedModel && pinVal !== null && pinVal !== undefined) {
        const delta = (val - pinVal) * 100;
        const deltaClass = delta >= 0 ? 'score-delta-pos' : 'score-delta-neg';
        const sign = delta >= 0 ? '+' : '';
        return `<span class="score-val">${pct}</span> <span class="${deltaClass}">(${sign}${delta.toFixed(1)}%)</span>`;
      }
      return `<span class="score-val">${pct}</span>`;
    }

    const pinBm = pinnedModel?.benchmarks || {};
    const pinIfeval = getBenchScores(pinBm, 'ifeval');
    const pinHumaneval = getBenchScores(pinBm, 'humaneval');
    const pinIfevalcode = getBenchScores(pinBm, 'ifevalcode');
    const pinAgentbench = getBenchScores(pinBm, 'agentbench');

    const pinIfevalStrict = pinIfeval.prompt_strict_acc ?? pinIfeval.strict_acc ?? pinIfeval.final_acc ?? null;
    const pinHumanevalP1 = pinHumaneval["pass@1"] ?? pinHumaneval.accuracy ?? null;
    const pinCodePy = pinIfevalcode.python_correctness ?? pinIfevalcode.overall_accuracy ?? pinIfevalcode.correctness ?? null;
    const pinAgentbenchAcc = pinAgentbench.accuracy ?? null;

    let pinSel = null;
    if (currentSubcat === 'ifeval_strict') pinSel = pinIfevalStrict;
    else if (currentSubcat === 'code_python') pinSel = pinCodePy;
    else if (currentSubcat === 'agentbench_os') pinSel = pinAgentbenchAcc;
    else if (currentSubcat === 'humaneval_p1') pinSel = pinHumanevalP1;

    tr.innerHTML = `
      <td>${nameHtml}</td>
      <td><span class="badge ${badgeClass}">${specs.size_class || badgeText}</span></td>
      <td>${formatScoreWithDelta(selScore, pinSel)}</td>
      <td class="academic-col">${formatScoreWithDelta(ifevalStrict, pinIfevalStrict)}</td>
      <td class="academic-col">${formatScoreWithDelta(humanevalP1, pinHumanevalP1)}</td>
      <td class="academic-col">${formatScoreWithDelta(ifevalCodePy, pinCodePy)}</td>
      <td class="academic-col">${formatScoreWithDelta(agentbenchAcc, pinAgentbenchAcc)}</td>
      ${(typeof EDS_TRIAXIS_HELPERS !== 'undefined') ? EDS_TRIAXIS_HELPERS.buildRowCells(bm) : ''}
      <td class="academic-col"><a class="hf-link" href="${specs.huggingface_url || '#'}" target="_blank">HF Model Card ↗</a></td>
    `;

    if (typeof EDS_TRIAXIS_HELPERS !== 'undefined') {
      EDS_TRIAXIS_HELPERS.markEdsRow(tr, bm);
    }
    tbody.appendChild(tr);
  });

  if (typeof EDS_TRIAXIS_HELPERS !== 'undefined') {
    EDS_TRIAXIS_HELPERS.afterRender();
  }
}

function initKVCalculator() {
  updateKVCalculator();
}

function updateKVCalculator() {
  const slider = document.getElementById('context-slider');
  const tokens = parseInt(slider.value, 10);
  document.getElementById('context-val-label').textContent = `${(tokens / 1024).toFixed(0)}k tokens`;

  // Formula: L * 2 * N_att * N_kv * Head_dim * Dtype / (TP * 1024^3)
  const kvBytesPerToken = 1536;
  const totalKvBytes = tokens * kvBytesPerToken;
  const kvGib = totalKvBytes / (1024 * 1024 * 1024);
  const weightsGib = 10.35;
  const cudaOverheadGib = 5.50;
  const totalEstGib = weightsGib + kvGib + cudaOverheadGib;

  document.getElementById('calc-kv-vram').textContent = `${kvGib.toFixed(2)} GiB`;
  document.getElementById('calc-weight-vram').textContent = `${weightsGib.toFixed(2)} GiB`;
  document.getElementById('calc-total-vram').textContent = `${totalEstGib.toFixed(2)} GiB`;
  document.getElementById('calc-kv-rate').textContent = `1.50 KiB/tok`;
}

function initRadarChart() {
  const canvas = document.getElementById('radarCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  radarChartInstance = new Chart(ctx, {
    type: 'radar',
    data: {
      labels: ['Instruction Strict', 'Python Pass@1', 'Polyglot Syntax', 'OS Terminal Agency', 'KV Metabolism (Eff)', 'Speculative TPS'],
      datasets: [
        {
          label: 'Nemotron 3.5 Lightning (Local)',
          data: [84, 88, 44, 24, 98, 92],
          backgroundColor: 'rgba(6, 182, 212, 0.2)',
          borderColor: '#06b6d4',
          borderWidth: 2,
          pointBackgroundColor: '#06b6d4',
        },
        {
          label: 'Claude 3.5 Sonnet (Cloud)',
          data: [88, 94, 88, 52, 60, 75],
          backgroundColor: 'rgba(59, 130, 246, 0.15)',
          borderColor: '#3b82f6',
          borderWidth: 2,
          pointBackgroundColor: '#3b82f6',
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        r: {
          angleLines: { color: 'rgba(255, 255, 255, 0.1)' },
          grid: { color: 'rgba(255, 255, 255, 0.08)' },
          pointLabels: { color: '#9ca3af', font: { size: 10 } },
          ticks: { display: false, min: 0, max: 100 }
        }
      },
      plugins: {
        legend: {
          labels: { color: '#f3f4f6', font: { size: 11 } }
        }
      }
    }
  });
}

function updateRadarChart() {
  if (!radarChartInstance || !leaderboardData) return;
  if (pinnedModelId && leaderboardData.models[pinnedModelId]) {
    const pin = leaderboardData.models[pinnedModelId];
    radarChartInstance.data.datasets[1].label = `${pin.name} (Pinned)`;
    radarChartInstance.update();
  }
}


// ===========================================================================
// Wave 7a — EDS Tri-Axis helpers (additive, scoped to a single
// ``EDS_TRIAXIS_HELPERS`` namespace so the legacy pipeline above is
// untouched). These helpers:
//
//   * ``pickEdsBenchmark(benchmarks)`` finds the first benchmark entry that
//     carries the ``eds_tag`` marker emitted by the
//     :class:`evalsbench.exporters.EDS_DASHBOARD_TAG` pipeline.
//   * ``buildRowCells(benchmarks)`` returns a string of ``<td>`` cells that
//     can be appended to the existing row HTML, mirroring the academic
//     column ordering convention. Renders ``—`` for missing fields.
//   * ``markEdsRow(tr, benchmarks)`` flags the row with ``data-eds="1"`` so
//     :func:`afterRender` can drive the EDS-only filter.
//   * ``afterRender()`` toggles row visibility for the EDS filter, shows /
//     hides the EDS column headers, and refreshes the Tri-Axis summary
//     card on the sidebar so an operator pivots between models without a
//     page reload.
//
// All helpers are pure DOM/API consumers; they never mutate
// ``leaderboardData`` directly.
// ===========================================================================

const EDS_TRIAXIS_HELPERS = (() => {
  /**
   * Canonical EDS marker propagated through the harvest pipeline. The
   * value MUST stay in lockstep with the exporters-side
   * :data:`EDS_DASHBOARD_TAG` constant.
   * @type {string}
   */
  const EDS_TAG = "eds_tri_axis";

  /**
   * Snapshot of the most-recent EDS aggregates we've seen for the
   * currently-pinned model. Refreshed by ``afterRender``.
   * @type {Object<string, any>|null}
   */
  let lastPinnedSnapshot = null;

  /**
   * Locate the first benchmark entry carrying the EDS marker.
   *
   * @param {Object<string, any>} benchmarks Model benchmarks dict.
   * @returns {Object<string, any>|null} The EDS entry, or null.
   */
  function pickEdsBenchmark(benchmarks) {
    if (!benchmarks || typeof benchmarks !== "object") return null;
    for (const [name, payload] of Object.entries(benchmarks)) {
      if (!payload || typeof payload !== "object") continue;
      if (payload.eds_tag === EDS_TAG) return payload;
      const camelName = name.toLowerCase();
      if (payload.eds_tag && String(payload.eds_tag).endsWith("tri_axis")) return payload;
      // Even without the tag, recognize the canonical MiniCorp / EDS keys
      // so historical harvests stay renderable.
      if (
        (camelName.includes("minicorp") || camelName.includes("eds")) &&
        ("functional_pass_rate" in payload || "mean_composite" in payload)
      ) {
        return payload;
      }
    }
    return null;
  }

  /**
   * Format a numeric EDS value as a human-friendly percent or scalar.
   *
   * @param {number|null|undefined} value Field value.
   * @param {boolean} asPercent Render as percent (multiply by 100).
   * @param {number} digits Decimal places for scalar renders.
   * @returns {string} Display string or em-dash for missing.
   */
  function fmtVal(value, asPercent = true, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return "—";
    }
    if (asPercent) return (value * 100).toFixed(digits) + "%";
    return Number(value).toFixed(digits);
  }

  /**
   * Build the EDS-only ``<td>`` cells appended after the academic columns.
   *
   * @param {Object<string, any>} benchmarks Model benchmarks dict.
   * @returns {string} HTML string of six ``<td>`` cells (or muted placeholders).
   */
  function buildRowCells(benchmarks) {
    const eds = pickEdsBenchmark(benchmarks);
    const cells = [];
    const asCell = (cls, value) =>
      `<td class="eds-cell ${value ? "" : "eds-cell-muted"}">${value}</td>`;
    if (!eds) {
      cells.push(asCell("functional", "—"));
      cells.push(asCell("hygiene", "—"));
      cells.push(asCell("safety", "—"));
      cells.push(asCell("ttft", "—"));
      cells.push(asCell("tps", "—"));
      cells.push(asCell("mtp", "—"));
      return cells.join("");
    }
    const functional = eds.functional_pass_rate ?? null;
    const hygiene = eds.hygiene_index ?? null;
    const tot = eds.safety_violations_total;
    const crit = eds.critical_violations_total;
    const safetyCell =
      tot === undefined && crit === undefined
        ? "—"
        : `${tot === undefined ? "—" : tot} / ${crit === undefined ? "—" : crit}`;
    const ttft = eds.median_ttft_s;
    const tps = eds.median_decode_tps;
    const mtp = eds.median_mtp_acceptance;
    cells.push(asCell("functional", fmtVal(functional, true, 1)));
    cells.push(asCell("hygiene", fmtVal(hygiene, true, 1)));
    cells.push(asCell("safety", safetyCell));
    cells.push(asCell("ttft", fmtVal(ttft, false, 3)));
    cells.push(asCell("tps", fmtVal(tps, false, 1)));
    cells.push(asCell("mtp", fmtVal(mtp, true, 1)));
    return cells.join("");
  }

  /**
   * Annotate a row so the EDS filter can recognize it.
   *
   * @param {HTMLTableRowElement} tr Row just rendered.
   * @param {Object<string, any>} benchmarks Model benchmarks dict.
   */
  function markEdsRow(tr, benchmarks) {
    if (!tr) return;
    const eds = pickEdsBenchmark(benchmarks);
    if (eds) {
      tr.classList.add("eds-row");
      tr.setAttribute("data-eds", "1");
    } else {
      tr.removeAttribute("data-eds");
    }
  }

  /**
   * Drive EDS-only filter and the Tri-Axis summary card.
   */
  function afterRender() {
    const tbody = document.getElementById("leaderboard-tbody");
    if (!tbody) return;
    const rows = tbody.querySelectorAll("tr");
    const onlyEds = (typeof currentFilter === "string") && currentFilter === "eds";
    document.body.classList.toggle("eds-mode", onlyEds);
    rows.forEach((row) => {
      if (!onlyEds) {
        row.style.display = "";
        return;
      }
      row.style.display = row.getAttribute("data-eds") === "1" ? "" : "none";
    });
    refreshTriAxisCard();
  }

  /**
   * Update the sidebar Tri-Axis widget to reflect the most relevant EDS
   * snapshot — the pinned model if one is selected, otherwise the
   * highest-volume EDS row currently visible.
   */
  function refreshTriAxisCard() {
    const widget = document.getElementById("eds-triaxis-widget");
    if (!widget) return;
    const snapshot =
      pickPinnedSnapshot() || pickFirstVisibleEdsSnapshot() || null;
    if (!snapshot) {
      widget.style.display = "none";
      lastPinnedSnapshot = null;
      return;
    }
    widget.style.display = "";
    lastPinnedSnapshot = snapshot;
    const functional = snapshot.functional_pass_rate;
    const hygiene = snapshot.hygiene_index;
    const safetyGate = snapshot.safety_gate_pass_rate;
    paintAxis("functional", functional);
    paintAxis("hygiene", hygiene);
    paintAxis("safety", safetyGate);
  }

  function pickPinnedSnapshot() {
    if (!pinnedModelId) return null;
    const model =
      leaderboardData && leaderboardData.models
        ? leaderboardData.models[pinnedModelId]
        : null;
    if (!model) return null;
    return pickEdsBenchmark(model.benchmarks);
  }

  function pickFirstVisibleEdsSnapshot() {
    const table = document.getElementById("leaderboard-table");
    if (!table || !leaderboardData) return null;
    const visibleEdsRow = table.querySelector('tr[data-eds="1"]');
    if (!visibleEdsRow) return null;
    // Find the model id by scanning leaderboardData.models until we
    // find one whose benchmarks yield an EDS entry that matches the
    // visible row. For a few dozen models this linear scan stays fast
    // enough; future waves can hash by id.
    for (const m of Object.values(leaderboardData.models)) {
      if (pickEdsBenchmark(m.benchmarks)) return pickEdsBenchmark(m.benchmarks);
    }
    return null;
  }

  function paintAxis(name, value) {
    const bar = document.getElementById("eds-bar-" + name);
    const label = document.getElementById("eds-val-" + name);
    if (!bar || !label) return;
    if (value === null || value === undefined || Number.isNaN(value)) {
      bar.style.width = "0%";
      label.textContent = "—";
      return;
    }
    const pct = Math.max(0, Math.min(100, value * 100));
    bar.style.width = pct.toFixed(1) + "%";
    label.textContent = pct.toFixed(1) + "%";
  }

  function init() {
    // Wire up the EDS filter tab explicitly so the existing nav-tab
    // bulk handler bypasses filter rows without EDS data. We also keep
    // the existing nav-tab handler intact — it's a no-op for rows
    // lacking the EDS marker in our model.
    const edstab = document.getElementById("eds-filter-tab");
    if (edstab) {
      edstab.addEventListener("click", () => {
        document.body.classList.add("eds-mode");
      });
    }
    afterRender();
  }

  return {
    init,
    pickEdsBenchmark,
    buildRowCells,
    markEdsRow,
    afterRender,
    refreshTriAxisCard,
    EDS_TAG,
  };
})();
