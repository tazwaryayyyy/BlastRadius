/**
 * diff_viewer.js
 * Renders a unified diff in the left panel.
 * Colors lines by +/- and marks blast-entry lines with a gutter indicator.
 */

/**
 * Render a unified diff string into a container element.
 * @param {string} containerId
 * @param {string} diffText
 * @param {string[]} blastEntrySymbols - symbol names to highlight as blast entries
 */
function renderDiff(containerId, diffText, blastEntrySymbols = []) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '';

  const lines = diffText.split('\n');
  let currentFile = null;

  lines.forEach((line) => {
    // File header line (--- / +++)
    if (line.startsWith('---') || line.startsWith('+++')) {
      const path = line.replace(/^[+-]{3}\s+/, '').replace(/^[ab]\//, '').trim();
      if (path && path !== '/dev/null' && path !== currentFile) {
        currentFile = path;
        const header = document.createElement('div');
        header.className = 'diff-file-header';
        header.textContent = `📄 ${path}`;
        container.appendChild(header);
      }
      return;
    }

    // Hunk header
    if (line.startsWith('@@')) {
      const row = document.createElement('div');
      row.className = 'diff-line context';
      row.style.opacity = '0.4';
      row.innerHTML = `
        <div class="diff-gutter"></div>
        <div class="diff-sign" style="color:#4a5060"> </div>
        <div class="diff-content" style="color:#4a5060">${escapeHtml(line)}</div>
      `;
      container.appendChild(row);
      return;
    }

    // Normal diff lines
    let type = 'context';
    let sign = ' ';
    if (line.startsWith('+')) { type = 'added';   sign = '+'; }
    if (line.startsWith('-')) { type = 'removed';  sign = '-'; }

    const content = line.slice(1); // strip leading +/-/ 

    // Check if this line is a blast entry (references a changed symbol)
    const isBlastEntry = type !== 'context' && blastEntrySymbols.some((sym) =>
      content.includes(sym + '(') ||
      content.includes(sym + ' =') ||
      content.includes('exports.' + sym) ||
      content.includes('module.exports')
    );

    const row = document.createElement('div');
    row.className = `diff-line ${type}${isBlastEntry ? ' blast-entry' : ''}`;
    row.innerHTML = `
      <div class="diff-gutter"></div>
      <div class="diff-sign">${sign}</div>
      <div class="diff-content">${escapeHtml(content)}</div>
    `;
    container.appendChild(row);
  });
}


/**
 * Clear the diff container.
 */
function clearDiff(containerId) {
  const container = document.getElementById(containerId);
  if (container) container.innerHTML = '';
}


function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}


window.DiffViewer = { renderDiff, clearDiff };
