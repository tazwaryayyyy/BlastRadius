/**
 * graph.js
 * D3 v7 force-directed graph for the blast radius visualization.
 *
 * Nodes = files. Edges = call relationships.
 * Color = risk level. Dashed = no test coverage. Size = changed file.
 */

/* global d3 */

const RISK_COLOR = {
  CRITICAL: '#ff4444',
  HIGH: '#ff8c00',
  MEDIUM: '#f0c040',
  LOW: '#40c080',
  CHANGED: '#44aaff',
  SAFE: '#2c3340',
};

const RISK_GLOW = {
  CRITICAL: 'rgba(255, 68, 68, 0.5)',
  HIGH: 'rgba(255, 140, 0, 0.4)',
  MEDIUM: 'rgba(240, 192, 64, 0.3)',
  LOW: 'rgba(64, 192, 128, 0.3)',
  CHANGED: 'rgba(68, 170, 255, 0.5)',
};

let svg = null;
let simulation = null;
let onNodeClickCb = null;

/**
 * Initialize the SVG canvas.
 * Call once on page load.
 */
function initGraph(containerId, onNodeClick) {
  onNodeClickCb = onNodeClick;
  const container = document.getElementById(containerId);
  if (!container) return;

  // Clean up previous instance
  d3.select(`#${containerId} svg`).remove();

  const { width, height } = container.getBoundingClientRect();

  svg = d3.select(`#${containerId}`)
    .append('svg')
    .attr('width', width)
    .attr('height', height);

  // Defs for filters
  const defs = svg.append('defs');

  // Glow filter for highlighted/critical nodes
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'CHANGED'].forEach((risk) => {
    const filter = defs.append('filter')
      .attr('id', `glow-${risk}`)
      .attr('x', '-50%').attr('y', '-50%')
      .attr('width', '200%').attr('height', '200%');

    filter.append('feGaussianBlur')
      .attr('in', 'SourceGraphic')
      .attr('stdDeviation', risk === 'CRITICAL' ? 4 : 3)
      .attr('result', 'blur');

    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'blur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');
  });

  // Arrow markers for edges
  ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'SAFE'].forEach((risk) => {
    defs.append('marker')
      .attr('id', `arrow-${risk}`)
      .attr('viewBox', '0 0 10 10')
      .attr('refX', 20).attr('refY', 5)
      .attr('markerWidth', 5).attr('markerHeight', 5)
      .attr('orient', 'auto-start-reverse')
      .append('path')
      .attr('d', 'M 0 0 L 10 5 L 0 10 z')
      .attr('fill', RISK_COLOR[risk])
      .attr('opacity', 0.5);
  });

  // Re-render on window resize
  window.addEventListener('resize', () => {
    const { width: w, height: h } = container.getBoundingClientRect();
    svg.attr('width', w).attr('height', h);
    if (simulation) {
      simulation.force('center', d3.forceCenter(w / 2, h / 2));
      simulation.alpha(0.3).restart();
    }
  });
}


/**
 * Build graph nodes and edges from a BlastRadiusReport.
 */
function buildGraphData(report) {
  const nodeMap = new Map();  // path → node
  const edges = [];

  // Add nodes from call chains
  report.call_chains.forEach((chain) => {
    chain.path.forEach((filePath, idx) => {
      const isChangedThisTime = report.changed_symbols.length > 0 && idx === 0;
      if (!nodeMap.has(filePath)) {
        nodeMap.set(filePath, {
          id: filePath,
          label: filePath.split('/').pop(),
          risk: isChangedThisTime ? 'CHANGED' : chain.risk,
          is_changed: isChangedThisTime,
          has_tests: chain.has_tests,
          chain_count: 1,
        });
      } else {
        const node = nodeMap.get(filePath);
        node.chain_count++;
        // Escalate risk if this chain is higher
        const riskOrder = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
        if (isChangedThisTime && !node.is_changed) {
          node.is_changed = true;
          node.risk = 'CHANGED';
        } else if (!node.is_changed &&
          riskOrder.indexOf(chain.risk) > riskOrder.indexOf(node.risk)) {
          node.risk = chain.risk;
          node.has_tests = node.has_tests && chain.has_tests;
        }
      }
    });

    // Add edges for this chain
    for (let i = 0; i < chain.path.length - 1; i++) {
      edges.push({
        source: chain.path[i],
        target: chain.path[i + 1],
        risk: chain.risk,
        chainId: chain.id,
      });
    }
  });

  return {
    nodes: Array.from(nodeMap.values()),
    links: edges,
  };
}


/**
 * Render the blast radius graph.
 * @param {object} report - BlastRadiusReport from the API
 */
function renderGraph(report) {
  if (!svg) return;
  const container = svg.node().parentElement;
  const W = container.clientWidth;
  const H = container.clientHeight;

  // Clear previous render
  svg.selectAll('*:not(defs)').remove();

  const { nodes, links } = buildGraphData(report);

  if (nodes.length === 0) return;

  // ── Simulation ─────────────────────────────────────────────────
  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links)
      .id((d) => d.id)
      .distance(110)
      .strength(0.6))
    .force('charge', d3.forceManyBody().strength(-280))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(32))
    .alphaDecay(0.025);


  // ── Edges ──────────────────────────────────────────────────────
  const link = svg.append('g').attr('class', 'links')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('class', 'link')
    .attr('stroke', (d) => RISK_COLOR[d.risk] || RISK_COLOR.SAFE)
    .attr('stroke-width', 1.5)
    .attr('marker-end', (d) => `url(#arrow-${d.risk})`);

  // ── Nodes ──────────────────────────────────────────────────────
  const node = svg.append('g').attr('class', 'nodes')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .attr('class', 'node')
    .call(drag(simulation))
    .on('click', (event, d) => {
      event.stopPropagation();
      highlightNode(d.id, nodes, links, node, link, report);
      if (onNodeClickCb) onNodeClickCb(d, report);
    });

  // Node radii and stroke per spec
  const BASE_RADIUS = 13; // px, default node
  const CHANGED_RADIUS = 18; // px, changed node
  const LABEL_DY = 22; // px, label offset
  const PULSE_BASE = 20; // px, pulse ring for normal
  const PULSE_CHANGED = 26; // px, pulse ring for changed

  // Node circle
  node.append('circle')
    .attr('r', (d) => d.is_changed ? CHANGED_RADIUS : BASE_RADIUS)
    .attr('fill', (d) => {
      // Use a subtle fill for all nodes, blue for changed
      if (d.is_changed) return 'rgba(68,170,255,0.13)';
      const color = RISK_COLOR[d.risk] || RISK_COLOR.SAFE;
      return `${color}18`;
    })
    .attr('stroke', (d) => RISK_COLOR[d.risk] || RISK_COLOR.SAFE)
    .attr('stroke-width', (d) => d.is_changed ? 2.5 : 1.7)
    .attr('stroke-dasharray', (d) => d.has_tests ? 'none' : '4 3')
    .attr('filter', (d) =>
      ['CRITICAL', 'CHANGED'].includes(d.risk) ? `url(#glow-${d.risk})` : 'none'
    );

  // Node label
  node.append('text')
    .text((d) => d.label.length > 18 ? d.label.slice(0, 16) + '…' : d.label)
    .attr('dy', LABEL_DY)
    .style('fill', (d) => RISK_COLOR[d.risk] || '#4a5060');

  // CRITICAL pulse ring (animated)
  node.filter((d) => d.risk === 'CRITICAL')
    .append('circle')
    .attr('class', 'pulse-ring')
    .attr('r', (d) => d.is_changed ? PULSE_CHANGED : PULSE_BASE)
    .attr('fill', 'none')
    .attr('stroke', '#ff4444')
    .attr('stroke-width', 1.5)
    .attr('opacity', 0.55)
    .call(addPulse);

  // Click canvas to reset
  svg.on('click', () => {
    resetHighlight(node, link);
    if (onNodeClickCb) onNodeClickCb(null, report);
  });

  // Tick
  simulation.on('tick', () => {
    link
      .attr('x1', (d) => d.source.x)
      .attr('y1', (d) => d.source.y)
      .attr('x2', (d) => d.target.x)
      .attr('y2', (d) => d.target.y);

    node.attr('transform', (d) => `translate(${d.x},${d.y})`);
  });
}


function addPulse(selection) {
  function repeat() {
    selection
      .attr('r', function (d) { return d.is_changed ? 26 : 20; })
      .attr('opacity', 0.55)
      .transition().duration(1200).ease(d3.easeSinOut)
      .attr('r', function (d) { return (d.is_changed ? 26 : 20) + 12; })
      .attr('opacity', 0)
      .on('end', repeat);
  }
  repeat();
}


function highlightNode(nodeId, nodes, links, nodeEl, linkEl, report) {
  // Find all chains touching this node
  const relevantChainIds = new Set(
    report.call_chains
      .filter((c) => c.path.includes(nodeId))
      .map((c) => c.id)
  );

  // Files in those chains
  const relevantFiles = new Set(
    report.call_chains
      .filter((c) => relevantChainIds.has(c.id))
      .flatMap((c) => c.path)
  );

  nodeEl.classed('dimmed', (d) => !relevantFiles.has(d.id));
  nodeEl.classed('highlighted', (d) => relevantFiles.has(d.id));

  linkEl.classed('dimmed', (d) => !relevantChainIds.has(d.chainId));
  linkEl.classed('highlighted', (d) => relevantChainIds.has(d.chainId));
}


function resetHighlight(nodeEl, linkEl) {
  nodeEl.classed('dimmed', false).classed('highlighted', false);
  linkEl.classed('dimmed', false).classed('highlighted', false);
}


function drag(sim) {
  return d3.drag()
    .on('start', (event, d) => {
      if (!event.active) sim.alphaTarget(0.3).restart();
      d.fx = d.x; d.fy = d.y;
    })
    .on('drag', (event, d) => {
      d.fx = event.x; d.fy = event.y;
    })
    .on('end', (event, d) => {
      if (!event.active) sim.alphaTarget(0);
      d.fx = null; d.fy = null;
    });
}


window.BlastGraph = { initGraph, renderGraph };
