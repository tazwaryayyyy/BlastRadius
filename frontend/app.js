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

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : 'https://blastradius-api-dz0l.onrender.com';

// ── State ──────────────────────────────────────────────────────────
let currentReport = null;
let currentReportId = null;
let currentDiff = '';
let activeStream = null;

// ── DOM refs ───────────────────────────────────────────────────────
const demoBtn = document.getElementById('demo-btn');
const analyzeBtn = document.getElementById('analyze-btn');
const diffInput = document.getElementById('diff-input');
const graphIdle = document.getElementById('graph-idle');
const streamLog = document.getElementById('stream-log');
const streamContent = document.getElementById('stream-content');
const streamMetrics = document.getElementById('stream-metrics');
const detailPanel = document.getElementById('detail-panel');
const detailEmpty = document.getElementById('detail-empty');
const noChainsState = document.getElementById('no-chains-state');
const riskBadge = document.getElementById('risk-badge');
const riskScoreEl = document.getElementById('risk-score');
const riskScoreValue = document.getElementById('risk-score-value');
const prTitleEl = document.getElementById('pr-title');
const riskSummaryEl = document.getElementById('risk-summary');
const mergeVerdictEl = document.getElementById('merge-verdict');
const recommendBar = document.getElementById('recommendation-bar');
const suggestedActionsEl = document.getElementById('suggested-actions');
const bobMetrics = document.getElementById('bob-metrics');

// Analysis timing
let analysisStartTime = null;
let streamSteps = [];

const STAGE_LABELS = {
  loading_repo: 'Loading repository context...',
  parsing_diff: 'Parsing diff and extracting symbols...',
  tracing_callers: 'Tracing callers of changed symbols...',
  building_chains: 'Building upstream call chains...',
  checking_coverage: 'Checking test coverage...',
  generating_verdict: 'Computing merge verdict...',
};


// ── Init ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  BlastGraph.initGraph('graph-canvas', onNodeClick);

  demoBtn.addEventListener('click', runDemo);
  analyzeBtn?.addEventListener('click', runCustomAnalysis);

  // Inline GitHub URL panel — Analyze PR button
  document.getElementById('analyze-github-btn')?.addEventListener('click', async () => {
    const prUrl = document.getElementById('pr-url-input')?.value?.trim();
    if (!prUrl) {
      showWarning(document.getElementById('pr-url-input'), 'Enter a GitHub PR URL first.');
      return;
    }
    setLoading(true);
    if (prTitleEl) prTitleEl.textContent = prUrl;
    analysisStartTime = Date.now();
    try {
      await streamGithubAnalysis(prUrl);
    } catch (err) {
      showError(err.message);
      setLoading(false);
    }
  });

  // Restore saved input mode
  const savedMode = sessionStorage.getItem('inputMode') || 'url';
  _applyInputMode(savedMode);

  // Background warmup
  fetch(`${API_BASE}/api/warmup`).catch(() => { });

  // Deep-link: ?report=UUID
  const params = new URLSearchParams(window.location.search);
  const reportId = params.get('report');
  if (reportId) {
    loadSharedReport(reportId);
  }
});


// ── Demo flow ──────────────────────────────────────────────────────
async function runDemo() {
  setLoading(true);
  resetUI();

  try {
    // Load the diff text for the diff viewer
    const diffResp = await fetch(`${API_BASE}/api/demo/diff`);
    if (!diffResp.ok) {
      throw new Error(`Demo diff request failed (${diffResp.status})`);
    }

    const { diff, pr_title } = await diffResp.json();
    if (typeof diff !== 'string' || !diff.trim()) {
      throw new Error('Demo diff payload is missing or invalid.');
    }

    currentDiff = diff;
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
    showWarning(diffInput, 'Paste a unified diff first.');
    return;
  }

  document.getElementById('custom-modal').style.display = 'none';

  setLoading(true);
  resetUI();
  currentDiff = diff;
  DiffViewer.renderDiff('diff-container', diff, []);

  if (prTitleEl) prTitleEl.textContent = 'Custom PR';

  try {
    analysisStartTime = Date.now();
    await streamAnalysis(diff, 'demo_repo', 'Custom PR');
  } catch (err) {
    showError(err.message);
    setLoading(false);
  }
}


// ── SSE streaming ──────────────────────────────────────────────────
//
// BACKEND_REQUIRED:
//   POST /api/stream/session
//   Body: { diff: string, repo_path: string, pr_title: string }
//   Returns: { session_id: string }  (UUID, expires after stream completes or 5 min)
//
//   GET /api/stream?session_id=<UUID>
//   Opens SSE. The session data is server-side; no diff content appears in the URL.
//
async function streamAnalysis(diff, repoPath, prTitle) {
  showStreamLog();

  // POST the diff body to get a server-side session token.
  // The EventSource URL then carries only an opaque UUID, not the diff content.
  let sessionId;
  try {
    const sessionResp = await fetch(`${API_BASE}/api/stream/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ diff, repo_path: repoPath, pr_title: prTitle ?? '' }),
    });
    if (!sessionResp.ok) {
      throw new Error(`Session creation failed (${sessionResp.status})`);
    }
    ({ session_id: sessionId } = await sessionResp.json());
  } catch (err) {
    hideStreamLog();
    throw err;
  }

  return new Promise((resolve, reject) => {
    if (activeStream) {
      activeStream.close();
      activeStream = null;
    }
    const es = new EventSource(`${API_BASE}/api/stream?session_id=${encodeURIComponent(sessionId)}`);
    activeStream = es;

    let resolvedReport = null;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'token') {
        if (streamMetrics && data.token_count) {
          const elapsed = analysisStartTime ? ((Date.now() - analysisStartTime) / 1000).toFixed(1) : '';
          streamMetrics.textContent = `${data.token_count} tokens · ${elapsed}s`;
        }
        return;
      }

      if (data.type === 'stage') {
        const label = STAGE_LABELS[data.stage];
        if (label) {
          renderStreamStep(label);
        } else {
          console.warn('Unknown stage event from backend:', data.stage);
        }
        return;
      }

      if (data.type === 'result') {
        resolvedReport = data.report;
        currentReportId = data.report_id || null;
        return;
      }

      if (data.type === 'done') {
        es.close();
        activeStream = null;
        hideStreamLog();
        setLoading(false);
        if (resolvedReport) {
          finalizeStreamSteps(resolvedReport);
          renderReport(resolvedReport);
          resolve(resolvedReport);
        } else {
          reject(new Error('No report received'));
        }
        return;
      }

      if (data.type === 'error') {
        es.close();
        activeStream = null;
        hideStreamLog();
        showError(data.message);
        setLoading(false);
        reject(new Error(data.message));
      }
    };

    es.onerror = () => {
      es.close();
      activeStream = null;
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
        `<span class="bob-metric-pill">${p}</span>`
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

  renderRiskScore(computeRiskScore(report));

  // Risk summary counts
  renderRiskSummary(report.risk_summary);

  // Merge recommendation
  renderMergeVerdict(report.merge_recommendation);
  renderSuggestedActions(report.suggested_actions || []);

  // Chain list — handle empty state
  if (report.call_chains.length === 0) {
    detailEmpty.style.display = 'none';
    if (noChainsState) noChainsState.style.display = 'block';
  } else {
    renderChainList(report);
  }

  // Update diff viewer with blast entry symbols
  DiffViewer.renderDiff('diff-container',
    currentDiff,
    report.changed_symbols
  );

  // Share bar
  if (currentReportId) {
    history.replaceState(null, '', `?report=${currentReportId}`);
    showShareBar(currentReportId);
  }

  // Context stats
  if (report.context_stats) {
    showContextStats(report.context_stats);
  }
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
    return `<span class="node${isChanged ? ' changed' : ''}">${name}</span>${i < chain.path.length - 1 ? '<span class="arrow">→</span>' : ''
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

  const confLevel = (chain.confidence || 'MEDIUM').toUpperCase();
  const confReason = confLevel === 'LOW'
    ? `${chain.confidence_reason || ''} — verify dynamic dispatch manually`
    : (chain.confidence_reason || '');
  const confidence = `
    <div class="chain-confidence confidence-${confLevel}">
      ${confLevel} confidence${confReason ? ` · ${escapeHtml(confReason)}` : ''}
    </div>`;

  return `
    <div class="chain-card risk-${chain.risk}" data-chain-id="${chain.id}">
      <div class="chain-risk-badge">${chain.risk}</div>
      <div class="chain-path">${pathHtml}</div>
      <div class="chain-impact">${escapeHtml(chain.business_impact)}</div>
      ${confidence}
      ${testHtml}
      ${testFiles}
      <div class="chain-explanation">${escapeHtml(chain.explanation)}</div>
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
    { key: 'HIGH', cls: 'high' },
    { key: 'MEDIUM', cls: 'medium' },
    { key: 'LOW', cls: 'low' },
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


function renderSuggestedActions(actions) {
  if (!suggestedActionsEl) return;
  if (!actions.length) {
    suggestedActionsEl.innerHTML = '';
    suggestedActionsEl.style.display = 'none';
    return;
  }

  suggestedActionsEl.style.display = 'block';
  suggestedActionsEl.innerHTML = `
    <div class="actions-title">What to do before merging</div>
    ${actions.map((action) => `
      <label class="action-item">
        <input type="checkbox" />
        <span>${escapeHtml(action)}</span>
      </label>
    `).join('')}
  `;
}


function computeRiskScore(report) {
  let score = 0;
  const chains = report.call_chains || [];

  chains.forEach((chain) => {
    const risk = (chain.risk || '').toUpperCase();
    if (risk === 'CRITICAL') score += 40;
    else if (risk === 'HIGH') score += 25;
    else if (risk === 'MEDIUM') score += 10;
    else score += 3;

    if (!chain.has_tests) score += 15;
    score += (chain.path?.length || 0) * 2;

    const conf = (chain.confidence || '').toUpperCase();
    if (conf === 'LOW') score += 8;
    else if (conf === 'MEDIUM') score += 4;
  });

  return Math.min(score, 100);
}


function renderRiskScore(score) {
  if (!riskScoreEl || !riskScoreValue) return;

  riskScoreValue.textContent = String(score);
  riskScoreEl.className = score === 0
    ? 'score-neutral'
    : score >= 75
      ? 'score-critical'
      : score >= 55
        ? 'score-high'
        : score >= 30
          ? 'score-moderate'
          : 'score-low';
}


// ── Helpers ────────────────────────────────────────────────────────
function getTopRisk(summary) {
  if (summary.CRITICAL > 0) return 'CRITICAL';
  if (summary.HIGH > 0) return 'HIGH';
  if (summary.MEDIUM > 0) return 'MEDIUM';
  if (summary.LOW > 0) return 'LOW';
  return null;
}


function setLoading(loading) {
  demoBtn.disabled = loading;
  demoBtn.textContent = loading ? 'Analyzing...' : 'Run Demo';
  if (analyzeBtn) analyzeBtn.disabled = loading;
}


function clearUI() {
  graphIdle.style.display = 'flex';
  detailPanel.innerHTML = '';
  detailEmpty.style.display = 'block';
  detailEmpty.innerHTML = 'Click a node in the graph<br />to see its blast radius chain.';
  if (noChainsState) noChainsState.style.display = 'none';
  riskBadge.className = '';
  riskBadge.style.display = 'none';
  if (riskScoreValue) riskScoreValue.textContent = '0';
  if (riskScoreEl) riskScoreEl.className = 'score-neutral';
  riskSummaryEl.style.display = 'none';
  riskSummaryEl.innerHTML = '';
  mergeVerdictEl.style.display = 'none';
  recommendBar.style.display = 'none';
  if (suggestedActionsEl) {
    suggestedActionsEl.innerHTML = '';
    suggestedActionsEl.style.display = 'none';
  }
  if (bobMetrics) bobMetrics.style.display = 'none';
  analysisStartTime = null;
  streamSteps = [];
  DiffViewer.clearDiff('diff-container');
}

function resetUI() {
  // Cancel any active SSE stream
  if (activeStream) {
    activeStream.close();
    activeStream = null;
  }

  // Reset state
  currentReport = null;
  currentReportId = null;

  // Clear D3 graph
  if (typeof window.BlastGraph?.destroy === 'function') {
    window.BlastGraph.destroy();
  }
  const svgEl = document.querySelector('#graph-canvas svg');
  if (svgEl) svgEl.innerHTML = '';

  // Hide share bar and context stats bar
  const shareBar = document.getElementById('share-bar');
  if (shareBar) shareBar.style.display = 'none';
  const statsBar = document.getElementById('context-stats-bar');
  if (statsBar) statsBar.style.display = 'none';

  // Clear everything else
  clearUI();
}


function showStreamLog() {
  streamLog.classList.add('visible');
  streamSteps = [];
  renderStreamStep('Identifying changed symbols...');
}


function hideStreamLog() {
  setTimeout(() => streamLog.classList.remove('visible'), 1200);
}



function finalizeStreamSteps(report) {
  const chain = (report.call_chains || [])[0];

  if (chain?.symbols?.[0]) {
    renderStreamStep(`Tracing callers of ${chain.symbols[0]}...`);
  }

  if (chain?.path?.[1]) {
    renderStreamStep(`Found usage in ${chain.path[1]}...`);
  }

  if (chain?.symbols?.[1]) {
    renderStreamStep(`Tracing callers of ${chain.symbols[1]}...`);
  }

  if (chain?.path?.length > 2) {
    renderStreamStep(`Found ${chain.path.slice(2).join(' -> ')} in chain...`);
  }

  if (chain) {
    renderStreamStep(chain.has_tests ? 'Test coverage found for this path.' : 'No tests found for this path...');
    renderStreamStep(`Risk classification: ${chain.risk}`);
  }
}


function renderStreamStep(message) {
  if (!streamContent || streamSteps.includes(message)) return;

  streamSteps.push(message);
  streamContent.innerHTML = streamSteps
    .map((step) => `<div class="stream-step">&#9656; ${escapeHtml(step)}</div>`)
    .join('');
}


function showError(msg) {
  detailEmpty.style.display = 'block';
  detailEmpty.innerHTML = `<span style="color:var(--critical)">Error: ${escapeHtml(msg)}</span>`;
}

function showWarning(anchorEl, msg) {
  const existing = anchorEl?.parentElement?.querySelector('.inline-warning');
  if (existing) existing.remove();
  const warn = document.createElement('div');
  warn.className = 'inline-warning';
  warn.textContent = msg;
  anchorEl?.insertAdjacentElement('afterend', warn);
  setTimeout(() => warn.remove(), 3500);
}


// ── GitHub URL analysis ────────────────────────────────────────────
async function streamGithubAnalysis(prUrl) {
  resetUI();

  const _urlInput = document.getElementById('pr-url-input');
  const _analyzeBtn = document.getElementById('analyze-github-btn');
  if (_urlInput) _urlInput.readOnly = true;
  if (_analyzeBtn) { _analyzeBtn.disabled = true; _analyzeBtn.textContent = 'Analyzing...'; }

  const _restoreInput = () => {
    if (_urlInput) _urlInput.readOnly = false;
    if (_analyzeBtn) { _analyzeBtn.disabled = false; _analyzeBtn.textContent = 'Analyze PR'; }
  };

  showStreamLog();

  return new Promise((resolve, reject) => {
    let resolvedReport = null;

    fetch(`${API_BASE}/api/analyze/github`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_url: prUrl }),
    }).then(async (resp) => {
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail ?? `Request failed (${resp.status})`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      const pump = async () => {
        const { done, value } = await reader.read();
        if (done) {
          hideStreamLog();
          setLoading(false);
          _restoreInput();
          if (resolvedReport) {
            finalizeStreamSteps(resolvedReport);
            renderReport(resolvedReport);
            resolve(resolvedReport);
          } else {
            reject(new Error('No report received'));
          }
          return;
        }

        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() ?? '';

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(part.slice(6));

            if (data.type === 'stage') {
              const label = STAGE_LABELS[data.stage];
              if (label) renderStreamStep(label);
            } else if (data.type === 'result') {
              resolvedReport = data.report;
              currentReportId = data.report_id || null;
            } else if (data.type === 'error') {
              hideStreamLog();
              showError(data.message);
              setLoading(false);
              _restoreInput();
              reject(new Error(data.message));
              return;
            }
          } catch (_) { /* ignore malformed chunks */ }
        }
        pump();
      };

      pump();
    }).catch((err) => {
      hideStreamLog();
      showError(err.message);
      setLoading(false);
      _restoreInput();
      reject(err);
    });
  });
}


// ── Input mode toggle ──────────────────────────────────────────────
function toggleInputMode(mode) {
  const diffContainer = document.getElementById('diff-container');
  const urlPanel = document.getElementById('github-url-panel');
  const githubTab = document.getElementById('mode-url-btn');
  const diffTab = document.getElementById('mode-diff-btn');

  if (mode === 'url') {
    if (urlPanel) urlPanel.style.display = 'block';
    if (diffContainer) diffContainer.style.display = 'none';
    githubTab?.classList.add('active');
    diffTab?.classList.remove('active');
  } else {
    if (urlPanel) urlPanel.style.display = 'none';
    if (diffContainer) diffContainer.style.display = 'block';
    diffTab?.classList.add('active');
    githubTab?.classList.remove('active');
  }
  sessionStorage.setItem('inputMode', mode);
}

function _applyInputMode(mode) {
  toggleInputMode(mode);
}


// ── Custom PR modal analysis ───────────────────────────────────────
// Override runCustomAnalysis to handle both URL and diff modes
async function runCustomAnalysis() {
  const mode = sessionStorage.getItem('inputMode') || 'url';

  if (mode === 'url') {
    const prUrl = document.getElementById('modal-pr-url-input')?.value?.trim();
    if (!prUrl) {
      showWarning(document.getElementById('modal-pr-url-input'), 'Enter a GitHub PR URL first.');
      return;
    }
    document.getElementById('custom-modal').style.display = 'none';
    setLoading(true);
    resetUI();
    if (prTitleEl) prTitleEl.textContent = prUrl;
    analysisStartTime = Date.now();
    try {
      await streamGithubAnalysis(prUrl);
    } catch (err) {
      showError(err.message);
      setLoading(false);
    }
  } else {
    const diff = document.getElementById('diff-input')?.value?.trim();
    if (!diff) {
      showWarning(document.getElementById('diff-input'), 'Paste a unified diff first.');
      return;
    }
    document.getElementById('custom-modal').style.display = 'none';
    setLoading(true);
    resetUI();
    currentDiff = diff;
    DiffViewer.renderDiff('diff-container', diff, []);
    if (prTitleEl) prTitleEl.textContent = 'Custom PR';
    analysisStartTime = Date.now();
    try {
      await streamAnalysis(diff, 'demo_repo', 'Custom PR');
    } catch (err) {
      showError(err.message);
      setLoading(false);
    }
  }
}


// ── Share link ─────────────────────────────────────────────────────
function showShareBar(reportId) {
  const bar = document.getElementById('share-bar');
  if (!bar || !reportId) return;
  bar.style.display = 'flex';
}

function copyShareLink() {
  const btn = document.getElementById('copy-link-btn');
  if (!currentReportId) return;
  const url = `${window.location.origin}${window.location.pathname}?report=${currentReportId}`;
  navigator.clipboard.writeText(url).then(() => {
    if (btn) {
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = 'Copy link'; }, 2000);
    }
  }).catch(() => {
    if (btn) btn.textContent = 'Copy failed';
  });
}


// ── Context stats ──────────────────────────────────────────────────
function showContextStats(stats) {
  const bar = document.getElementById('context-stats-bar');
  if (!bar || !stats) return;
  bar.style.display = 'flex';
  bar.innerHTML = [
    `<span class="ctx-pill">${stats.files_in_repo} repo files</span>`,
    `<span class="ctx-pill">${stats.files_sent_to_model} sent to model</span>`,
    `<span class="ctx-pill">${(stats.chars_sent / 1000).toFixed(0)}k chars</span>`,
    `<span class="ctx-pill">${stats.budget_used_pct}% budget</span>`,
  ].join('');
}


// ── Shared report deep-link ────────────────────────────────────────
async function loadSharedReport(reportId) {
  try {
    const resp = await fetch(`${API_BASE}/api/report/${encodeURIComponent(reportId)}`);
    if (!resp.ok) return;
    const report = await resp.json();
    currentReportId = reportId;
    renderReport(report);
    showShareBar(reportId);
    if (prTitleEl && report.pr_title) prTitleEl.textContent = report.pr_title;
  } catch (_) { /* silently ignore */ }
}
