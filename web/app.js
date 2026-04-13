// counterplan — isometric cel-shaded 3D viewer.
// Style: Monument-Valley-esque ortho-isometric with inked outlines.
// Consumes the trace JSON produced by trace.py; no algorithm knowledge
// lives here.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ── Palette ─────────────────────────────────────────────────────────────
// Warm-cool pastel. Outline ink is near-black for crisp toon edges.
// Two palettes: the default cold/architectural one the standalone viewer
// was designed around, and a light "blog" palette that matches Tufte CSS's
// #fffff8 page background. The light palette is selected by the embed via
// `?theme=light`. Everything structural stays the same; only the colour
// constants change.
const PAL_DARK = {
  bg:       0x1C2030,
  ground:   0x2D3448,
  ink:      0x15181F,
  placed:   0x9FB0CC,   // dusty lavender
  active:   0xE8967A,   // coral
  failed:   0xC47286,   // muted rose
  success:  0x9DC9AB,   // sage mint
  ghost:    0x3A414F,
  arrowKinematic: 0xE0B888,
  arrowStability: 0xE8967A,
  arrowLanding:   0xB0B8C8,
  keyLight: 0xFFE8C8,
  fillLight:0x7A8FB0,
};
const PAL_LIGHT = {
  bg:       0xFFFFF8,   // Tufte cream
  ground:   0xE6E2D2,   // warm light stone
  ink:      0x3B3A36,   // Tufte body text
  placed:   0xB9C6DC,   // soft dusty blue
  active:   0xE1876A,   // warmer coral
  failed:   0xBC6478,   // muted rose
  success:  0x8DBBA0,   // sage mint
  ghost:    0xA8A8A2,
  arrowKinematic: 0xD9A267,
  arrowStability: 0xE1876A,
  arrowLanding:   0x9AA3AE,
  keyLight: 0xFFF2D8,
  fillLight:0xBCC4CE,
};
const PAL = (new URLSearchParams(location.search).get('theme') === 'light')
            ? PAL_LIGHT
            : PAL_DARK;
// Loop playback instead of stopping on the last frame. Default on; pass
// ?loop=0 to keep the animation stopped on the last frame.
const LOOP_PLAYBACK = new URLSearchParams(location.search).get('loop') !== '0';
// Suppress the precedence-arrow overlay — the blog embed wants the clean
// animation without the constraint-graph layer.
const SHOW_ARROWS   = new URLSearchParams(location.search).get('arrows') !== 'off';

const DEFAULT_DEPTH = 1.0;
const DROP_HEIGHT   = 6.0;
const GRAVITY       = 9.81;
// Plinth (ground) spans x,z in [-PLINTH_HALF, PLINTH_HALF], top at y=0.
// Failed blocks collide with it instead of clipping through.
const PLINTH_HALF   = 15;
const PLINTH_TOP_Y  = 0;

// ── Global state ────────────────────────────────────────────────────────
let scene, camera, renderer, controls;
let rootGroup, arrowGroup;
let previewRenderer, previewScene, previewCamera, previewRoot;
let trace = null;
let framePlan = [];
let currentFrame = 0;
let playing = false;
let lastTick = 0;
let frameAccum = 0;
let blockMeshes = {};  // id -> { group, body, outline, material, basePos, depth, blockData }
let centerOffset = new THREE.Vector3();

// ── DOM ────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const canvasMount     = $('three-canvas');
const statusText      = $('status-text');
const roundLabel      = $('round-label');
const sequenceDisp    = $('sequence-display');
const constraintsList = $('constraints-list');
const resultDisplay   = $('result-display');
const timelineProg    = $('timeline-progress');
const frameCounter    = $('frame-counter');
const traceSelect     = $('trace-select');
const btnPrev         = $('btn-prev');
const btnPlay         = $('btn-play');
const btnNext         = $('btn-next');
const timelineBar     = $('timeline-bar');

// ── Scene setup ─────────────────────────────────────────────────────────
function initScene() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(PAL.bg);

  const w = canvasMount.clientWidth;
  const h = canvasMount.clientHeight;
  const aspect = w / h;

  // Orthographic isometric, camera on the -X / +Z side so the structure's
  // principal face reads toward the right of the screen.
  const vs = 6;
  camera = new THREE.OrthographicCamera(-vs * aspect, vs * aspect, vs, -vs, -100, 100);
  camera.position.set(-14, 12, 14);
  camera.lookAt(0, 0, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  canvasMount.appendChild(renderer.domElement);

  // Lights — warm key + cool fill + ambient.
  const key = new THREE.DirectionalLight(PAL.keyLight, 1.0);
  key.position.set(8, 14, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -12; key.shadow.camera.right = 12;
  key.shadow.camera.top = 12;   key.shadow.camera.bottom = -12;
  key.shadow.camera.near = 0.5; key.shadow.camera.far = 50;
  key.shadow.bias = -0.0005;
  scene.add(key);

  const fill = new THREE.DirectionalLight(PAL.fillLight, 0.5);
  fill.position.set(-8, 6, -4);
  scene.add(fill);

  scene.add(new THREE.AmbientLight(0xffffff, 0.22));

  // Ground: raised plinth, not an infinite plane. Gives the scene a diorama feel.
  const ground = new THREE.Mesh(
    new THREE.BoxGeometry(30, 0.6, 30),
    new THREE.MeshLambertMaterial({ color: PAL.ground }),
  );
  ground.position.y = -0.3;
  ground.receiveShadow = true;
  scene.add(ground);

  // Thin ink edge around the plinth — subtle architectural rim.
  const groundEdge = new THREE.LineSegments(
    new THREE.EdgesGeometry(ground.geometry),
    new THREE.LineBasicMaterial({ color: PAL.ink, transparent: true, opacity: 0.55 }),
  );
  groundEdge.position.copy(ground.position);
  scene.add(groundEdge);

  rootGroup  = new THREE.Group();
  arrowGroup = new THREE.Group();
  scene.add(rootGroup);
  scene.add(arrowGroup);

  // Subtle user interaction — allow gentle orbit, snap to iso on release.
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enablePan = false;
  controls.enableZoom = false;          // locked ortho zoom; blockable but feels cleaner
  controls.minPolarAngle = 0.45;
  controls.maxPolarAngle = 1.05;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.6;
  controls.target.set(0, 1.2, 0);

  window.addEventListener('resize', onResize);
}

function onResize() {
  const w = canvasMount.clientWidth;
  const h = canvasMount.clientHeight;
  const aspect = w / h;
  const vs = camera.top;  // preserve zoom
  camera.left = -vs * aspect;
  camera.right = vs * aspect;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

// ── Block factory ───────────────────────────────────────────────────────
// Blocks are 2D polygons (x, y up). We extrude along z. The shape lives in
// its absolute coordinates; the group is translated by `centerOffset` to
// center the structure on the origin.
function makeBlock(blockData) {
  const verts = blockData.vertices;
  const [cx, cy] = blockData.centroid;
  // Build the shape in the block's own frame (centroid at local origin) so
  // rotation around the group pivots the block on its own centre, not on
  // the scene origin. Local vertices are also retained for rotation-aware
  // ground collision below.
  const localVerts = verts.map(([x, y]) => [x - cx, y - cy]);
  const shape = new THREE.Shape();
  shape.moveTo(localVerts[0][0], localVerts[0][1]);
  for (let i = 1; i < localVerts.length; i++) shape.lineTo(localVerts[i][0], localVerts[i][1]);
  shape.closePath();

  const depth = blockData.depth ?? DEFAULT_DEPTH;
  const geom = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 1 });
  geom.translate(0, 0, -depth / 2);
  geom.computeVertexNormals();

  // Body is opaque by default; setState() flips transparent on only when
  // it actually needs opacity < 1 (ghost / fade). When body and outline
  // share a centroid, making both transparent makes the transparent-pass
  // sort order ambiguous and the black outline hull can end up drawn on
  // top of the body.
  const material = new THREE.MeshLambertMaterial({
    color: PAL.placed,
  });

  const body = new THREE.Mesh(geom, material);
  body.castShadow = true;
  body.receiveShadow = true;
  body.renderOrder = 1;

  // Backface-hull ink outline — opaque with polygonOffset so the body
  // reliably wins the depth test regardless of driver tie-breaking.
  const outlineMat = new THREE.MeshBasicMaterial({
    color: PAL.ink,
    side: THREE.BackSide,
    polygonOffset: true,
    polygonOffsetFactor: 2,
    polygonOffsetUnits: 2,
  });
  const outline = new THREE.Mesh(geom, outlineMat);
  outline.scale.set(1.04, 1.04, 1.08);
  outline.renderOrder = 0;

  // Sharp edge lines layered on top — tightens the silhouette.
  const edgeGeom = new THREE.EdgesGeometry(geom, 30);
  const edges = new THREE.LineSegments(
    edgeGeom,
    new THREE.LineBasicMaterial({ color: PAL.ink }),
  );
  edges.renderOrder = 2;

  // Target-position ghost. Shares the edge geometry but is *not* a child
  // of the moving group — it stays at the block's basePos so the viewer
  // always sees where this block is supposed to land, even while the body
  // is mid-drop or tumbling. Rendered in a dashed line, shown only when
  // the body is not currently sitting on its target.
  const anchorMat = new THREE.LineDashedMaterial({
    color: PAL.active,
    dashSize: 0.14, gapSize: 0.1,
    transparent: true, opacity: 0.55,
  });
  const anchor = new THREE.LineSegments(edgeGeom, anchorMat);
  anchor.computeLineDistances();
  anchor.renderOrder = 3;
  anchor.visible = false;

  const group = new THREE.Group();
  group.add(outline);
  group.add(body);
  group.add(edges);

  return {
    group, body, outline, edges, material, outlineMat,
    anchor, anchorMat,
    depth, localVerts, blockData,
  };
}

function disposeBlock(m) {
  m.body.geometry.dispose();
  m.material.dispose();
  m.outlineMat.dispose();
  m.edges.geometry.dispose();
  m.edges.material.dispose();
  m.anchorMat.dispose();
}

function clearBlocks() {
  for (const id in blockMeshes) {
    rootGroup.remove(blockMeshes[id].group);
    rootGroup.remove(blockMeshes[id].anchor);
    disposeBlock(blockMeshes[id]);
  }
  blockMeshes = {};
  while (arrowGroup.children.length) {
    const c = arrowGroup.children[0];
    arrowGroup.remove(c);
    c.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose?.();
    });
  }
}

function buildBlocks() {
  clearBlocks();

  const ex = trace.structure.extents;
  centerOffset.set(-(ex.min_x + ex.max_x) / 2, 0, 0);

  for (const b of trace.structure.blocks) {
    const m = makeBlock(b);
    // Place the group at the block's centroid in world coords (shifted by
    // centerOffset). Children are centroid-local so rotation pivots here.
    m.group.position.set(b.centroid[0] + centerOffset.x, b.centroid[1], 0);
    m.basePos = m.group.position.clone();
    rootGroup.add(m.group);
    // The target-position ghost lives in the scene at basePos — not under
    // the block's moving group — so it stays put when the body animates.
    m.anchor.position.copy(m.basePos);
    rootGroup.add(m.anchor);
    blockMeshes[b.id] = m;
  }

  fitCamera();
}

function fitCamera() {
  // Tight iso-aware fit — same formula the preview panel uses so both
  // panels render blocks at the same on-screen size. Iso projection
  // stretches the extents ~1.2× vertically and ~1.15× horizontally;
  // compute the smaller ortho half-height that covers both projections.
  const ex = trace.structure.extents;
  const spanX = Math.max(1.5, ex.max_x - ex.min_x);
  const spanY = Math.max(1.5, ex.max_y - ex.min_y);
  const aspect = canvasMount.clientWidth / Math.max(1, canvasMount.clientHeight);
  const needY = (spanY * 1.0 + spanX * 0.35) / 2;
  const needX = (spanX * 1.0 + spanY * 0.35) / (2 * aspect);
  const vs = Math.max(needX, needY) * 1.15 + 0.25;
  camera.left = -vs * aspect; camera.right = vs * aspect;
  camera.top = vs; camera.bottom = -vs;
  camera.updateProjectionMatrix();
  controls.target.set(0, spanY * 0.45, 0);
  controls.update();
}

// ── Kinematic collision height ─────────────────────────────────────────
// For rounds that fail via the kinematic verifier, the placed block can't
// descend to its target because another block is already in its path. We
// stop the drop at the blocker's top + a small clearance and animate a
// "rejected" lift-away instead of a gravity tumble.
function computeKinematicStop(rd) {
  if (rd.failed_verifier !== 'kinematic' || rd.failure_step === null) return null;
  const steps = rd.steps || [];
  const failStep = steps[rd.failure_step];
  const kin = failStep?.verifiers?.find(v => v.verifier === 'kinematic');
  const blockers = kin?.diagnostics?.blockers;
  if (!blockers || !blockers.length) return null;

  let maxY = -Infinity;
  for (const bid of blockers) {
    const b = blockMeshes[bid];
    if (!b) continue;
    for (const [, ly] of b.localVerts) {
      const wy = b.basePos.y + ly;
      if (wy > maxY) maxY = wy;
    }
  }
  if (!Number.isFinite(maxY)) return null;

  const m = blockMeshes[rd.failed_block];
  if (!m) return null;
  let minLocalY = Infinity;
  for (const [, ly] of m.localVerts) if (ly < minLocalY) minLocalY = ly;

  const clearance = 0.04;
  return { stopGroupY: maxY + clearance - minLocalY, blockers };
}

// ── Constraint arrows ──────────────────────────────────────────────────
function arrowColor(source) {
  if (source === 'kinematic') return PAL.arrowKinematic;
  if (source === 'landing')   return PAL.arrowLanding;
  return PAL.arrowStability;
}

function makeArrow(from, to, color, active) {
  const a = from.clone();
  const b = to.clone();
  const mid = a.clone().lerp(b, 0.5);
  mid.y += a.distanceTo(b) * 0.35 + 0.4;
  const curve = new THREE.QuadraticBezierCurve3(a, mid, b);

  const tubeMat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: active ? 0.9 : 0.28,
  });
  const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, 0.045, 8, false), tubeMat);

  const headMat = new THREE.MeshBasicMaterial({
    color, transparent: true, opacity: active ? 1.0 : 0.35,
  });
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.12, 0.28, 10), headMat);
  const tangent = curve.getTangent(0.98).normalize();
  head.position.copy(b);
  head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent);

  const g = new THREE.Group();
  g.add(tube);
  g.add(head);
  return g;
}

function rebuildArrows(allConstraints, activeConstraints) {
  while (arrowGroup.children.length) {
    const c = arrowGroup.children[0];
    arrowGroup.remove(c);
    c.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose?.();
    });
  }
  for (const c of allConstraints) {
    const a = blockMeshes[c.before];
    const b = blockMeshes[c.after];
    if (!a || !b) continue;
    const p1 = new THREE.Vector3(a.blockData.centroid[0] + centerOffset.x, a.blockData.centroid[1], 0);
    const p2 = new THREE.Vector3(b.blockData.centroid[0] + centerOffset.x, b.blockData.centroid[1], 0);
    const isActive = activeConstraints.some(ac => ac.before === c.before && ac.after === c.after);
    arrowGroup.add(makeArrow(p1, p2, arrowColor(c.source), isActive));
  }
}

// ── Frame plan (phases → frames) ────────────────────────────────────────
const PHASE_DURATION = {
  propose: 0.4, place: 0.45, fail: 0.7, learn: 0.6,
  fall: 1.0,    rewind: 0.5, pause: 0.25, success: 1.4,
};

function buildFramePlan() {
  const FPS = 30;
  const plan = [];
  for (let ri = 0; ri < trace.rounds.length; ri++) {
    const rd = trace.rounds[ri];
    const nSteps = rd.failure_step !== null ? rd.failure_step : rd.candidate.length;

    pushPhase(plan, 'propose', ri, -1, PHASE_DURATION.propose, FPS);
    for (let s = 0; s < nSteps; s++) pushPhase(plan, 'place', ri, s, PHASE_DURATION.place, FPS);

    if (rd.failure_step !== null) {
      if (rd.failed_verifier === 'kinematic') {
        // Descent is blocked before reaching the target — the solver lifts
        // the rejected block away instead of letting it topple.
        pushPhase(plan, 'drop_blocked', ri, rd.failure_step, PHASE_DURATION.place, FPS);
        pushPhase(plan, 'blocked',      ri, rd.failure_step, PHASE_DURATION.fail, FPS);
        pushPhase(plan, 'learn',        ri, rd.failure_step, PHASE_DURATION.learn, FPS);
        pushPhase(plan, 'retract',      ri, rd.failure_step, PHASE_DURATION.fall, FPS);
      } else {
        pushPhase(plan, 'fail',   ri, rd.failure_step, PHASE_DURATION.fail, FPS);
        pushPhase(plan, 'learn',  ri, rd.failure_step, PHASE_DURATION.learn, FPS);
        pushPhase(plan, 'fall',   ri, rd.failure_step, PHASE_DURATION.fall, FPS);
      }
      pushPhase(plan, 'rewind', ri, nSteps, PHASE_DURATION.rewind, FPS);
      pushPhase(plan, 'pause',  ri, 0, PHASE_DURATION.pause, FPS);
    } else {
      for (let s = nSteps; s < rd.candidate.length; s++) pushPhase(plan, 'place', ri, s, PHASE_DURATION.place, FPS);
      pushPhase(plan, 'success', ri, rd.candidate.length, PHASE_DURATION.success, FPS);
    }
  }
  return plan;
}

function pushPhase(plan, phase, round, step, seconds, fps) {
  const n = Math.max(1, Math.round(seconds * fps));
  for (let i = 0; i < n; i++) plan.push({ phase, round, step, t: i / Math.max(1, n - 1) });
}

// ── Easing ─────────────────────────────────────────────────────────────
const easeOutCubic  = (t) => 1 - Math.pow(1 - t, 3);
const easeOutBack   = (t) => { const c1 = 1.3, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); };
const easeInQuad    = (t) => t * t;

// ── Block state (color + opacity) ───────────────────────────────────────
// Transparent is only flipped on when we genuinely need alpha blending
// (ghost or hidden). Solid states stay fully opaque so the outline hull
// and body render deterministically in the opaque pass.
function setState(m, state) {
  if (!m) return;
  let color, opacity;
  switch (state) {
    case 'placed':  color = PAL.placed;  opacity = 1.0; break;
    case 'active':  color = PAL.active;  opacity = 1.0; break;
    case 'failed':  color = PAL.failed;  opacity = 1.0; break;
    case 'success': color = PAL.success; opacity = 1.0; break;
    case 'hidden':  color = PAL.ghost;   opacity = 0.0; break;
    // Ghost state (unplaced block) — render nothing. The user found the
    // faint grey placeholders distracting; hiding them entirely trades
    // the "you will place this" cue for a cleaner stage.
    default:        color = PAL.ghost;   opacity = 0.0; break;
  }
  const needsAlpha = opacity < 1.0;
  m.material.color.setHex(color);
  m.material.opacity     = opacity;
  m.material.transparent = needsAlpha;
  m.outlineMat.opacity     = (opacity > 0) ? 1.0 : 0.0;
  m.outlineMat.transparent = needsAlpha;
  m.edges.material.opacity     = (opacity > 0) ? 1.0 : 0.0;
  m.edges.material.transparent = needsAlpha;
  m.body.visible = opacity > 0.001;
  m.outline.visible = m.body.visible;
  m.edges.visible = m.body.visible;

  // Dashed anchor at basePos — marks every target slot. Shown for:
  //   * ghost  (not yet placed; anchor alone shows where the block lands)
  //   * active (currently dropping; coloured in the "active" tint)
  //   * failed (currently being rejected; coloured in the "failed" tint)
  // Hidden for 'placed' / 'success' (body already on target) and 'hidden'.
  const showAnchor = !(state === 'placed' || state === 'success' || state === 'hidden');
  m.anchor.visible = showAnchor;
  if (showAnchor) {
    let c;
    if (state === 'failed')      c = PAL.failed;
    else if (state === 'active') c = PAL.active;
    else                         c = PAL.ghost;   // default + explicit 'ghost'
    m.anchorMat.color.setHex(c);
  }
}

// Helper used by fall / retract animations that need to fade the block
// mid-phase without re-calling setState.
function fadeBlock(m, alpha) {
  m.material.opacity     = alpha;
  m.material.transparent = true;
  m.outlineMat.opacity     = alpha;
  m.outlineMat.transparent = true;
  m.edges.material.opacity     = alpha;
  m.edges.material.transparent = true;
}

// ── Render a frame ──────────────────────────────────────────────────────
function renderFrame(idx) {
  if (!trace) return;
  const frame = framePlan[idx];
  if (!frame) return;

  const rd = trace.rounds[frame.round];
  const placedIds = frame.step > 0 ? rd.candidate.slice(0, frame.step) : [];
  const activeId  = frame.step >= 0 && frame.step < rd.candidate.length ? rd.candidate[frame.step] : null;

  // Reset all blocks to base transform + ghost.
  for (const id in blockMeshes) {
    const m = blockMeshes[id];
    m.group.position.copy(m.basePos);
    m.group.rotation.set(0, 0, 0);
    m.group.scale.set(1, 1, 1);
    setState(m, 'ghost');
  }

  // Solid-placed so far.
  for (const id of placedIds) setState(blockMeshes[id], 'placed');

  // Phase-specific behaviour.
  if (frame.phase === 'propose') {
    for (const id of rd.candidate) setState(blockMeshes[id], 'ghost');
  } else if (frame.phase === 'place' && activeId !== null) {
    const m = blockMeshes[activeId];
    setState(m, 'active');
    const t = easeOutCubic(frame.t);
    // Descend from DROP_HEIGHT, then a brief squish on landing.
    const tDrop = Math.min(1, frame.t * 1.15);
    m.group.position.y = m.basePos.y + DROP_HEIGHT * (1 - easeOutCubic(tDrop));
    const squish = frame.t > 0.82 ? (1 - easeOutBack((frame.t - 0.82) / 0.18)) * 0.08 : 0;
    m.group.scale.set(1 + squish, 1 - squish, 1 + squish);
  } else if (frame.phase === 'fail' && activeId !== null) {
    const m = blockMeshes[activeId];
    setState(m, 'failed');
    const shake = 0.05 * Math.sin(frame.t * 28) * (1 - frame.t);
    m.group.position.x = m.basePos.x + shake;
  } else if (frame.phase === 'learn' && activeId !== null) {
    setState(blockMeshes[activeId], 'failed');
    // In kinematic rounds the block is still pressed against its blocker;
    // keep it there while the learned arrows animate in.
    if (rd.failed_verifier === 'kinematic') {
      const stop = computeKinematicStop(rd);
      if (stop) blockMeshes[activeId].group.position.y = stop.stopGroupY;
    }
  } else if (frame.phase === 'drop_blocked' && activeId !== null) {
    // Descent halts at the blocker — the block can't reach its target.
    const m = blockMeshes[activeId];
    setState(m, 'active');
    const stop = computeKinematicStop(rd);
    const endY = stop ? stop.stopGroupY : m.basePos.y;
    const startY = m.basePos.y + DROP_HEIGHT;
    m.group.position.y = startY + (endY - startY) * easeOutCubic(frame.t);
  } else if (frame.phase === 'blocked' && activeId !== null) {
    // Pressed against the blocker — tight vibration + flash to failed colour.
    const m = blockMeshes[activeId];
    setState(m, 'failed');
    const stop = computeKinematicStop(rd);
    if (stop) m.group.position.y = stop.stopGroupY;
    const buzz = 0.045 * Math.sin(frame.t * 42) * (1 - frame.t * 0.6);
    m.group.position.x = m.basePos.x + buzz;
  } else if (frame.phase === 'retract' && activeId !== null) {
    // Lift back up and fade out — "this placement is impossible".
    const m = blockMeshes[activeId];
    setState(m, 'failed');
    const stop = computeKinematicStop(rd);
    const startY = stop ? stop.stopGroupY : m.basePos.y;
    const endY   = m.basePos.y + DROP_HEIGHT * 0.75;
    m.group.position.y = startY + (endY - startY) * easeOutCubic(frame.t);
    fadeBlock(m, Math.max(0, 1.0 - frame.t));
    if (frame.t > 0.98) setState(m, 'hidden');
  } else if (frame.phase === 'fall' && activeId !== null) {
    const m = blockMeshes[activeId];
    setState(m, 'failed');
    const fallT = frame.t;
    // Horizontal push away from the pile — negative side goes left, centred
    // blocks pick a side by id parity.
    const pushDir = Math.sign(m.basePos.x) || (activeId % 2 === 0 ? 1 : -1);
    const targetX = m.basePos.x + pushDir * fallT * 2.6;
    let   targetY = m.basePos.y - 0.5 * GRAVITY * Math.pow(fallT * 1.1, 2);
    const rot     = fallT * 1.8 * pushDir;

    // Rotation-aware collision. For each local vertex rotated by rot,
    // compute rx / ry. World vertex position = (targetX + rx, targetY + ry).
    // We clamp targetY so the lowest rotated vertex stays above every
    // obstacle whose world-X range overlaps the falling block — the plinth
    // floor (only while the block is still over it) plus any already-placed
    // block tops. Past the plinth edge with no block overlap, free-fall.
    const c = Math.cos(rot), s = Math.sin(rot);
    let minLocalY = Infinity, minLocalX = Infinity, maxLocalX = -Infinity;
    for (const [lx, ly] of m.localVerts) {
      const rx = lx * c - ly * s;
      const ry = lx * s + ly * c;
      if (rx < minLocalX) minLocalX = rx;
      if (rx > maxLocalX) maxLocalX = rx;
      if (ry < minLocalY) minLocalY = ry;
    }
    const activeMinX = targetX + minLocalX;
    const activeMaxX = targetX + maxLocalX;

    let obstacleTopY = -Infinity;
    if (Math.abs(targetX) < PLINTH_HALF) obstacleTopY = PLINTH_TOP_Y;
    for (const pid of placedIds) {
      const p = blockMeshes[pid];
      if (!p) continue;
      let pMinX = Infinity, pMaxX = -Infinity, pMaxY = -Infinity;
      for (const [vx, vy] of p.blockData.vertices) {
        const wx = vx + centerOffset.x;
        if (wx < pMinX) pMinX = wx;
        if (wx > pMaxX) pMaxX = wx;
        if (vy > pMaxY) pMaxY = vy;
      }
      // AABB overlap in X.
      if (activeMaxX > pMinX && activeMinX < pMaxX && pMaxY > obstacleTopY) {
        obstacleTopY = pMaxY;
      }
    }
    if (Number.isFinite(obstacleTopY)) {
      const minAllowedY = obstacleTopY - minLocalY;
      if (targetY < minAllowedY) {
        // Light damped bounce on impact — never penetrates obstacles.
        const penetration = minAllowedY - targetY;
        const bounce = penetration * Math.exp(-fallT * 6) * 0.3;
        targetY = minAllowedY + bounce;
      }
    }

    m.group.position.x = targetX;
    m.group.position.y = targetY;
    m.group.rotation.z = rot;
    fadeBlock(m, Math.max(0, 1.0 - fallT * 0.4));
    if (m.group.position.y < -5) setState(m, 'hidden');
  } else if (frame.phase === 'rewind') {
    const nVisible = Math.round(frame.step * (1 - easeInQuad(frame.t)));
    for (let i = 0; i < rd.candidate.length; i++) {
      setState(blockMeshes[rd.candidate[i]], i < nVisible ? 'placed' : 'ghost');
    }
  } else if (frame.phase === 'pause') {
    for (const id of rd.candidate) setState(blockMeshes[id], 'ghost');
  } else if (frame.phase === 'success') {
    // Sequential cascade to success — each block flips at a staggered threshold.
    const n = rd.candidate.length;
    for (let i = 0; i < n; i++) {
      const t0 = i / (n + 2);
      const local = Math.min(1, Math.max(0, (frame.t - t0) * 3.5));
      setState(blockMeshes[rd.candidate[i]], local > 0.01 ? 'success' : 'placed');
      if (local > 0.01 && local < 1) {
        const m = blockMeshes[rd.candidate[i]];
        const pop = Math.sin(local * Math.PI) * 0.06;
        m.group.scale.set(1 + pop, 1 + pop, 1 + pop);
      }
    }
  }

  // Arrows — constraints are knowledge the proposer uses when it builds
  // the NEXT plan. During round N's propose / place / fail phases, only
  // constraints from rounds 0..N-1 were available. In the 'learn' phase
  // the round's newly-learned edges animate in (tagged as active); from
  // round N+1 onward those sit with the rest of the static set.
  const allC = [];
  for (let i = 0; i < frame.round; i++) allC.push(...trace.rounds[i].constraints_learned);
  let activeC = [];
  if (frame.phase === 'learn') {
    allC.push(...rd.constraints_learned);
    activeC = rd.constraints_learned;
  }
  if (SHOW_ARROWS) rebuildArrows(allC, activeC);
  else             rebuildArrows([], []);

  updatePanel(frame, rd, allC, activeC);
}

function updatePanel(frame, rd, allC, activeC) {
  const currentBlock = frame.step >= 0 && frame.step < rd.candidate.length ? rd.candidate[frame.step] : '·';
  const phaseLabel = {
    propose:      'Proposing sequence…',
    place:        `Placing block ${currentBlock}`,
    fail:         `Block ${currentBlock} fails — ${rd.failed_verifier ?? 'verifier'}`,
    learn:        'Learning precedence',
    fall:         'Rejected — block falls away',
    drop_blocked: `Block ${currentBlock} descending`,
    blocked:      `Block ${currentBlock} blocked — kinematic`,
    retract:      'Rejected — cannot reach target',
    rewind:       'Rewinding',
    pause:        '',
    success:      'Sequence complete',
  }[frame.phase] ?? '';
  statusText.textContent = `Round ${frame.round + 1} — ${phaseLabel}`;

  roundLabel.textContent = `Round ${frame.round + 1} / ${trace.rounds.length}`;
  sequenceDisp.textContent = rd.candidate.join(' ');

  constraintsList.innerHTML = '';
  for (const c of allC) {
    const div = document.createElement('div');
    const isNew = activeC.some(ac => ac.before === c.before && ac.after === c.after);
    div.className = 'constraint-item' + (isNew ? ' constraint-new' : '');
    const swatch = `<span class="swatch swatch-${c.source || 'stability'}"></span>`;
    div.innerHTML = `${swatch}${c.before} → ${c.after}`;
    constraintsList.appendChild(div);
  }

  const feasible = trace.result.feasible;
  resultDisplay.innerHTML = `<span class="${feasible ? 'result-feasible' : 'result-infeasible'}">${feasible ? 'FEASIBLE' : 'INFEASIBLE'}</span>`;
  if (trace.result.sequence) {
    resultDisplay.innerHTML += `<br><span class="mono" style="color:var(--muted); font-size:0.8rem; font-weight:400;">${trace.result.sequence.join(' ')}</span>`;
  }

  timelineProg.style.width = `${(currentFrame / Math.max(1, framePlan.length - 1)) * 100}%`;
  frameCounter.textContent = `${currentFrame + 1} / ${framePlan.length}`;
}

// ── Main loop ──────────────────────────────────────────────────────────
function animate(now) {
  requestAnimationFrame(animate);
  const dt = (now - lastTick) / 1000;
  lastTick = now;
  controls.update();

  if (playing) {
    frameAccum += dt;
    const STEP = 1 / 30;
    while (frameAccum > STEP) {
      frameAccum -= STEP;
      if (currentFrame >= framePlan.length - 1) {
        if (LOOP_PLAYBACK) {
          // Pause briefly on the end frame, then restart from the top.
          frameAccum = -0.9;  // ~0.9s pause before the next tick progresses
          setFrame(0);
          break;
        }
        togglePlay();
        break;
      }
      setFrame(currentFrame + 1);
    }
  }
  renderer.render(scene, camera);
}

// ── Controls ───────────────────────────────────────────────────────────
function setFrame(idx) {
  currentFrame = Math.max(0, Math.min(idx, framePlan.length - 1));
  renderFrame(currentFrame);
}
function togglePlay() {
  playing = !playing;
  btnPlay.innerHTML = playing ? '&#10074;&#10074;' : '&#9654;';
  if (playing && currentFrame >= framePlan.length - 1) currentFrame = 0;
  frameAccum = 0;
}
btnPrev.addEventListener('click', () => setFrame(currentFrame - 1));
btnNext.addEventListener('click', () => setFrame(currentFrame + 1));
btnPlay.addEventListener('click', togglePlay);
document.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowLeft')  setFrame(currentFrame - 1);
  else if (e.key === 'ArrowRight') setFrame(currentFrame + 1);
  else if (e.key === ' ')     { e.preventDefault(); togglePlay(); }
});
timelineBar.addEventListener('click', (e) => {
  const r = timelineBar.getBoundingClientRect();
  setFrame(Math.round(((e.clientX - r.left) / r.width) * (framePlan.length - 1)));
});

// ── Trace loading ──────────────────────────────────────────────────────
// ── Right-panel 3D structure preview ───────────────────────────────────
// A second Three.js scene that mirrors the main view's camera, lighting,
// materials and plinth. Static render — no animation loop, no orbit —
// just shows what the target looks like. Rebuilt when a trace loads and
// re-rendered on window resize.
function initPreview() {
  const mount = document.getElementById('preview-canvas');
  if (!mount) return;

  previewScene = new THREE.Scene();
  previewScene.background = new THREE.Color(PAL.bg);

  const w = Math.max(1, mount.clientWidth);
  const h = Math.max(1, mount.clientHeight);
  const aspect = w / h;
  const vs = 6;
  previewCamera = new THREE.OrthographicCamera(-vs * aspect, vs * aspect, vs, -vs, -100, 100);
  previewCamera.position.set(-14, 12, 14);
  previewCamera.lookAt(0, 0, 0);

  previewRenderer = new THREE.WebGLRenderer({ antialias: true });
  previewRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  previewRenderer.setSize(w, h);
  previewRenderer.shadowMap.enabled = true;
  previewRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
  mount.appendChild(previewRenderer.domElement);

  // Lights — same warm-cool key/fill as the main scene. Key casts shadow
  // so the preview matches the left panel's shadow treatment.
  const key = new THREE.DirectionalLight(PAL.keyLight, 1.0);
  key.position.set(8, 14, 6);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -12; key.shadow.camera.right = 12;
  key.shadow.camera.top = 12;   key.shadow.camera.bottom = -12;
  key.shadow.camera.near = 0.5; key.shadow.camera.far = 50;
  key.shadow.bias = -0.0005;
  previewScene.add(key);
  const fill = new THREE.DirectionalLight(PAL.fillLight, 0.5);
  fill.position.set(-8, 6, -4);
  previewScene.add(fill);
  previewScene.add(new THREE.AmbientLight(0xffffff, 0.22));

  const ground = new THREE.Mesh(
    new THREE.BoxGeometry(30, 0.6, 30),
    new THREE.MeshLambertMaterial({ color: PAL.ground }),
  );
  ground.position.y = -0.3;
  ground.receiveShadow = true;
  previewScene.add(ground);
  const groundEdge = new THREE.LineSegments(
    new THREE.EdgesGeometry(ground.geometry),
    new THREE.LineBasicMaterial({ color: PAL.ink, transparent: true, opacity: 0.55 }),
  );
  groundEdge.position.copy(ground.position);
  previewScene.add(groundEdge);

  previewRoot = new THREE.Group();
  previewScene.add(previewRoot);

  window.addEventListener('resize', () => {
    if (!previewRenderer) return;
    const w2 = mount.clientWidth, h2 = mount.clientHeight;
    if (w2 < 1 || h2 < 1) return;
    previewRenderer.setSize(w2, h2);
    const a = w2 / h2;
    const v = previewCamera.top;  // preserve current zoom
    previewCamera.left = -v * a; previewCamera.right = v * a;
    previewCamera.updateProjectionMatrix();
    previewRenderer.render(previewScene, previewCamera);
  });
}

// Lightweight block for the preview — same visual recipe as makeBlock
// (body + backface-hull outline + edge lines), minus the state machinery
// and target-ghost anchor. Returns a Group ready to drop into a scene.
function makeStaticBlock(blockData, color) {
  const [cx, cy] = blockData.centroid;
  const verts = blockData.vertices.map(([x, y]) => [x - cx, y - cy]);
  const shape = new THREE.Shape();
  shape.moveTo(verts[0][0], verts[0][1]);
  for (let i = 1; i < verts.length; i++) shape.lineTo(verts[i][0], verts[i][1]);
  shape.closePath();

  const depth = blockData.depth ?? DEFAULT_DEPTH;
  const geom = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false, curveSegments: 1 });
  geom.translate(0, 0, -depth / 2);
  geom.computeVertexNormals();

  const body = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color }));
  body.renderOrder = 1;
  body.castShadow = true;
  body.receiveShadow = true;

  const outline = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
    color: PAL.ink, side: THREE.BackSide,
    polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2,
  }));
  outline.scale.set(1.04, 1.04, 1.08);
  outline.renderOrder = 0;

  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(geom, 30),
    new THREE.LineBasicMaterial({ color: PAL.ink }),
  );
  edges.renderOrder = 2;

  const g = new THREE.Group();
  g.add(outline);
  g.add(body);
  g.add(edges);
  return g;
}

function buildPreview() {
  if (!previewRenderer || !trace) return;

  // Dispose previous preview content.
  while (previewRoot.children.length) {
    const c = previewRoot.children[0];
    previewRoot.remove(c);
    c.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) o.material.dispose?.();
    });
  }

  const ex = trace.structure.extents;
  const offsetX = -(ex.min_x + ex.max_x) / 2;
  // Preview shows the final state the main view settles into: mint on
  // success, rose on infeasible.
  const infeasible = trace.result && trace.result.feasible === false;
  const blockColor = infeasible ? PAL.failed : PAL.success;

  for (const b of trace.structure.blocks) {
    const g = makeStaticBlock(b, blockColor);
    g.position.set(b.centroid[0] + offsetX, b.centroid[1], 0);
    previewRoot.add(g);
  }

  // Fit camera tightly. The preview canvas is ~1/4 the main view so we
  // want the structure to fill most of the frame, not float in it. We
  // compute the minimum ortho half-height that actually fits both the
  // horizontal and vertical screen projections, then pad lightly.
  const spanX = Math.max(1.0, ex.max_x - ex.min_x);
  const spanY = Math.max(1.0, ex.max_y - ex.min_y);
  const mount = document.getElementById('preview-canvas');
  const aspect = mount.clientWidth / Math.max(1, mount.clientHeight);
  // Iso projection stretches extents roughly by 1.2× vertically, 1.15× horizontally.
  const needY = (spanY * 1.0 + spanX * 0.35) / 2;
  const needX = (spanX * 1.0 + spanY * 0.35) / (2 * aspect);
  const vs = Math.max(needX, needY) * 1.15 + 0.25;
  previewCamera.left = -vs * aspect; previewCamera.right = vs * aspect;
  previewCamera.top = vs; previewCamera.bottom = -vs;
  previewCamera.updateProjectionMatrix();
  previewCamera.lookAt(0, spanY * 0.45, 0);

  previewRenderer.render(previewScene, previewCamera);
}

async function loadTrace(name) {
  if (playing) togglePlay();
  try {
    // Prefer the inlined bundle (window.TRACES[name]) when present — this
    // is what lets the blog/iframe work from file:// where fetch() fails.
    if (window.TRACES && window.TRACES[name]) {
      trace = window.TRACES[name];
    } else {
      const resp = await fetch(`data/${name}.json`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      trace = await resp.json();
    }
    buildBlocks();
    buildPreview();
    framePlan = buildFramePlan();
    currentFrame = 0;
    renderFrame(0);
    statusText.textContent = `Loaded ${trace.name ?? name}`;
  } catch (e) {
    statusText.textContent = `Error loading trace: ${e.message}`;
    console.error(e);
  }
}
traceSelect.addEventListener('change', () => loadTrace(traceSelect.value));

// ── Init ───────────────────────────────────────────────────────────────
initScene();
initPreview();
requestAnimationFrame((t) => { lastTick = t; animate(t); });

// URL-param overrides: ?structure=pyramid_10 picks a trace up front.
// Autoplay is on by default; pass ?autoplay=0 to start paused.
const _params = new URLSearchParams(location.search);
const _overrideStruct = _params.get('structure');
if (_overrideStruct) {
  const opt = [...traceSelect.options].find(o => o.value === _overrideStruct);
  if (opt) traceSelect.value = _overrideStruct;
}
const _autoplay = _params.get('autoplay') !== '0';
loadTrace(traceSelect.value).then?.(() => {
  if (_autoplay && !playing) togglePlay();
});
if (_autoplay) {
  // loadTrace isn't typed as a promise in older paths; use a timeout fallback.
  setTimeout(() => { if (!playing && framePlan.length) togglePlay(); }, 500);
}
