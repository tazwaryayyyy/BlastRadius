/**
 * app.js
 * BlastRadius frontend — main orchestrator.
 *
 * Handles:
 *  - Demo mode (one-click, pre-seeded PR)
 *  - Custom PR analysis (paste a diff)
 *  - SSE streaming display
 *  - Wiring graph + diff viewer + detail panel
 */

/* global BlastGraph, DiffViewer */

const API_BASE = window.API_BASE || 'http://localhost:8000';

// ── State ──────────────────────────────────────────────────────────
let currentReport = null;

// ── DOM refs ───────────────────────────────────────────────────────
const demoBtn         = document.getElementById('demo-btn');
const analyzeBtn      = document.getElementById('analyze-btn');
const diffInput       = document.getElementById('diff-input');
const graphIdle       = document.getElementById('graph-idle');
const streamLog       = document.getElementById('stream-log');
const streamContent   = document.getElementById('stream-content');
const streamMetrics   = document.getElementById('stream-metrics');
const detailPanel     = document.getElementById('detail-panel');
const detailEmpty     = document.getElementById('detail-empty');
const noChainsState   = document.getElementById('no-chains-state');
const riskBadge       = document.getElementById('risk-badge');
const prTitleEl       = document.getElementById('pr-title');
const riskSummaryEl   = document.getElementById('risk-summary');
const mergeVerdictEl  = document.getElementById('merge-verdict');
const recommendBar    = document.getElementById('recommendation-bar');
const bobMetrics      = document.getElementById('bob-metrics');

// Analysis timing
let analysisStartTime = null;


// ── Init ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  BlastGraph.initGraph('graph-canvas', onNodeClick);

  demoBtn.addEventListener('click', runDemo);
  analyzeBtn?.addEventListener('click', runCustomAnalysis);
});


// ── Demo flow ──────────────────────────────────────────────────────
async function runDemo() {
  setLoading(true);
  clearUI();

  try {
    // Load the diff text for the diff viewer
    const diffResp = await fetch(`${API_BASE}/api/demo/diff`);
    const { diff, pr_title } = await diffResp.json();
    DiffViewer.renderDiff('diff-container', diff, []);

    if (prTitleEl) prTitleEl.textContent = pr_title;

    analysisStartTime = Date.now();
    // Stream the analysis
    await streamAnalysis(diff, 'demo_repo', pr_title);

  } catch (err) {
    showError(err.message);
    setLoading(false);
  }
}


// ── Custom PR analysis ─────────────────────────────────────────────
async function runCustomAnalysis() {
  const diff = diffInput?.value?.trim();
  if (!diff) {
    alert('Paste a unified diff first.');
    return;
  }

  setLoading(true);
  clearUI();
  DiffViewer.renderDiff('diff-container', diff, []);

  try {
    await streamAnalysis(diff, 'demo_repo', 'Custom PR');
  } catch (err) {
    showError(err.message);
    setLoading(false);
  }
}


// ── SSE streaming ──────────────────────────────────────────────────
async function streamAnalysis(diff, repoPath, prTitle) {
  const params = new URLSearchParams({
    diff,
    repo_path: repoPath,
    pr_title: prTitle ?? '',
  });

  showStreamLog();

  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API_BASE}/api/stream?${params.toString()}`);

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'token') {
        // Append Bob's reasoning token-by-token
        appendStreamToken(data.content);
        // Live metrics: tokens processed
        if (streamMetrics && data.token_count) {
          const elapsed = analysisStartTime ? ((Date.now() - analysisStartTime) / 1000).toFixed(1) : '';
          streamMetrics.textContent = `${data.token_count} tokens · ${elapsed}s`;
        }
        return;
      }

      if (data.type === 'done') {
        es.close();
        hideStreamLog();
        renderReport(data.report);
        setLoading(false);
        resolve(data.report);
        return;
      }

      if (data.type === 'error') {
        es.close();
        hideStreamLog();
        showError(data.message);
        setLoading(false);
        reject(new Error(data.message));
      }
    };

    es.onerror = (err) => {
      es.close();
      hideStreamLog();
      // Fallback to non-streaming POST
      fetchAnalysis(diff, repoPath, prTitle).then(resolve).catch(reject);
    };
  });
}


// ── Non-streaming fallback ─────────────────────────────────────────
async function fetchAnalysis(diff, repoPath, prTitle) {
  const resp = await fetch(`${API_BASE}/api/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ diff, repo_path: repoPath, pr_title: prTitle }),
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail ?? 'Analysis failed');
  }

  const report = await resp.json();
  renderReport(report);
  setLoading(false);
  return report;
}


// ── Render report ──────────────────────────────────────────────────
function renderReport(report) {
  currentReport = report;

  // Bob metrics — files analyzed + time taken
  const elapsed = analysisStartTime ? ((Date.now() - analysisStartTime) / 1000).toFixed(1) : null;
  const fileCount = new Set(report.call_chains.flatMap(c => c.path)).size;
  if (bobMetrics) {
    const parts = [];
    if (fileCount > 0) parts.push(`${fileCount} files traced`);
    if (elapsed) parts.push(`${elapsed}s`);
    if (parts.length) {
      bobMetrics.style.display = 'flex';
      bobMetrics.innerHTML = parts.map(p =>
        `<span style="background:var(--bg-card);border:1px solid var(--border);padding:1px 8px;border-radius:3px">${p}</span>`
      ).join('');
    }
  }

  // Graph
  graphIdle.style.display = 'none';
  BlastGraph.renderGraph(report);

  // Risk badge in header
  const topRisk = getTopRisk(report.risk_summary);
  if (topRisk) {
    riskBadge.textContent = topRisk;
    riskBadge.className = topRisk;
  }

  // Risk summary counts
  renderRiskSummary(report.risk_summary);

  // Merge recommendation
  renderMergeVerdict(report.merge_recommendation);

  // Chain list — handle empty state
  if (report.call_chains.length === 0) {
    detailEmpty.style.display = 'none';
    if (noChainsState) noChainsState.style.display = 'block';
  } else {
    renderChainList(report);
  }

  // Update diff viewer with blast entry symbols
  DiffViewer.renderDiff('diff-container',
    currentReport._diff ?? '',
    report.changed_symbols
  );
}


// ── Chain detail ───────────────────────────────────────────────────
function renderChainList(report) {
  detailEmpty.style.display = 'none';

  // Sort: CRITICAL first
  const riskOrder = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
  const sorted = [...report.call_chains].sort(
    (a, b) => (riskOrder[a.risk] ?? 9) - (riskOrder[b.risk] ?? 9)
  );

  const cards = sorted.map((chain) => buildChainCard(chain)).join('');
  detailPanel.innerHTML = cards;

  // Click handlers
  detailPanel.querySelectorAll('.chain-card').forEach((card) => {
    card.addEventListener('click', () => {
      const chainId = card.dataset.chainId;
      const chain = report.call_chains.find((c) => c.id === chainId);
      if (!chain) return;

      detailPanel.querySelectorAll('.chain-card').forEach((c) => c.classList.remove('active'));
      card.classList.add('active');
    });
  });
}


function buildChainCard(chain) {
  const pathHtml = chain.path.map((p, i) => {
    const name = p.split('/').pop();
    const isChanged = i === 0;
    return `<span class="node${isChanged ? ' changed' : ''}">${name}</span>${
      i < chain.path.length - 1 ? '<span class="arrow">→</span>' : ''
    }`;
  }).join('');

  const testHtml = chain.has_tests
    ? `<div class="chain-has-tests">✓ Test coverage exists</div>`
    : `<div class="chain-no-tests">⚠ No test coverage for this path</div>`;

  const testFiles = chain.test_files?.length
    ? `<div style="font-size:11px;color:var(--text-3);margin-top:5px">
         Tests: ${chain.test_files.map((f) => f.split('/').pop()).join(', ')}
       </div>`
    : '';

  return `
    <div class="chain-card risk-${chain.risk}" data-chain-id="${chain.id}">
      <div class="chain-risk-badge">${chain.risk}</div>
      <div class="chain-path">${pathHtml}</div>
      <div class="chain-impact">${chain.business_impact}</div>
      ${testHtml}
      ${testFiles}
      <div class="chain-explanation">${chain.explanation}</div>
    </div>
  `;
}


function onNodeClick(node, report) {
  if (!node) {
    // Reset — deselect all cards
    detailPanel.querySelectorAll('.chain-card').forEach((c) => c.classList.remove('active'));
    return;
  }

  // Find chains that include this node's file
  const matchingChainIds = report.call_chains
    .filter((c) => c.path.includes(node.id))
    .map((c) => c.id);

  detailPanel.querySelectorAll('.chain-card').forEach((card) => {
    const active = matchingChainIds.includes(card.dataset.chainId);
    card.classList.toggle('active', active);
    if (active) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
}


// ── Risk summary bar ───────────────────────────────────────────────
function renderRiskSummary(summary) {
  const levels = [
    { key: 'CRITICAL', cls: 'critical' },
    { key: 'HIGH',     cls: 'high'     },
    { key: 'MEDIUM',   cls: 'medium'   },
    { key: 'LOW',      cls: 'low'      },
  ];

  riskSummaryEl.style.display = 'flex';
  riskSummaryEl.innerHTML = levels
    .filter((l) => summary[l.key] > 0)
    .map((l) => `
      <div class="risk-count ${l.cls}">
        <div class="dot"></div>
        ${summary[l.key]} ${l.key}
      </div>
    `).join('');
}


function renderMergeVerdict(recommendation) {
  if (!recommendation) return;
  mergeVerdictEl.style.display = 'block';
  recommendBar.style.display = 'block';

  const isBlock = recommendation.toUpperCase().includes('BLOCK');
  mergeVerdictEl.className = isBlock ? 'block' : 'safe';
  mergeVerdictEl.textContent = recommendation;
}


// ── Helpers ────────────────────────────────────────────────────────
function getTopRisk(summary) {
  if (summary.CRITICAL > 0) return 'CRITICAL';
  if (summary.HIGH > 0)     return 'HIGH';
  if (summary.MEDIUM > 0)   return 'MEDIUM';
  if (summary.LOW > 0)      return 'LOW';
  return null;
}


function setLoading(loading) {
  demoBtn.disabled = loading;
  demoBtn.textContent = loading ? 'Analyzing…' : 'Run Demo';
  if (analyzeBtn) analyzeBtn.disabled = loading;
}


function clearUI() {
  graphIdle.style.display = 'flex';
  detailPanel.innerHTML = '';
  detailEmpty.style.display = 'block';
  if (noChainsState) noChainsState.style.display = 'none';
  riskBadge.className = '';
  riskBadge.style.display = 'none';
  riskSummaryEl.style.display = 'none';
  riskSummaryEl.innerHTML = '';
  mergeVerdictEl.style.display = 'none';
  recommendBar.style.display = 'none';
  if (bobMetrics) bobMetrics.style.display = 'none';
  analysisStartTime = null;
  DiffViewer.clearDiff('diff-container');
}


function showStreamLog() {
  streamLog.classList.add('visible');
  streamContent.textContent = '';
}


function hideStreamLog() {
  setTimeout(() => streamLog.classList.remove('visible'), 1200);
}


function appendStreamToken(token) {
  streamContent.textContent += token;
  streamLog.scrollTop = streamLog.scrollHeight;
}


function showError(msg) {
  detailEmpty.style.display = 'block';
  detailEmpty.innerHTML = `<span style="color:var(--critical)">Error: ${msg}</span>`;
}
