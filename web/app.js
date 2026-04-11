// Counterplan — CEGIS Assembly Planning Viewer
// Vanilla JS, no dependencies. Loads pre-computed JSON traces.

const COLORS = {
  bg: '#1A1D23', surface: '#22262E', fg: '#D8DEE9',
  accent: '#7BA4C7', terracotta: '#D97757', success: '#8FBCA3',
  error: '#BF616A', muted: '#6B7894', ground: '#3B4048',
};

// ── State ──
let trace = null;
let currentFrame = 0;
let framePlan = [];
let playing = false;
let playInterval = null;

// ── DOM refs ──
const canvas = document.getElementById('canvas');
const blockGroup = document.getElementById('block-group');
const arrowGroup = document.getElementById('arrow-group');
const groundGroup = document.getElementById('ground-group');
const statusText = document.getElementById('status-text');
const roundLabel = document.getElementById('round-label');
const sequenceDisplay = document.getElementById('sequence-display');
const constraintsList = document.getElementById('constraints-list');
const resultDisplay = document.getElementById('result-display');
const timelineProgress = document.getElementById('timeline-progress');
const frameCounter = document.getElementById('frame-counter');
const traceSelect = document.getElementById('trace-select');
const btnPrev = document.getElementById('btn-prev');
const btnPlay = document.getElementById('btn-play');
const btnNext = document.getElementById('btn-next');
const timelineBar = document.getElementById('timeline-bar');

// ── Coordinate transform ──
let xScale = 1, yScale = 1, xOffset = 0, yOffset = 0;
const SVG_W = 800, SVG_H = 600;
const MARGIN = 60;

function computeTransform(blocks, groundY) {
  let minX = Infinity, maxX = -Infinity, minY = groundY, maxY = -Infinity;
  for (const b of blocks) {
    for (const [x, y] of b.vertices) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  const w = maxX - minX || 1;
  const h = maxY - minY || 1;
  const scaleX = (SVG_W - 2 * MARGIN) / w;
  const scaleY = (SVG_H - 2 * MARGIN) / h;
  const scale = Math.min(scaleX, scaleY);
  xScale = scale; yScale = -scale; // flip Y
  xOffset = MARGIN + ((SVG_W - 2 * MARGIN) - w * scale) / 2 - minX * scale;
  yOffset = SVG_H - MARGIN + minY * scale;
}

function toSVG(x, y) {
  return [xOffset + x * xScale, yOffset + y * yScale];
}

function pointsToSVG(vertices) {
  return vertices.map(([x, y]) => toSVG(x, y).join(',')).join(' ');
}

// ── Rendering ──
function renderGround(groundY) {
  groundGroup.innerHTML = '';
  const [x1, y1] = toSVG(-100, groundY);
  const [x2, y2] = toSVG(100, groundY - 1);
  const rect = svgEl('rect', {
    x: 0, y: y1, width: SVG_W, height: SVG_H - y1,
    class: 'ground-rect',
  });
  groundGroup.appendChild(rect);
}

function renderBlocks(blocks, states) {
  blockGroup.innerHTML = '';
  // Add arrowhead marker
  const defs = canvas.querySelector('defs');
  if (!defs.querySelector('#arrowhead')) {
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'arrowhead');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('refX', '8');
    marker.setAttribute('refY', '3');
    marker.setAttribute('orient', 'auto');
    const path = svgEl('path', { d: 'M0,0 L8,3 L0,6 Z', fill: COLORS.terracotta });
    marker.appendChild(path);
    defs.appendChild(marker);
  }

  for (const block of blocks) {
    const state = states[block.id] || 'ghost';
    const points = pointsToSVG(block.vertices);

    const poly = svgEl('polygon', {
      points,
      class: `block-${state}`,
    });

    // Offset animation for active blocks
    if (state === 'active' && states._activeOffset) {
      const offset = states._activeOffset;
      const shifted = block.vertices.map(([x, y]) => [x, y + offset]);
      poly.setAttribute('points', pointsToSVG(shifted));
    }

    blockGroup.appendChild(poly);

    // Label
    const cx = block.centroid[0], cy = block.centroid[1];
    let labelY = cy;
    if (state === 'active' && states._activeOffset) labelY += states._activeOffset;
    const [sx, sy] = toSVG(cx, labelY);
    if (state !== 'ghost') {
      const label = svgEl('text', { x: sx, y: sy, class: 'block-label' });
      label.textContent = block.id;
      blockGroup.appendChild(label);
    }
  }
}

function renderConstraintArrows(blocks, constraints, activeConstraints) {
  arrowGroup.innerHTML = '';
  const blockMap = {};
  for (const b of blocks) blockMap[b.id] = b;

  for (const { before, after } of constraints) {
    const bBefore = blockMap[before], bAfter = blockMap[after];
    if (!bBefore || !bAfter) continue;
    const [x1, y1] = toSVG(bBefore.centroid[0], bBefore.centroid[1]);
    const [x2, y2] = toSVG(bAfter.centroid[0], bAfter.centroid[1]);
    const isActive = activeConstraints.some(c => c.before === before && c.after === after);
    const line = svgEl('line', {
      x1, y1, x2, y2,
      class: `constraint-arrow${isActive ? ' visible' : ''}`,
      style: isActive ? '' : 'opacity: 0.25',
    });
    arrowGroup.appendChild(line);
  }
}

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// ── Frame plan ──
function buildFramePlan(trace) {
  const plan = [];
  const FPS = 12;
  const PROPOSE = Math.round(0.8 * FPS);
  const PLACE = Math.round(0.5 * FPS);
  const FAIL = Math.round(0.6 * FPS);
  const LEARN = Math.round(0.8 * FPS);
  const REWIND = Math.round(0.5 * FPS);
  const SUCCESS = Math.round(1.2 * FPS);
  const PAUSE = Math.round(0.2 * FPS);

  for (let ri = 0; ri < trace.rounds.length; ri++) {
    const rd = trace.rounds[ri];
    const nSteps = rd.failure_step !== null ? rd.failure_step : rd.candidate.length;

    for (let f = 0; f < PROPOSE; f++)
      plan.push({ phase: 'propose', round: ri, t: f / PROPOSE, step: -1 });

    for (let s = 0; s < nSteps; s++)
      for (let f = 0; f < PLACE; f++)
        plan.push({ phase: 'place', round: ri, t: f / PLACE, step: s });

    if (rd.failure_step !== null) {
      for (let f = 0; f < FAIL; f++)
        plan.push({ phase: 'fail', round: ri, t: f / FAIL, step: rd.failure_step });
      for (let f = 0; f < LEARN; f++)
        plan.push({ phase: 'learn', round: ri, t: f / LEARN, step: rd.failure_step });
      for (let f = 0; f < REWIND; f++)
        plan.push({ phase: 'rewind', round: ri, t: f / REWIND, step: nSteps });
      for (let f = 0; f < PAUSE; f++)
        plan.push({ phase: 'pause', round: ri, t: 0, step: 0 });
    } else {
      for (let s = nSteps; s < rd.candidate.length; s++)
        for (let f = 0; f < PLACE; f++)
          plan.push({ phase: 'place', round: ri, t: f / PLACE, step: s });
      for (let f = 0; f < SUCCESS; f++)
        plan.push({ phase: 'success', round: ri, t: f / SUCCESS, step: rd.candidate.length });
    }
  }
  return plan;
}

function renderFrame(idx) {
  if (!trace || idx >= framePlan.length) return;
  const frame = framePlan[idx];
  const rd = trace.rounds[frame.round];
  const blocks = trace.structure.blocks;

  // Build block states
  const states = {};
  const placedBefore = frame.step > 0 ? rd.candidate.slice(0, frame.step) : [];

  if (frame.phase === 'propose') {
    for (const b of blocks) states[b.id] = 'ghost';
  } else if (frame.phase === 'place') {
    for (const b of blocks) {
      if (placedBefore.includes(b.id)) states[b.id] = 'placed';
      else if (b.id === rd.candidate[frame.step]) {
        states[b.id] = 'active';
        states._activeOffset = (1 - frame.t) * 0.4;
      }
      else states[b.id] = 'ghost';
    }
  } else if (frame.phase === 'fail') {
    for (const b of blocks) {
      if (placedBefore.includes(b.id)) states[b.id] = 'placed';
      else if (b.id === rd.candidate[frame.step]) {
        const pulse = Math.abs(Math.sin(frame.t * 3 * Math.PI));
        states[b.id] = pulse > 0.5 ? 'failed' : 'ghost';
      }
      else states[b.id] = 'ghost';
    }
  } else if (frame.phase === 'learn') {
    for (const b of blocks) {
      if (placedBefore.includes(b.id)) states[b.id] = 'placed';
      else if (b.id === rd.candidate[frame.step]) states[b.id] = 'failed';
      else states[b.id] = 'ghost';
    }
  } else if (frame.phase === 'rewind') {
    const n = Math.round(frame.step * (1 - frame.t));
    const visible = rd.candidate.slice(0, n);
    for (const b of blocks) states[b.id] = visible.includes(b.id) ? 'placed' : 'ghost';
  } else if (frame.phase === 'pause') {
    for (const b of blocks) states[b.id] = 'ghost';
  } else if (frame.phase === 'success') {
    for (const b of blocks) states[b.id] = 'placed';
  }

  renderBlocks(blocks, states);

  // Constraints
  const allConstraints = [];
  for (let i = 0; i <= frame.round; i++) {
    for (const c of trace.rounds[i].constraints_learned)
      allConstraints.push(c);
  }
  const activeConstraints = frame.phase === 'learn' ? rd.constraints_learned : [];
  renderConstraintArrows(blocks, allConstraints, activeConstraints);

  // Status
  const currentBlock = frame.step >= 0 ? rd.candidate[frame.step] : '?';
  const phaseLabel = {
    propose: 'Proposing sequence...',
    place: `Placing block ${currentBlock}`,
    fail: `Block ${currentBlock} UNSTABLE`,
    learn: 'Learning constraints',
    rewind: 'Rewinding...',
    pause: '',
    success: 'Assembly sequence found',
  }[frame.phase];
  statusText.textContent = `Round ${frame.round + 1} \u2014 ${phaseLabel}`;
  statusText.style.color = frame.phase === 'fail' ? COLORS.error :
                            frame.phase === 'success' ? COLORS.success :
                            frame.phase === 'learn' ? COLORS.terracotta : COLORS.muted;

  // Info panel
  roundLabel.textContent = `Round ${frame.round + 1} / ${trace.rounds.length}`;
  sequenceDisplay.textContent = rd.candidate.join(' ');

  constraintsList.innerHTML = '';
  for (const c of allConstraints) {
    const div = document.createElement('div');
    div.className = 'constraint-item' +
      (activeConstraints.some(ac => ac.before === c.before && ac.after === c.after) ? ' constraint-new' : '');
    div.textContent = `${c.before} \u2192 ${c.after}`;
    constraintsList.appendChild(div);
  }

  const rClass = trace.result.feasible ? 'result-feasible' : 'result-infeasible';
  resultDisplay.innerHTML = `<span class="${rClass}">${trace.result.feasible ? 'FEASIBLE' : 'INFEASIBLE'}</span>`;
  if (trace.result.sequence) {
    resultDisplay.innerHTML += `<br><span class="mono" style="color:${COLORS.muted}">${trace.result.sequence.join(' ')}</span>`;
  }

  // Timeline
  const progress = idx / Math.max(framePlan.length - 1, 1) * 100;
  timelineProgress.style.width = `${progress}%`;
  frameCounter.textContent = `${idx + 1} / ${framePlan.length}`;
}

// ── Controls ──
function setFrame(idx) {
  currentFrame = Math.max(0, Math.min(idx, framePlan.length - 1));
  renderFrame(currentFrame);
}

function togglePlay() {
  if (playing) {
    clearInterval(playInterval);
    playing = false;
    btnPlay.textContent = '\u25B6';
  } else {
    playing = true;
    btnPlay.textContent = '\u23F8';
    if (currentFrame >= framePlan.length - 1) currentFrame = 0;
    playInterval = setInterval(() => {
      if (currentFrame >= framePlan.length - 1) { togglePlay(); return; }
      setFrame(currentFrame + 1);
    }, 83); // ~12fps
  }
}

btnPrev.addEventListener('click', () => setFrame(currentFrame - 1));
btnNext.addEventListener('click', () => setFrame(currentFrame + 1));
btnPlay.addEventListener('click', togglePlay);

document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft') setFrame(currentFrame - 1);
  else if (e.key === 'ArrowRight') setFrame(currentFrame + 1);
  else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
});

timelineBar.addEventListener('click', (e) => {
  const rect = timelineBar.getBoundingClientRect();
  const frac = (e.clientX - rect.left) / rect.width;
  setFrame(Math.round(frac * (framePlan.length - 1)));
});

// ── Trace loading ──
async function loadTrace(name) {
  if (playing) togglePlay();
  try {
    const resp = await fetch(`data/${name}.json`);
    trace = await resp.json();
    computeTransform(trace.structure.blocks, trace.structure.ground_y);
    renderGround(trace.structure.ground_y);
    framePlan = buildFramePlan(trace);
    currentFrame = 0;
    renderFrame(0);
    statusText.textContent = `Loaded: ${trace.name || name}`;
  } catch (e) {
    statusText.textContent = `Error loading trace: ${e.message}`;
  }
}

traceSelect.addEventListener('change', () => loadTrace(traceSelect.value));

// ── Init ──
loadTrace('post_and_lintel');
