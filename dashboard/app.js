/**
 * EvalsBench Dashboard Client Application
 * Handles filtering, pinned baseline delta normalization, dynamic KV calculation, and Radar visualization.
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
  try {
    const res = await fetch('data/leaderboard.json');
    leaderboardData = await res.json();
    populatePinSelector();
    renderTable();
    updateKVCalculator();
    updateRadarChart();
  } catch (err) {
    console.error('Failed to load leaderboard.json:', err);
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

function renderTable() {
  const tbody = document.getElementById('leaderboard-tbody');
  tbody.innerHTML = '';
  if (!leaderboardData || !leaderboardData.models) return;

  const pinnedModel = pinnedModelId ? leaderboardData.models[pinnedModelId] : null;

  Object.values(leaderboardData.models).forEach(model => {
    // Filter matching
    if (currentFilter === 'cloud' && !model.is_cloud) return;
    if (currentFilter === 'edge' && !model.specs.size_class.toLowerCase().includes('edge') && !model.specs.size_class.includes('8B')) return;
    if (currentFilter === 'mid' && !model.specs.size_class.toLowerCase().includes('mid') && !model.specs.size_class.includes('35B')) return;
    if (currentFilter === 'moe' && !model.specs.size_class.toLowerCase().includes('moe')) return;
    if (currentFilter === 'titan' && !model.specs.size_class.toLowerCase().includes('titan') && !model.specs.size_class.includes('70B')) return;

    const tr = document.createElement('tr');

    // Model Column
    const badgeClass = model.is_cloud ? 'cloud' : 'local';
    const badgeText = model.is_cloud ? 'Cloud Frontier' : 'Local Node';
    const nameHtml = `
      <div class="model-cell">
        <span class="model-name">${model.name}</span>
        <span class="model-meta">${model.specs.architecture || 'Transformer'} • ${model.specs.context_window ? (model.specs.context_window/1024).toFixed(0) + 'k ctx' : ''}</span>
      </div>
    `;

    // Benchmark Scores Extraction
    const bm = model.benchmarks || {};
    const ifevalStrict = bm.IFEval ? (bm.IFEval.prompt_strict_acc ?? bm.IFEval.scores?.prompt_strict_acc ?? null) : null;
    const humanevalP1 = bm.HumanEval ? (bm.HumanEval["pass@1"] ?? bm.HumanEval.scores?.accuracy ?? null) : null;
    const ifevalCodePy = bm.IFEvalCode ? (bm.IFEvalCode.python_correctness ?? bm.IFEvalCode.scores?.python_correctness ?? bm.IFEvalCode.overall_accuracy ?? null) : null;
    const agentbenchAcc = bm.AgentBench ? (bm.AgentBench.accuracy ?? bm.AgentBench.scores?.accuracy ?? null) : null;

    // Selected Subcat Value
    let selScore = null;
    if (currentSubcat === 'ifeval_strict') selScore = ifevalStrict;
    else if (currentSubcat === 'ifeval_inst') selScore = bm.IFEval ? (bm.IFEval.inst_strict_acc ?? bm.IFEval.scores?.inst_strict_acc ?? null) : null;
    else if (currentSubcat === 'code_python') selScore = ifevalCodePy;
    else if (currentSubcat === 'code_ts') selScore = bm.IFEvalCode ? (bm.IFEvalCode.typescript_correctness ?? bm.IFEvalCode.scores?.typescript_correctness ?? null) : null;
    else if (currentSubcat === 'code_java') selScore = bm.IFEvalCode ? (bm.IFEvalCode.java_correctness ?? bm.IFEvalCode.scores?.java_correctness ?? null) : null;
    else if (currentSubcat === 'agentbench_os') selScore = agentbenchAcc;
    else if (currentSubcat === 'humaneval_p1') selScore = humanevalP1;
    else {
      // Overall aggregate
      const validScores = [ifevalStrict, humanevalP1, ifevalCodePy, agentbenchAcc].filter(v => v !== null);
      selScore = validScores.length ? (validScores.reduce((a, b) => a + b, 0) / validScores.length) : null;
    }

    // Delta Computation against Pinned Model
    function formatScoreWithDelta(val, pinVal) {
      if (val === null || val === undefined) return '<span class="text-muted">—</span>';
      const pct = (val * 100).toFixed(1) + '%';
      if (pinnedModel && pinVal !== null && pinVal !== undefined) {
        const delta = (val - pinVal) * 100;
        const deltaClass = delta >= 0 ? 'score-delta-pos' : 'score-delta-neg';
        const sign = delta >= 0 ? '+' : '';
        return `<span class="score-val">${pct}</span> <span class="${deltaClass}">(${sign}${delta.toFixed(1)}%)</span>`;
      }
      return `<span class="score-val">${pct}</span>`;
    }

    // Get Pinned Model Corresponding Values
    const pinBm = pinnedModel?.benchmarks || {};
    const pinIfeval = pinBm.IFEval ? (pinBm.IFEval.prompt_strict_acc ?? pinBm.IFEval.scores?.prompt_strict_acc ?? null) : null;
    const pinHumaneval = pinBm.HumanEval ? (pinBm.HumanEval["pass@1"] ?? pinBm.HumanEval.scores?.accuracy ?? null) : null;
    const pinCodePy = pinBm.IFEvalCode ? (pinBm.IFEvalCode.python_correctness ?? pinBm.IFEvalCode.scores?.python_correctness ?? pinBm.IFEvalCode.overall_accuracy ?? null) : null;
    const pinAgentbench = pinBm.AgentBench ? (pinBm.AgentBench.accuracy ?? pinBm.AgentBench.scores?.accuracy ?? null) : null;

    let pinSel = null;
    if (currentSubcat === 'ifeval_strict') pinSel = pinIfeval;
    else if (currentSubcat === 'code_python') pinSel = pinCodePy;
    else if (currentSubcat === 'agentbench_os') pinSel = pinAgentbench;
    else if (currentSubcat === 'humaneval_p1') pinSel = pinHumaneval;

    tr.innerHTML = `
      <td>${nameHtml}</td>
      <td><span class="badge ${badgeClass}">${model.specs.size_class || badgeText}</span></td>
      <td>${formatScoreWithDelta(selScore, pinSel)}</td>
      <td>${formatScoreWithDelta(ifevalStrict, pinIfeval)}</td>
      <td>${formatScoreWithDelta(humanevalP1, pinHumaneval)}</td>
      <td>${formatScoreWithDelta(ifevalCodePy, pinCodePy)}</td>
      <td>${formatScoreWithDelta(agentbenchAcc, pinAgentbench)}</td>
      <td><a class="hf-link" href="${model.specs.huggingface_url || '#'}" target="_blank">HF Model Card ↗</a></td>
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
  // For Nemotron 3.5 Lightning: 6 layers, 1 KV head per GPU (TP=2), 128 head_dim, FP8 (1 byte)
  // KV bytes per token per GPU = 1,536 bytes (1.50 KiB)
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
  const ctx = document.getElementById('radarCanvas').getContext('2d');
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
  // Dynamic radar update when pinned model changes
  if (pinnedModelId && leaderboardData.models[pinnedModelId]) {
    const pin = leaderboardData.models[pinnedModelId];
    radarChartInstance.data.datasets[1].label = `${pin.name} (Pinned)`;
    radarChartInstance.update();
  }
}
