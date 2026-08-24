/**
 * EvalsBench Dashboard Client Application
 * Supports zero-CORS file:// local loading, interactive size-class filtering,
 * pinned model baseline comparisons, dynamic KV cache calculations, and Radar visualization.
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
      <td>${formatScoreWithDelta(ifevalStrict, pinIfevalStrict)}</td>
      <td>${formatScoreWithDelta(humanevalP1, pinHumanevalP1)}</td>
      <td>${formatScoreWithDelta(ifevalCodePy, pinCodePy)}</td>
      <td>${formatScoreWithDelta(agentbenchAcc, pinAgentbenchAcc)}</td>
      <td><a class="hf-link" href="${specs.huggingface_url || '#'}" target="_blank">HF Model Card ↗</a></td>
    `;

    tbody.appendChild(tr);
  });
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
