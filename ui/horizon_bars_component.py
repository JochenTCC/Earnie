"""Streamlit component: horizon as draggable bars, north to north (SUSI P3a editor).

One bar per direction. Active bars are dragged with the mouse or stepped by 1° with the
buttons under the axis; the state ``elevations`` goes back to Python when the mouse is
released or shortly after the last button step. HTML, CSS and JS are inline strings, so
no asset has to be packaged.
"""
from __future__ import annotations

import streamlit as st

_HTML = '<div class="hz"></div>'

_CSS = """
.hz { width: 100%; color: var(--st-text-color); font-family: var(--st-font); }
.hz svg { width: 100%; height: auto; display: block; user-select: none; }
.hz text { fill: currentColor; font-size: 13px; }
.hz .small { font-size: 11px; opacity: 0.7; }
.hz .grid { stroke: currentColor; stroke-opacity: 0.15; stroke-width: 1; }
.hz .axis { stroke: currentColor; stroke-opacity: 0.5; stroke-width: 1; }
.hz .area { fill: currentColor; fill-opacity: 0.18; stroke: currentColor; stroke-opacity: 0.6; stroke-width: 1.5; }
.hz .bar { fill: currentColor; fill-opacity: 0.28; }
.hz .grip { stroke: var(--st-primary-color); stroke-width: 5; stroke-linecap: round; }
.hz .hit { fill: transparent; cursor: ns-resize; }
.hz .hit:hover + .bar, .hz .bar.drag { fill: var(--st-primary-color); fill-opacity: 0.45; }
.hz .value { font-weight: 600; paint-order: stroke; stroke: var(--st-background-color); stroke-width: 4px; }
.hz .off { opacity: 0.35; }
.hz .sun { fill: none; stroke-width: 2; pointer-events: none; }
.hz .btn rect { fill: var(--st-secondary-background-color); stroke: currentColor; stroke-opacity: 0.35; rx: 4; cursor: pointer; }
.hz .btn:hover rect { stroke: var(--st-primary-color); stroke-opacity: 1; }
.hz .btn text { pointer-events: none; font-size: 11px; }
"""

_JS = """
const NS = 'http://www.w3.org/2000/svg';
const W = 1000, H = 352, X0 = 46, X1 = 992, Y0 = 16, Y1 = 280;
const SPAN = 382.5, PAD = 11.25;

function el(name, attrs, parent, text) {
  const node = document.createElementNS(NS, name);
  for (const key in attrs) node.setAttribute(key, attrs[key]);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.appendChild(node);
  return node;
}

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector('.hz');
  const store = root.__hz || (root.__hz = { values: null, dirty: false, timer: null, hold: null });
  store.commit = setStateValue;
  if (!store.dirty) store.values = data.elevations.slice();
  const values = store.values;
  const maxDeg = data.max_elevation;
  const count = values.length;
  const step = 360 / count;
  const px = (compass) => X0 + ((compass + PAD) / SPAN) * (X1 - X0);
  const py = (deg) => Y1 - (deg / maxDeg) * (Y1 - Y0);
  const pitch = (step / SPAN) * (X1 - X0);
  const show = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1).replace('.', ',')) + '°';

  root.replaceChildren();
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img' }, root);
  el('title', {}, svg, data.title);

  for (let deg = 0; deg <= maxDeg; deg += 15) {
    el('line', { class: deg === 0 ? 'axis' : 'grid', x1: X0, x2: X1, y1: py(deg), y2: py(deg) }, svg);
    el('text', { class: 'small', x: X0 - 6, y: py(deg) + 4, 'text-anchor': 'end' }, svg, deg + '°');
  }

  const area = el('polygon', { class: 'area' }, svg);
  for (const path of data.paths) {
    const points = path.points.map(([c, e]) => `${px(c).toFixed(1)},${py(e).toFixed(1)}`).join(' ');
    el('polyline', { class: 'sun', stroke: path.color, points }, svg);
  }
  data.paths.forEach((path, row) => {
    const y = Y0 + 10 + row * 17;
    el('line', { class: 'sun', stroke: path.color, x1: X1 - 178, x2: X1 - 154, y1: y, y2: y }, svg);
    el('text', { class: 'small', x: X1 - 148, y: y + 4 }, svg, path.label);
  });

  // Column 16 repeats north at the right edge.
  const columns = [];
  for (let col = 0; col <= count; col++) columns.push({ index: col % count, x: px(col * step) });
  const parts = columns.map(() => ({}));

  function update() {
    const mid = (values[count - 1] + values[0]) / 2;
    const outline = [[X0, py(mid)]];
    columns.forEach((c) => outline.push([c.x, py(values[c.index])]));
    outline.push([X1, py(mid)], [X1, Y1], [X0, Y1]);
    area.setAttribute('points', outline.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' '));
    columns.forEach((c, i) => {
      const part = parts[i];
      if (!part.bar) return;
      const top = py(values[c.index]);
      part.bar.setAttribute('y', top);
      part.bar.setAttribute('height', Math.max(0, Y1 - top));
      part.grip.setAttribute('y1', top);
      part.grip.setAttribute('y2', top);
      part.value.setAttribute('y', top - 9);
      part.value.textContent = show(values[c.index]);
    });
  }

  function send() {
    clearTimeout(store.timer);
    store.timer = null;
    store.dirty = false;
    store.commit('elevations', values.slice());
  }
  function sendSoon() {
    clearTimeout(store.timer);
    store.timer = setTimeout(send, 600);
  }
  function setValue(index, deg) {
    const next = Math.min(maxDeg, Math.max(0, deg));
    if (next === values[index]) return;
    values[index] = next;
    store.dirty = true;
    update();
  }
  function degAt(event) {
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    return Math.round(((Y1 - point.y) / (Y1 - Y0)) * maxDeg);
  }
  function stopHold() {
    clearTimeout(store.hold);
    clearInterval(store.hold);
    store.hold = null;
  }

  columns.forEach((c, i) => {
    const active = data.active[c.index];
    const label = el('text', { x: c.x, y: Y1 + 18, 'text-anchor': 'middle' }, svg, data.labels[c.index]);
    const degrees = el('text', { class: 'small', x: c.x, y: Y1 + 32, 'text-anchor': 'middle' }, svg, data.degrees[c.index]);
    if (!active) {
      label.classList.add('off');
      degrees.classList.add('off');
      return;
    }
    const part = parts[i];
    const hit = el('rect', { class: 'hit', x: c.x - pitch / 2, y: Y0, width: pitch, height: Y1 - Y0 }, svg);
    part.bar = el('rect', { class: 'bar', x: c.x - 15, width: 30, 'pointer-events': 'none' }, svg);
    part.grip = el('line', { class: 'grip', x1: c.x - 15, x2: c.x + 15, 'pointer-events': 'none' }, svg);
    part.value = el('text', { class: 'value', x: c.x, 'text-anchor': 'middle', 'pointer-events': 'none' }, svg);
    el('title', {}, hit, data.drag_hint);

    hit.addEventListener('pointerdown', (event) => {
      if (event.pointerType === 'touch' || event.button !== 0) return;
      event.preventDefault();
      hit.setPointerCapture(event.pointerId);
      part.dragging = true;
      part.bar.classList.add('drag');
      clearTimeout(store.timer);
      setValue(c.index, degAt(event));
    });
    hit.addEventListener('pointermove', (event) => {
      if (part.dragging) setValue(c.index, degAt(event));
    });
    const release = () => {
      if (!part.dragging) return;
      part.dragging = false;
      part.bar.classList.remove('drag');
      if (store.dirty) send();
    };
    hit.addEventListener('pointerup', release);
    hit.addEventListener('pointercancel', release);

    [[1, '▲', -13, data.up_hint], [-1, '▼', 13, data.down_hint]].forEach(([delta, glyph, dx, hint]) => {
      const group = el('g', { class: 'btn' }, svg);
      el('rect', { x: c.x + dx - 11, y: Y1 + 40, width: 22, height: 22 }, group);
      el('text', { x: c.x + dx, y: Y1 + 55, 'text-anchor': 'middle' }, group, glyph);
      el('title', {}, group, hint);
      const stepOnce = () => setValue(c.index, Math.round(values[c.index]) + delta);
      group.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        clearTimeout(store.timer);
        stepOnce();
        stopHold();
        store.hold = setTimeout(() => { store.hold = setInterval(stepOnce, 70); }, 400);
      });
      const done = () => {
        stopHold();
        if (store.dirty) sendSoon();
      };
      group.addEventListener('pointerup', done);
      group.addEventListener('pointerleave', done);
      group.addEventListener('pointercancel', done);
    });
  });

  update();
  return stopHold;
}
"""

_horizon_bars = st.components.v2.component("earnie_horizon_bars", html=_HTML, css=_CSS, js=_JS)


def horizon_bars(
    *,
    key: str,
    labels: list[str],
    degrees: list[str],
    active: list[bool],
    seed: list[float],
    paths: list[dict],
    max_elevation: float,
) -> list[float]:
    """Mount the bar editor and return the elevations it holds (seed until the first change)."""
    state = st.session_state.get(key)
    current = state.get("elevations") if state is not None else None
    elevations = list(seed) if current is None else [float(v) for v in current]
    result = _horizon_bars(
        key=key,
        data={
            "title": "Horizont und Sonnenbahnen über der Himmelsrichtung",
            "drag_hint": "Ziehen oder klicken: Höhenwinkel setzen",
            "up_hint": "1° höher (gedrückt halten: schneller)",
            "down_hint": "1° niedriger (gedrückt halten: schneller)",
            "labels": labels,
            "degrees": degrees,
            "active": active,
            "elevations": elevations,
            "paths": paths,
            "max_elevation": max_elevation,
        },
        default={"elevations": elevations},
        on_elevations_change=lambda: None,
    )
    return [float(v) for v in result.elevations]
