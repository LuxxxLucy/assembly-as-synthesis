// counterplan — 3D CEGIS replay viewer.
// Single consumer of the trace JSON. No algorithm knowledge lives here.
// Style: stacking-game vibe (each block drops into place, failures fall away).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── Palette (matches style.css) ──
const COLORS = {
  bg: 0x1A1D23,
  ground: 0x2C313A,
  placed: 0x7BA4C7,
  active: 0xD97757,
  failed: 0xBF616A,
  success: 0x8FBCA3,
  edge: 0x1A1D23,
  ghost: 0x454B57,
  arrowStability: 0xD97757,
  arrowKinematic: 0xC9A87C,
  arrowLanding:   0xA9B0BC,
};

const DEFAULT_DEPTH = 1.0;
const DROP_HEIGHT = 6.0;   // how far above target the active block starts
const GRAVITY = 9.81;

// ── Global state ──
let scene, camera, renderer, controls;
let rootGroup;              // holds block meshes + arrows (centered + flipped)
let trace = null;
let framePlan = [];
let currentFrame = 0;
let playing = false;
let lastTick = 0;
let blockMeshes = {};       // id -> { group, body, edges, basePos, depth }
let arrowMeshes = [];
let fallingBlocks = [];     // blocks that "fail" and tumble off screen
let failPulseT = 0;

// ── DOM ──
const $ = (id) => document.getElementById(id);
const canvasMount  = $('three-canvas');
const statusText   = $('status-text');
const roundLabel   = $('round-label');
const sequenceDisp = $('sequence-display');
const constraintsList = $('constraints-list');
const resultDisplay = $('result-display');
const timelineProg = $('timeline-progress');
const frameCounter = $('frame-counter');
const traceSelect  = $('trace-select');
const btnPrev = $('btn-prev');
const btnPlay = $('btn-play');
const btnNext = $('btn-next');
const timelineBar = $('timeline-bar');

// ── Scene setup ──
function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(COLORS.bg);
  scene.fog = new THREE.Fog(COLORS.bg, 18, 55);

  const w = canvasMount.clientWidth;
  const h = canvasMount.clientHeight;
  camera = new THREE.PerspectiveCamera(28, w / h, 0.1, 200);
  camera.position.set(10, 8, 12);
  camera.lookAt(0, 2, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(w, h);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  canvasMount.appendChild(renderer.domElement);

  // Light — warm key + cool fill + soft ambient.
  const key = new THREE.DirectionalLight(0xffe8d0, 0.9);
  key.position.set(6, 12, 8);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -10; key.shadow.camera.right = 10;
  key.shadow.camera.top = 10;   key.shadow.camera.bottom = -10;
  key.shadow.camera.near = 0.5; key.shadow.camera.far = 40;
  key.shadow.bias = -0.0006;
  scene.add(key);

  const fill = new THREE.DirectionalLight(0x6C7A8F, 0.35);
  fill.position.set(-8, 5, -4);
  scene.add(fill);

  scene.add(new THREE.AmbientLight(0xffffff, 0.18));

  // Ground.
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(60, 60),
    new THREE.MeshStandardMaterial({ color: COLORS.ground, roughness: 1.0, metalness: 0 }),
  );
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  // Subtle grid.
  const grid = new THREE.GridHelper(60, 30, 0x333944, 0x2A2F38);
  grid.position.y = 0.002;
  scene.add(grid);

  rootGroup = new THREE.Group();
  scene.add(rootGroup);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.minPolarAngle = 0.2;
  controls.maxPolarAngle = Math.PI / 2 - 0.08;
  controls.minDistance = 6;
  controls.maxDistance = 30;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 1.5, 0);

  window.addEventListener('resize', onResize);
}

function onResize() {
  const w = canvasMount.clientWidth;
  const h = canvasMount.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

// ── Block factory ──
// A block in the trace is a 2D polygon (x, y=up). We extrude it along z (depth)
// and then map trace (x, y) → world (x, y) with y-up. Depth is placed so the
// block is centered on z=0.
function makeBlock(blockData) {
  const shape = new THREE.Shape();
  const verts = blockData.vertices;
  shape.moveTo(verts[0][0], verts[0][1]);
  for (let i = 1; i < verts.length; i++) shape.lineTo(verts[i][0], verts[i][1]);
  shape.closePath();

  const depth = blockData.depth ?? DEFAULT_DEPTH;
  const geom = new THREE.ExtrudeGeometry(shape, {
    depth, bevelEnabled: false, curveSegments: 4,
  });
  // ExtrudeGeometry builds in +z. Offset so block is centered on z=0.
  geom.translate(0, 0, -depth / 2);
  geom.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({
    color: COLORS.placed,
    roughness: 0.65,
    metalness: 0.0,
    flatShading: true,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });

  const mesh = new THREE.Mesh(geom, mat);
  mesh.castShadow = true;
  mesh.receiveShadow = true;

  const edgeGeom = new THREE.EdgesGeometry(geom, 20);
  const edges = new THREE.LineSegments(
    edgeGeom,
    new THREE.LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: 0.7 }),
  );

  const group = new THREE.Group();
  group.add(mesh);
  group.add(edges);

  return { group, mesh, edges, material: mat, depth, blockData };
}

// ── Build block meshes for current trace ──
function buildBlocks() {
  // Clear
  while (rootGroup.children.length) {
    const c = rootGroup.children[0];
    rootGroup.remove(c);
    c.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose?.();
    });
  }
  blockMeshes = {};
  arrowMeshes = [];
  fallingBlocks = [];

  // Recentre: translate so (x,y) min is balanced
  const ex = trace.structure.extents;
  const cx = (ex.min_x + ex.max_x) / 2;

  for (const b of trace.structure.blocks) {
    const made = makeBlock(b);
    made.group.position.set(-cx, 0, 0); // base origin, block added at own coords
    // The shape is built in the block's local frame; we need to translate it
    // so the scene is centred. We've moved the group; individual block coords
    // remain unchanged below.
    rootGroup.add(made.group);
    made.basePos = made.group.position.clone();
    blockMeshes[b.id] = made;
  }

  // Scale camera zoom to fit
  const spanX = ex.max_x - ex.min_x;
  const spanY = ex.max_y - ex.min_y;
  const fit = Math.max(spanX, spanY) * 1.4 + 3;
  camera.position.set(fit * 0.8, fit * 0.75, fit);
  controls.target.set(0, spanY / 2, 0);
  controls.update();
}

// ── Arrow factory (precedence constraints) ──
function makeArrow(fromPt, toPt, color) {
  const a = new THREE.Vector3(fromPt.x, fromPt.y, fromPt.z);
  const b = new THREE.Vector3(toPt.x, toPt.y, toPt.z);
  const mid = a.clone().lerp(b, 0.5);
  mid.y += a.distanceTo(b) * 0.25 + 0.3;
  const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 16, 0.04, 6, false),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.75 }),
  );
  // arrowhead
  const tangent = curve.getTangent(1).normalize();
  const head = new THREE.Mesh(
    new THREE.ConeGeometry(0.1, 0.22, 10),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 }),
  );
  head.position.copy(b);
  head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent);
  const g = new THREE.Group();
  g.add(tube);
  g.add(head);
  return g;
}

function arrowColor(source) {
  if (source === 'kinematic') return COLORS.arrowKinematic;
  if (source === 'landing')   return COLORS.arrowLanding;
  return COLORS.arrowStability;
}

function rebuildArrows(constraints, active) {
  for (const a of arrowMeshes) rootGroup.remove(a);
  arrowMeshes = [];
  for (const c of constraints) {
    const bA = blockMeshes[c.before];
    const bB = blockMeshes[c.after];
    if (!bA || !bB) continue;
    const centroidA = bA.blockData.centroid;
    const centroidB = bB.blockData.centroid;
    const p1 = new THREE.Vector3(centroidA[0] + bA.basePos.x, centroidA[1], 0);
    const p2 = new THREE.Vector3(centroidB[0] + bB.basePos.x, centroidB[1], 0);
    const isActive = active.some(ac => ac.before === c.before && ac.after === c.after);
    const color = arrowColor(c.source);
    const arrow = makeArrow(p1, p2, color);
    if (!isActive) {
      arrow.traverse((o) => { if (o.material) o.material.opacity = 0.22; });
    }
    rootGroup.add(arrow);
    arrowMeshes.push(arrow);
  }
}

// ── Frame plan ──
// Each round expands into phases (propose → place… → fail/success → rewind).
const PHASE_DURATION = {
  propose: 0.6, place: 0.55, fail: 0.9, learn: 0.7,
  fall: 1.1, rewind: 0.5, pause: 0.3, success: 1.4,
};

function buildFramePlan() {
  const FPS = 30;
  const plan = [];
  for (let ri = 0; ri < trace.rounds.length; ri++) {
    const rd = trace.rounds[ri];
    const nSteps = rd.failure_step !== null ? rd.failure_step : rd.candidate.length;

    pushPhase(plan, 'propose', ri, -1, PHASE_DURATION.propose, FPS);
    for (let s = 0; s < nSteps; s++) {
      pushPhase(plan, 'place', ri, s, PHASE_DURATION.place, FPS);
    }
    if (rd.failure_step !== null) {
      pushPhase(plan, 'fail', ri, rd.failure_step, PHASE_DURATION.fail, FPS);
      pushPhase(plan, 'learn', ri, rd.failure_step, PHASE_DURATION.learn, FPS);
      pushPhase(plan, 'fall', ri, rd.failure_step, PHASE_DURATION.fall, FPS);
      pushPhase(plan, 'rewind', ri, nSteps, PHASE_DURATION.rewind, FPS);
      pushPhase(plan, 'pause', ri, 0, PHASE_DURATION.pause, FPS);
    } else {
      for (let s = nSteps; s < rd.candidate.length; s++) {
        pushPhase(plan, 'place', ri, s, PHASE_DURATION.place, FPS);
      }
      pushPhase(plan, 'success', ri, rd.candidate.length, PHASE_DURATION.success, FPS);
    }
  }
  return plan;
}

function pushPhase(plan, phase, round, step, seconds, fps) {
  const n = Math.max(1, Math.round(seconds * fps));
  for (let i = 0; i < n; i++) plan.push({ phase, round, step, t: i / n });
}

// ── Easing ──
const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);
const easeInCubic  = (t) => t * t * t;

// ── Render a given frame ──
function renderFrame(idx) {
  if (!trace) return;
  const frame = framePlan[idx];
  if (!frame) return;

  const rd = trace.rounds[frame.round];
  const placedIds = frame.step > 0 ? rd.candidate.slice(0, frame.step) : [];
  const activeId = frame.step >= 0 && frame.step < rd.candidate.length ? rd.candidate[frame.step] : null;

  // Reset all blocks to hidden/ghost at base positions unless otherwise set.
  for (const id in blockMeshes) {
    const m = blockMeshes[id];
    m.group.visible = true;
    m.group.position.copy(m.basePos);
    m.group.rotation.set(0, 0, 0);
    setBlockState(m, 'ghost');
  }

  // Placed so far → solid steel-blue.
  for (const id of placedIds) setBlockState(blockMeshes[id], 'placed');

  // Phase-specific behavior for the active block.
  if (frame.phase === 'propose') {
    // Ghost all blocks (already done).
    for (const id of rd.candidate) setBlockState(blockMeshes[id], 'ghost');
  } else if (frame.phase === 'place' && activeId !== null) {
    // Drop-in animation: start high, descend to base.
    const m = blockMeshes[activeId];
    setBlockState(m, 'active');
    const fallT = easeOutCubic(frame.t);
    m.group.position.y = m.basePos.y + DROP_HEIGHT * (1 - fallT);
    m.group.position.x = m.basePos.x; m.group.position.z = m.basePos.z;
  } else if (frame.phase === 'fail' && activeId !== null) {
    const m = blockMeshes[activeId];
    setBlockState(m, 'failed');
    // Suspended at target, pulsing + small shake
    const shake = 0.04 * Math.sin(frame.t * 28) * (1 - frame.t);
    m.group.position.x = m.basePos.x + shake;
    m.group.position.y = m.basePos.y;
  } else if (frame.phase === 'learn' && activeId !== null) {
    const m = blockMeshes[activeId];
    setBlockState(m, 'failed');
  } else if (frame.phase === 'fall' && activeId !== null) {
    // Gravity: the failed block tumbles off. Apply gravity to y and a slight rotation.
    const m = blockMeshes[activeId];
    setBlockState(m, 'failed');
    const fallDist = 0.5 * GRAVITY * Math.pow(frame.t * 1.2, 2);
    m.group.position.y = m.basePos.y - fallDist;
    m.group.rotation.z = frame.t * 1.2;
    if (m.group.position.y < -6) m.group.visible = false;
  } else if (frame.phase === 'rewind') {
    // Fade placed blocks back to ghost in reverse order.
    const nVisible = Math.round(frame.step * (1 - frame.t));
    for (let i = nVisible; i < rd.candidate.length; i++) {
      setBlockState(blockMeshes[rd.candidate[i]], 'ghost');
    }
  } else if (frame.phase === 'pause') {
    for (const id of rd.candidate) setBlockState(blockMeshes[id], 'ghost');
  } else if (frame.phase === 'success') {
    for (const id of rd.candidate) setBlockState(blockMeshes[id], 'success');
  }

  // Constraint arrows (all learned so far; active round's new ones glow).
  const allConstraints = [];
  for (let i = 0; i <= frame.round; i++) {
    for (const c of trace.rounds[i].constraints_learned) allConstraints.push(c);
  }
  const activeConstraints = frame.phase === 'learn' ? rd.constraints_learned : [];
  rebuildArrows(allConstraints, activeConstraints);

  // Panel updates.
  updatePanel(frame, rd, allConstraints, activeConstraints);
}

function setBlockState(m, state) {
  if (!m) return;
  let color;
  switch (state) {
    case 'placed':  color = COLORS.placed;  break;
    case 'active':  color = COLORS.active;  break;
    case 'failed':  color = COLORS.failed;  break;
    case 'success': color = COLORS.success; break;
    default:        color = COLORS.ghost;   break;
  }
  m.material.color.setHex(color);
  m.material.opacity = (state === 'ghost') ? 0.18 : 1.0;
  m.material.transparent = (state === 'ghost');
  m.edges.material.opacity = (state === 'ghost') ? 0.12 : 0.75;
  m.edges.material.transparent = true;
  m.edges.visible = true;
}

function updatePanel(frame, rd, allConstraints, activeConstraints) {
  const currentBlock = frame.step >= 0 && frame.step < rd.candidate.length ? rd.candidate[frame.step] : '·';
  const phaseLabel = {
    propose: 'Proposing sequence…',
    place:   `Placing block ${currentBlock}`,
    fail:    `Block ${currentBlock} fails — ${rd.failed_verifier ?? 'verifier'}`,
    learn:   'Learning precedence',
    fall:    'Rejected — block falls away',
    rewind:  'Rewinding',
    pause:   '',
    success: 'Sequence complete',
  }[frame.phase] ?? '';
  statusText.textContent = `Round ${frame.round + 1} — ${phaseLabel}`;

  roundLabel.textContent = `Round ${frame.round + 1} / ${trace.rounds.length}`;
  sequenceDisp.textContent = rd.candidate.join(' ');

  constraintsList.innerHTML = '';
  for (const c of allConstraints) {
    const div = document.createElement('div');
    const isNew = activeConstraints.some(ac => ac.before === c.before && ac.after === c.after);
    div.className = 'constraint-item' + (isNew ? ' constraint-new' : '');
    const swatch = `<span class="swatch swatch-${c.source || 'stability'}"></span>`;
    div.innerHTML = `${swatch}${c.before} → ${c.after}`;
    constraintsList.appendChild(div);
  }

  const feasible = trace.result.feasible;
  resultDisplay.innerHTML = `<span class="${feasible ? 'result-feasible' : 'result-infeasible'}">${feasible ? 'FEASIBLE' : 'INFEASIBLE'}</span>`;
  if (trace.result.sequence) {
    resultDisplay.innerHTML += `<br><span class="mono" style="color:var(--fg-muted); font-size:0.8rem; font-weight:400;">${trace.result.sequence.join(' ')}</span>`;
  }

  timelineProg.style.width = `${(currentFrame / Math.max(1, framePlan.length - 1)) * 100}%`;
  frameCounter.textContent = `${currentFrame + 1} / ${framePlan.length}`;
}

// ── Main loop ──
function animate(now) {
  requestAnimationFrame(animate);
  const dt = (now - lastTick) / 1000;
  lastTick = now;
  controls.update();

  if (playing) {
    failPulseT += dt;
    // ~30 frames per second → advance 1 frame every 33ms.
    if (failPulseT > 1 / 30) {
      failPulseT = 0;
      if (currentFrame >= framePlan.length - 1) {
        togglePlay();
      } else {
        setFrame(currentFrame + 1);
      }
    }
  }
  renderer.render(scene, camera);
}

// ── Controls ──
function setFrame(idx) {
  currentFrame = Math.max(0, Math.min(idx, framePlan.length - 1));
  renderFrame(currentFrame);
}
function togglePlay() {
  playing = !playing;
  btnPlay.innerHTML = playing ? '&#10074;&#10074;' : '&#9654;';
  if (playing && currentFrame >= framePlan.length - 1) currentFrame = 0;
}
btnPrev.addEventListener('click', () => setFrame(currentFrame - 1));
btnNext.addEventListener('click', () => setFrame(currentFrame + 1));
btnPlay.addEventListener('click', togglePlay);
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft')  setFrame(currentFrame - 1);
  else if (e.key === 'ArrowRight') setFrame(currentFrame + 1);
  else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
});
timelineBar.addEventListener('click', (e) => {
  const r = timelineBar.getBoundingClientRect();
  setFrame(Math.round(((e.clientX - r.left) / r.width) * (framePlan.length - 1)));
});

// ── Trace loading ──
async function loadTrace(name) {
  if (playing) togglePlay();
  try {
    const resp = await fetch(`data/${name}.json`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    trace = await resp.json();
    buildBlocks();
    framePlan = buildFramePlan();
    currentFrame = 0;
    renderFrame(0);
    statusText.textContent = `Loaded ${trace.name ?? name}`;
  } catch (e) {
    statusText.textContent = `Error loading trace: ${e.message}`;
  }
}
traceSelect.addEventListener('change', () => loadTrace(traceSelect.value));

// ── Init ──
initScene();
requestAnimationFrame((t) => { lastTick = t; animate(t); });
loadTrace(traceSelect.value);
