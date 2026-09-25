/*
 * Apartment Hunter: the web UI.
 * Vanilla ES2020 in one classic script, no build step. All requests go to the same origin (/api/...).
 * Listing text comes from websites, so this file builds DOM nodes and never puts listing data into innerHTML.
 */
'use strict';

// ---------------------------------------------------------------- constants

const RENDER_STEP = 300;
const RANK_DEBOUNCE_MS = 200;
const SETTINGS_DEBOUNCE_MS = 1000;
const POLL_MS = 1000;
const POLL_RETRY_MS = 3000;
const SLOW_RANK_MS = 300;
const DEFAULT_AREA_TIER = 3;
const PRICE_MIN = 0;
const PRICE_MAX = 15000;
const PRICE_STEP = 50;
const DESCRIPTION_PREVIEW = 200;
const MAP_CENTER = [40.745, -73.98];
const MAP_ZOOM = 12;
// Esri light gray canvas: keyless (CARTO basemaps need a key since September 2026). Note the {y}/{x} order.
const TILE_BASE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}';
const TILE_LABELS_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}';
const TILE_ATTRIBUTION = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors';
const TILE_OPTIONS = { maxNativeZoom: 16, maxZoom: 19 };
const VIEW_KEY = 'apartment-hunter:view';

const TIER_NAMES = { 1: 'Best matches', 2: 'Strong', 3: 'Possible', 4: 'Weak' };
const TIER_COLORS = { 1: '#1E7A4F', 2: '#3F83D6', 3: '#D69A1E', 4: '#949BA4' };
const SITE_NAMES = { streeteasy: 'StreetEasy', zillow: 'Zillow' };
const JOB_NAMES = { search: 'Search', inspect: 'Inspect', deep: 'Deep look' };
const SHORT_LABELS = {
  price: 'Price', neighborhood: 'Area', subway: 'Subway', lines: 'Lines', size: 'Size', bedrooms: 'Beds',
  floor: 'Floor', move_in: 'Move-in', deal: 'Deal', views: 'Views', light: 'Light', windows: 'Windows',
  renovation: 'Reno', space: 'Space',
};
const BEDS_OPTIONS = [[0, 'Studio'], [1, '1'], [2, '2'], [3, '3'], [4, '4+']];
const BATHS_OPTIONS = [[1, '1'], [1.5, '1.5'], [2, '2']];
const TIER_OPTIONS = [[1, '1'], [2, '2'], [3, '3'], [4, '4']];
const SOURCE_OPTIONS = [['streeteasy', 'StreetEasy'], ['zillow', 'Zillow']];
const SAFETY_FIELDS = [
  { key: 'page_loads_per_site', label: 'Page loads per site', min: 1, max: 3, unit: '' },
  { key: 'pause_s', label: 'Pause between page loads', min: 20, max: 600, unit: 's' },
  { key: 'deep_look_max', label: 'Deep look, listings per run', min: 1, max: 10, unit: '' },
  { key: 'deep_look_pause_s', label: 'Pause between detail pages', min: 30, max: 600, unit: 's' },
  { key: 'human_wait_s', label: 'Wait for a human check', min: 30, max: 900, unit: 's' },
  { key: 'inspect_top_n', label: 'Inspect top N', min: 1, max: 60, unit: '' },
];
const DEEP_TITLE = 'Open the listing page in your Chrome and read the full description, photos, and amenities. '
  + 'Uses one page load.';

const LINE_COLORS = {};
[
  [['1', '2', '3'], '#EE352E'],
  [['4', '5', '6', '6X'], '#00933C'],
  [['7', '7X'], '#B933AD'],
  [['A', 'C', 'E'], '#0039A6'],
  [['B', 'D', 'F', 'FX', 'M'], '#FF6319'],
  [['G'], '#6CBE45'],
  [['J', 'Z'], '#996633'],
  [['L'], '#A7A9AC'],
  [['N', 'Q', 'R', 'W'], '#FCCC0A', '#000000'],
  [['S', 'GS', 'FS', 'H'], '#808183'],
  [['T'], '#00ADD0'],
].forEach(([lines, bg, fg]) => lines.forEach((line) => { LINE_COLORS[line] = { bg, fg: fg || '#FFFFFF' }; }));
const LINE_DISPLAY = { GS: 'S', FS: 'S', H: 'S', '6X': '6', '7X': '7', FX: 'F' };

// ---------------------------------------------------------------- small helpers

const $ = (selector, root) => (root || document).querySelector(selector);
const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isText = (v) => typeof v === 'string' && v.trim() !== '';
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
let uidCounter = 0;
const uid = (prefix) => `${prefix}-${(uidCounter += 1)}`;
const reducedMotion = () => Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

function toStep(value, lo, hi, step, fallback) {
  if (value === '' || value === null || value === undefined) return fallback;
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return clamp(Math.round(n / step) * step, lo, hi);
}

const moneyFormat = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const intFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const decFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const fmtMoney = (v) => (isNum(v) ? moneyFormat.format(v) : '—');
const fmtInt = (v) => (isNum(v) ? intFormat.format(v) : '—');
const fmtDec = (v) => (isNum(v) ? decFormat.format(v) : '—');
const plural = (n, one, many) => `${fmtDec(n)} ${n === 1 ? one : (many || `${one}s`)}`;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

// Dates from the server are "YYYY-MM-DD" or naive local "YYYY-MM-DDTHH:MM:SS". Parse by hand: no UTC shift.
function parseDay(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(typeof text === 'string' ? text : '');
  if (!m) return null;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function fmtDay(date) {
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return `${MONTHS[date.getMonth()]} ${date.getDate()}${sameYear ? '' : `, ${date.getFullYear()}`}`;
}

function fmtStamp(text) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(typeof text === 'string' ? text : '');
  if (!m) return null;
  const hour = Number(m[4]);
  const day = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return `${fmtDay(day)}, ${hour % 12 === 0 ? 12 : hour % 12}:${m[5]} ${hour < 12 ? 'AM' : 'PM'}`;
}

function fmtClock(text) {
  const m = /[T ](\d{2}:\d{2}:\d{2})/.exec(typeof text === 'string' ? text : '');
  return m ? m[1] : '';
}

function fmtSeconds(s) {
  if (!isNum(s)) return '';
  if (s >= 60 && s % 60 === 0) return plural(s / 60, 'minute');
  return plural(s, 'second');
}

// ---------------------------------------------------------------- DOM building (no innerHTML for data)

const DOM_PROPS = new Set(['checked', 'disabled', 'value', 'hidden', 'indeterminate', 'open']);

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key === 'style') Object.assign(el.style, value);
      else if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else if (DOM_PROPS.has(key)) el[key] = value;
      else el.setAttribute(key, value === true ? '' : String(value));
    }
  }
  return append(el, children);
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === '') continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICON_HOME = 'M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z';

function icon(pathData, className) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('class', className || 'icon');
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', pathData);
  svg.append(path);
  return svg;
}

// Only http(s) links leave the page; photos must be https.
function safeUrl(value, httpsOnly) {
  if (!isText(value)) return null;
  try {
    const url = new URL(value, window.location.href);
    if (url.protocol === 'https:' || (!httpsOnly && url.protocol === 'http:')) return url.href;
  } catch (error) {
    return null;
  }
  return null;
}

function setRangeFill(input) {
  const min = Number(input.min) || 0;
  const max = Number(input.max) || 100;
  const pct = max > min ? ((Number(input.value) - min) / (max - min)) * 100 : 0;
  input.style.setProperty('--fill', `${clamp(pct, 0, 100)}%`);
}

// ---------------------------------------------------------------- API

const TOKEN = (document.querySelector('meta[name="hunter-token"]') || {}).content || '';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function api(path, body) {
  const init = { cache: 'no-store', headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    init.method = 'POST';
    init.headers['Content-Type'] = 'application/json';
    init.headers['X-Hunter-Token'] = TOKEN;
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (error) {
    throw new ApiError('The Apartment Hunter server does not answer. Check that it still runs.', 0);
  }
  let data = null;
  try {
    const text = await res.text();
    data = text ? JSON.parse(text) : null;
  } catch (error) {
    data = null;
  }
  if (!res.ok) {
    const message = isObj(data) && isText(data.error) ? data.error.trim() : `The server answered HTTP ${res.status} for ${path}.`;
    throw new ApiError(message, res.status);
  }
  if (!isObj(data)) throw new ApiError(`The server did not send JSON for ${path}.`, res.status);
  return data;
}

// ---------------------------------------------------------------- state

const state = {
  config: null,
  criteria: [],
  presets: [],
  amenities: [],
  stations: [],
  limits: {},
  weights: {},
  tiers: {},
  safety: {},
  lastSearch: null,
  result: null, // the last /api/rank answer
  listings: [], // result.listings, best first
  byId: new Map(),
  rankError: null,
  job: null,
  events: [],
  chrome: null,
  notice: null, // {text, level, source}: an error or a job summary for the status line
  cancelPending: false,
  progressDone: null,
  view: 'split',
  renderLimit: RENDER_STEP,
  selectedId: null,
  photoIndex: new Map(), // listing id -> index of the photo the card shows
  openDetails: new Set(), // listing ids with the full description open
  pendingFit: false,
  fitOnShow: false,
};
const dirty = new Set(); // settings keys changed since the last POST /api/settings
const timers = { rank: null, settings: null, poll: null, slow: null };

// ---------------------------------------------------------------- config

const passOf = (c) => (Number(c.pass) === 2 ? 2 : 1);
const criterionLabel = (id) => (state.criteria.find((c) => c.id === id) || {}).label || id;

function normalizeWeights(raw) {
  const src = isObj(raw) ? raw : {};
  const out = {};
  for (const c of state.criteria) {
    const n = Number(src[c.id]);
    const fallback = Number.isFinite(Number(c.weight)) ? clamp(Math.round(Number(c.weight)), 0, 10) : 5;
    const given = src[c.id] !== undefined && src[c.id] !== null && Number.isFinite(n);
    out[c.id] = given ? clamp(Math.round(n), 0, 10) : fallback;
  }
  return out;
}

function defaultWeights() {
  return normalizeWeights({});
}

function normalizeTiers(raw) {
  const out = {};
  if (!isObj(raw)) return out;
  for (const [key, value] of Object.entries(raw)) {
    const tier = Number(value);
    if (/^\d+$/.test(String(key)) && [1, 2, 3, 4].includes(tier)) out[String(key)] = tier;
  }
  return out;
}

function normalizeLimits(raw) {
  const src = isObj(raw) ? raw : {};
  const lim = { ...src };
  lim.price_min = toStep(src.price_min, PRICE_MIN, PRICE_MAX, 1, PRICE_MIN);
  lim.price_max = toStep(src.price_max, PRICE_MIN, PRICE_MAX, 1, 7500);
  if (lim.price_max < lim.price_min) lim.price_max = lim.price_min;
  lim.beds_min = toStep(src.beds_min, 0, 4, 1, 1);
  lim.beds_max = toStep(src.beds_max, 0, 4, 1, 4);
  if (lim.beds_max < lim.beds_min) lim.beds_max = lim.beds_min;
  const baths = Number(src.baths_min);
  lim.baths_min = src.baths_min !== null && src.baths_min !== undefined && Number.isFinite(baths) ? baths : 1;
  lim.sqft_min = toStep(src.sqft_min, 0, 20000, 1, 0);
  lim.max_tier = toStep(src.max_tier, 1, 4, 1, 4);
  lim.max_walk_min = toStep(src.max_walk_min, 1, 20, 1, 15);
  lim.move_in_from = isText(src.move_in_from) ? src.move_in_from.slice(0, 10) : null;
  lim.move_in_by = isText(src.move_in_by) ? src.move_in_by.slice(0, 10) : null;
  lim.areas = Array.isArray(src.areas) ? src.areas.map(Number).filter(Number.isFinite) : [];
  lim.must_have = Array.isArray(src.must_have) ? src.must_have.filter(isText) : [];
  lim.sources = Array.isArray(src.sources) ? src.sources.filter(isText) : SOURCE_OPTIONS.map(([id]) => id);
  lim.strict_move_in = Boolean(src.strict_move_in);
  lim.no_ground_floor = Boolean(src.no_ground_floor);
  lim.include_building_groups = src.include_building_groups === undefined ? true : Boolean(src.include_building_groups);
  lim.use_net_effective = Boolean(src.use_net_effective);
  return lim;
}

function normalizeSafety(raw) {
  const src = isObj(raw) ? raw : {};
  const out = { ...src };
  for (const f of SAFETY_FIELDS) {
    if (src[f.key] !== undefined) out[f.key] = toStep(src[f.key], f.min, f.max, 1, f.min);
  }
  return out;
}

function applyConfig(cfg) {
  state.config = cfg;
  state.criteria = (Array.isArray(cfg.criteria) ? cfg.criteria : []).filter((c) => isObj(c) && isText(c.id));
  state.presets = (Array.isArray(cfg.presets) ? cfg.presets : []).filter((p) => isObj(p) && isObj(p.weights));
  state.amenities = (Array.isArray(cfg.amenities) ? cfg.amenities : []).filter((a) => isObj(a) && isText(a.id));
  state.stations = (Array.isArray(cfg.stations) ? cfg.stations : []).filter(isObj);
  buildTree(Array.isArray(cfg.areas) ? cfg.areas : []);
  state.limits = normalizeLimits(clone(cfg.limits));
  state.weights = normalizeWeights(cfg.weights);
  state.tiers = normalizeTiers(cfg.tiers);
  state.safety = normalizeSafety(clone(cfg.safety));
  state.lastSearch = isObj(cfg.last_search) ? cfg.last_search : null;
}

// ---------------------------------------------------------------- area tree

const tree = { byId: new Map(), children: new Map(), roots: [], desc: new Map() };

function buildTree(areas) {
  tree.byId.clear();
  tree.children.clear();
  tree.desc.clear();
  tree.roots = [];
  for (const a of areas) {
    const id = Number(a && a.id);
    if (!Number.isFinite(id)) continue;
    const parent = a.parent_id === null || a.parent_id === undefined ? null : Number(a.parent_id);
    tree.byId.set(id, {
      id, name: isText(a.name) ? a.name : `Area ${id}`, level: Number(a.level) || 0, parent_id: parent,
      borough: isText(a.borough) ? a.borough : null,
    });
  }
  for (const a of tree.byId.values()) {
    if (a.parent_id !== null && a.parent_id !== a.id && tree.byId.has(a.parent_id)) {
      if (!tree.children.has(a.parent_id)) tree.children.set(a.parent_id, []);
      tree.children.get(a.parent_id).push(a);
    } else {
      tree.roots.push(a);
    }
  }
  const byName = (x, y) => x.name.localeCompare(y.name, 'en', { sensitivity: 'base' });
  for (const kids of tree.children.values()) kids.sort(byName);
  tree.roots.sort((x, y) => x.id - y.id);
  for (const a of tree.byId.values()) {
    const out = [];
    const seen = new Set([a.id]);
    const stack = [...(tree.children.get(a.id) || [])];
    while (stack.length) {
      const node = stack.pop();
      if (seen.has(node.id)) continue;
      seen.add(node.id);
      out.push(node.id);
      stack.push(...(tree.children.get(node.id) || []));
    }
    tree.desc.set(a.id, out);
  }
}

function ancestors(id) {
  const out = [];
  const seen = new Set([id]);
  let node = tree.byId.get(id);
  while (node && node.parent_id !== null && tree.byId.has(node.parent_id) && !seen.has(node.parent_id)) {
    out.push(node.parent_id);
    seen.add(node.parent_id);
    node = tree.byId.get(node.parent_id);
  }
  return out;
}

const selectedAreas = () => new Set((state.limits.areas || []).map(Number));
const coveredBy = (id, sel) => sel.has(id) || ancestors(id).some((a) => sel.has(a));

// The user's tier for an area: its own entry, else the nearest ancestor's, else 3 (same rule as the server).
function tierInfo(id) {
  let current = id;
  const seen = new Set();
  while (current !== null && current !== undefined && !seen.has(current)) {
    seen.add(current);
    const tier = state.tiers[String(current)];
    if ([1, 2, 3, 4].includes(tier)) {
      const from = tree.byId.get(current);
      return { tier, own: current === id, fromName: from ? from.name : null };
    }
    const node = tree.byId.get(current);
    current = node ? node.parent_id : null;
  }
  return { tier: DEFAULT_AREA_TIER, own: false, fromName: null };
}

// True when an area of `current` is not covered by `last` (directly, by an ancestor, or by all its children).
function areasAdded(current, last) {
  const lastSet = new Set(last.map(Number));
  const covered = (id, depth) => {
    if (coveredBy(id, lastSet)) return true;
    const kids = tree.children.get(id) || [];
    return depth < 8 && kids.length > 0 && kids.every((k) => covered(k.id, depth + 1));
  };
  return current.some((id) => !covered(Number(id), 0));
}

// Limits that need new data from the sites: the last search could not have fetched these listings.
function limitsWider() {
  const last = state.lastSearch && isObj(state.lastSearch.limits) ? state.lastSearch.limits : null;
  if (!last) return false;
  const cur = state.limits;
  const more = (a, b) => isNum(a) && isNum(b) && a > b;
  if (more(cur.price_max, last.price_max) || more(last.price_min, cur.price_min)) return true;
  if (more(last.beds_min, cur.beds_min) || more(cur.beds_max, last.beds_max)) return true;
  if (more(last.sqft_min, cur.sqft_min) || more(last.baths_min, cur.baths_min)) return true;
  if (isText(cur.move_in_by) && isText(last.move_in_by) && cur.move_in_by > last.move_in_by) return true;
  if (Array.isArray(last.sources) && cur.sources.some((s) => !last.sources.includes(s))) return true;
  if (Array.isArray(last.must_have) && last.must_have.some((m) => !cur.must_have.includes(m))) return true;
  return Array.isArray(last.areas) && areasAdded(cur.areas, last.areas);
}

// ---------------------------------------------------------------- listing helpers

const isActive = (job) => Boolean(job) && (job.status === 'running' || job.status === 'waiting_for_user');
const tierOf = (l) => ([1, 2, 3, 4].includes(l.tier) ? l.tier : 4);
const hasPoint = (l) => isNum(l.lat) && isNum(l.lon) && Math.abs(l.lat) <= 90 && Math.abs(l.lon) <= 180;
const scoreOf = (l) => (isNum(l.score) ? Math.round(clamp(l.score, 0, 1) * 100) : null);

function listingTitle(l) {
  if (isText(l.title)) return l.title.trim();
  const parts = [l.street, l.unit].filter(isText).map((s) => s.trim());
  return parts.length ? parts.join(' ') : 'Untitled listing';
}

function listingUrls(l) {
  const urls = isObj(l.urls) ? { ...l.urls } : {};
  if (isText(l.source) && !urls[l.source] && isText(l.url)) urls[l.source] = l.url;
  return urls;
}

const primaryUrl = (l) => safeUrl(l.url) || Object.values(listingUrls(l)).map((u) => safeUrl(u)).find(Boolean) || null;

function listingPhotos(l) {
  const list = [];
  const add = (u) => {
    const url = safeUrl(u, true);
    if (url && !list.includes(url)) list.push(url);
  };
  (Array.isArray(l.photos) ? l.photos : []).forEach(add);
  if (isObj(l.detail) && Array.isArray(l.detail.photos)) l.detail.photos.forEach(add);
  return list;
}

function neighborhoodTier(l) {
  if ([1, 2, 3, 4].includes(l.area_tier)) return l.area_tier;
  if (isNum(l.area_id) && tree.byId.has(l.area_id)) return tierInfo(l.area_id).tier;
  return null;
}

// ---------------------------------------------------------------- sidebar: shared controls

function field(label, control, opts) {
  const o = opts || {};
  const labelEl = o.for ? h('label', { class: 'field-label', for: o.for }, label) : h('span', { class: 'field-label' }, label);
  return h('div', { class: 'field' },
    h('div', { class: 'field-head' }, labelEl, o.value || null),
    control,
    o.hint ? h('p', { class: 'field-hint' }, o.hint) : null);
}

function segmentedControl(name, options, value, onPick, ariaLabel) {
  const group = uid(name);
  const wrap = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': ariaLabel });
  const inputs = [];
  for (const [val, text] of options) {
    const id = uid(name);
    const input = h('input', { type: 'radio', class: 'seg-input', name: group, id, value: String(val) });
    input.checked = Number(val) === Number(value);
    input.addEventListener('change', () => { if (input.checked) onPick(val); });
    inputs.push(input);
    wrap.append(input, h('label', { class: 'seg-btn', for: id }, text));
  }
  wrap.setValue = (v) => inputs.forEach((i) => { i.checked = Number(i.value) === Number(v); });
  return wrap;
}

function checkbox(label, checked, onChange, hint) {
  const id = uid('check');
  const input = h('input', { type: 'checkbox', class: 'check-input', id });
  input.checked = Boolean(checked);
  input.addEventListener('change', () => onChange(input.checked));
  return h('div', { class: 'check' }, input,
    h('label', { for: id }, label, hint ? h('span', { class: 'check-hint' }, hint) : null));
}

// A number box that commits on "change" (Enter, blur, or the arrows) and snaps to its bounds and step.
// An empty or invalid entry goes back to `opts.current()`, the value in the state.
function numberInput(opts, value, onCommit) {
  const input = h('input', {
    type: 'number', class: 'input num', id: opts.id, min: String(opts.min), max: String(opts.max),
    step: String(opts.step || 1), inputmode: 'numeric', 'aria-label': opts.label,
  });
  input.value = String(value);
  input.addEventListener('change', () => {
    const current = opts.current ? opts.current() : opts.min;
    const v = toStep(input.value, opts.min, opts.max, opts.step || 1, current);
    input.value = String(v);
    onCommit(v);
  });
  return input;
}

// ---------------------------------------------------------------- sidebar: limits

const areaRows = new Map();

function buildLimits() {
  const body = $('#limits-body');
  areaRows.clear();
  const walkValue = h('span', { class: 'field-value' });
  const sqftId = uid('sqft');
  const setLimit = (key) => (v) => { state.limits[key] = v; changed('limits'); };
  body.replaceChildren(
    h('div', { class: 'section-tools' },
      h('p', { class: 'hint' }, 'A listing that fails a limit is hidden.'),
      isObj(state.config.default_limits) ? h('button', { type: 'button', class: 'link-btn', onclick: resetLimits }, 'Reset limits') : null),
    field('Monthly rent', rentControl()),
    field('Bedrooms', bedsControl()),
    field('Bathrooms, at least', segmentedControl('baths', BATHS_OPTIONS, state.limits.baths_min, setLimit('baths_min'), 'Minimum bathrooms')),
    field('Size, at least', h('div', { class: 'with-unit' },
      numberInput({ id: sqftId, min: 0, max: 20000, step: 50, current: () => state.limits.sqft_min }, state.limits.sqft_min, setLimit('sqft_min')),
      h('span', { class: 'unit' }, 'ft²'), h('span', { class: 'unit-hint' }, '0 means any size')), { for: sqftId }),
    field('Move-in window', moveInControl()),
    field('Areas', areaTreeControl(), { hint: 'Checking an area selects every area inside it.' }),
    field('Lowest neighborhood tier', segmentedControl('max-tier', TIER_OPTIONS, state.limits.max_tier, setLimit('max_tier'), 'Lowest neighborhood tier to include'),
      { hint: 'Hides areas with a worse tier. You set the tiers under Neighborhood tiers.' }),
    field('Walk to the subway, at most', walkControl(walkValue), { value: walkValue }),
    checkbox('No ground floor', state.limits.no_ground_floor, setLimit('no_ground_floor')),
    field('Must have', amenitiesControl()),
    field('Sources', sourcesControl()),
    checkbox('Rank on net effective rent', state.limits.use_net_effective, setLimit('use_net_effective'), 'Uses the rent after free months.'),
  );
  syncAreaTree();
}

function resetLimits() {
  state.limits = normalizeLimits(clone(state.config.default_limits));
  buildLimits();
  syncTierEditor();
  changed('limits');
}

function rentControl() {
  const lim = () => state.limits;
  const minNum = numberInput({ id: uid('rent'), min: PRICE_MIN, max: PRICE_MAX, step: PRICE_STEP, current: () => lim().price_min, label: 'Minimum rent in dollars' },
    lim().price_min, (v) => { lim().price_min = v; if (lim().price_max < v) lim().price_max = v; sync(); changed('limits'); });
  const maxNum = numberInput({ id: uid('rent'), min: PRICE_MIN, max: PRICE_MAX, step: PRICE_STEP, current: () => lim().price_max, label: 'Maximum rent in dollars' },
    lim().price_max, (v) => { lim().price_max = v; if (lim().price_min > v) lim().price_min = v; sync(); changed('limits'); });
  const range = (label) => h('input', {
    type: 'range', class: 'dual-input', min: String(PRICE_MIN), max: String(PRICE_MAX), step: String(PRICE_STEP), 'aria-label': label,
  });
  const minRange = range('Minimum rent');
  const maxRange = range('Maximum rent');
  const fill = h('span', { class: 'dual-fill' });
  function sync() {
    const lo = lim().price_min;
    const hi = lim().price_max;
    minNum.value = String(lo);
    maxNum.value = String(hi);
    minRange.value = String(lo);
    maxRange.value = String(hi);
    const span = PRICE_MAX - PRICE_MIN;
    // The thumbs travel 8 px in from each end (half a thumb), so the fill uses the same inset.
    fill.style.left = `calc(8px + (100% - 16px) * ${(lo - PRICE_MIN) / span})`;
    fill.style.right = `calc(8px + (100% - 16px) * ${1 - (hi - PRICE_MIN) / span})`;
    minRange.classList.toggle('is-top', lo > PRICE_MAX - PRICE_STEP * 20);
    minRange.setAttribute('aria-valuetext', fmtMoney(lo));
    maxRange.setAttribute('aria-valuetext', fmtMoney(hi));
  }
  minRange.addEventListener('input', () => { lim().price_min = Math.min(Number(minRange.value), lim().price_max); sync(); changed('limits'); });
  maxRange.addEventListener('input', () => { lim().price_max = Math.max(Number(maxRange.value), lim().price_min); sync(); changed('limits'); });
  sync();
  const money = (input) => h('span', { class: 'money' }, h('span', { class: 'money-sign', 'aria-hidden': 'true' }, '$'), input);
  return h('div', { class: 'rent' },
    h('div', { class: 'pair' }, money(minNum), h('span', { class: 'pair-sep' }, 'to'), money(maxNum)),
    h('div', { class: 'dual' }, h('span', { class: 'dual-track' }), fill, minRange, maxRange));
}

function bedsControl() {
  let minSeg = null;
  let maxSeg = null;
  minSeg = segmentedControl('beds-min', BEDS_OPTIONS, state.limits.beds_min, (v) => {
    state.limits.beds_min = v;
    if (state.limits.beds_max < v) { state.limits.beds_max = v; maxSeg.setValue(v); }
    changed('limits');
  }, 'Minimum bedrooms');
  maxSeg = segmentedControl('beds-max', BEDS_OPTIONS, state.limits.beds_max, (v) => {
    state.limits.beds_max = v;
    if (state.limits.beds_min > v) { state.limits.beds_min = v; minSeg.setValue(v); }
    changed('limits');
  }, 'Maximum bedrooms');
  return h('div', { class: 'stack' },
    h('div', { class: 'seg-row' }, h('span', { class: 'seg-row-label' }, 'Min'), minSeg),
    h('div', { class: 'seg-row' }, h('span', { class: 'seg-row-label' }, 'Max'), maxSeg));
}

function moveInControl() {
  const from = h('input', { type: 'date', class: 'input date', 'aria-label': 'Earliest move-in date' });
  const by = h('input', { type: 'date', class: 'input date', 'aria-label': 'Latest move-in date' });
  const sync = () => {
    from.value = state.limits.move_in_from || '';
    by.value = state.limits.move_in_by || '';
    from.max = state.limits.move_in_by || '';
    by.min = state.limits.move_in_from || '';
  };
  const commit = (key, input) => {
    if (!input.value) { sync(); return; } // The window needs both dates: keep the last complete one.
    const lim = state.limits;
    lim[key] = input.value;
    if (lim.move_in_from && lim.move_in_by && lim.move_in_from > lim.move_in_by) {
      if (key === 'move_in_from') lim.move_in_by = lim.move_in_from;
      else lim.move_in_from = lim.move_in_by;
    }
    sync();
    changed('limits');
  };
  from.addEventListener('change', () => commit('move_in_from', from));
  by.addEventListener('change', () => commit('move_in_by', by));
  sync();
  return h('div', { class: 'stack' },
    h('div', { class: 'pair' }, from, h('span', { class: 'pair-sep' }, 'to'), by),
    checkbox('Only listings with a known move-in date inside the window', state.limits.strict_move_in,
      (v) => { state.limits.strict_move_in = v; changed('limits'); }));
}

function areaTreeControl() {
  if (!tree.roots.length) return h('p', { class: 'field-hint' }, 'The server sent no area list.');
  const make = (area, depth) => {
    const kids = tree.children.get(area.id) || [];
    const cb = h('input', { type: 'checkbox', class: 'area-check', id: uid('area') });
    cb.addEventListener('change', () => toggleArea(area.id, cb.checked));
    const row = h('div', { class: 'area-row' });
    let list = null;
    if (kids.length) {
      list = h('ul', { class: 'area-children', hidden: true });
      const toggle = h('button', { type: 'button', class: 'tree-toggle', 'aria-expanded': 'false', 'aria-label': `Show the areas in ${area.name}` });
      toggle.addEventListener('click', () => {
        const open = list.hidden;
        list.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', `${open ? 'Hide' : 'Show'} the areas in ${area.name}`);
      });
      row.append(toggle);
      for (const kid of kids) list.append(make(kid, depth + 1));
    } else {
      row.append(h('span', { class: 'tree-spacer', 'aria-hidden': 'true' }));
    }
    const count = depth === 0 ? h('span', { class: 'area-count' }) : null;
    append(row, [cb, h('label', { class: 'area-label', for: cb.id }, area.name), count]); // `count` may be null.
    areaRows.set(area.id, { cb, row, count });
    return h('li', { class: 'area-node' }, row, list);
  };
  return h('ul', { class: 'area-tree' }, tree.roots.map((root) => make(root, 0)));
}

// A checked area covers its subtree: children show as checked and disabled.
function syncAreaTree() {
  const sel = selectedAreas();
  for (const [id, r] of areaRows) {
    const explicit = sel.has(id);
    const via = explicit ? undefined : ancestors(id).find((a) => sel.has(a));
    const inherited = via !== undefined;
    r.cb.checked = explicit || inherited;
    r.cb.disabled = inherited;
    r.cb.indeterminate = !r.cb.checked && (tree.desc.get(id) || []).some((d) => sel.has(d));
    r.row.classList.toggle('is-inherited', inherited);
    r.row.title = inherited ? `Included with ${tree.byId.get(via).name}` : '';
    if (r.count) {
      const all = tree.desc.get(id) || [];
      const covered = all.filter((d) => coveredBy(d, sel)).length;
      r.count.textContent = explicit ? 'All' : covered ? `${fmtInt(covered)} of ${fmtInt(all.length)}` : 'None';
    }
  }
}

// Store only the highest checked ids: checking an area drops its descendants from the list.
function toggleArea(id, on) {
  const sel = selectedAreas();
  if (on) {
    sel.add(id);
    for (const d of tree.desc.get(id) || []) sel.delete(d);
  } else {
    sel.delete(id);
  }
  state.limits.areas = Array.from(sel).sort((a, b) => a - b);
  syncAreaTree();
  syncTierEditor();
  changed('limits');
}

function walkControl(valueEl) {
  const input = h('input', { type: 'range', class: 'range', min: '1', max: '20', step: '1', 'aria-label': 'Maximum walk to the subway in minutes' });
  input.value = String(state.limits.max_walk_min);
  const sync = () => {
    valueEl.textContent = `${input.value} min`;
    input.setAttribute('aria-valuetext', `${input.value} minutes`);
    setRangeFill(input);
  };
  input.addEventListener('input', () => { state.limits.max_walk_min = Number(input.value); sync(); changed('limits'); });
  sync();
  return input;
}

function amenitiesControl() {
  if (!state.amenities.length) return h('p', { class: 'field-hint' }, 'The server sent no amenity filters.');
  return h('div', { class: 'check-grid' }, state.amenities.map((a) => checkbox(isText(a.label) ? a.label : a.id,
    state.limits.must_have.includes(a.id), (on) => {
      const set = new Set(state.limits.must_have);
      if (on) set.add(a.id);
      else set.delete(a.id);
      state.limits.must_have = Array.from(set);
      changed('limits');
    })));
}

function sourcesControl() {
  const toggleSource = (id, on) => {
    const set = new Set(state.limits.sources);
    if (on) set.add(id);
    else set.delete(id);
    state.limits.sources = SOURCE_OPTIONS.map(([key]) => key).filter((key) => set.has(key));
    changed('limits');
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'check-row' }, SOURCE_OPTIONS.map(([id, label]) => checkbox(label, state.limits.sources.includes(id), (on) => toggleSource(id, on)))),
    checkbox("Include Zillow buildings with 'from' prices", state.limits.include_building_groups,
      (v) => { state.limits.include_building_groups = v; changed('limits'); }));
}

// ---------------------------------------------------------------- sidebar: priorities

const weightRows = new Map();
const presetButtons = [];
const fmtWeight = (v) => (isNum(v) ? String(v) : '?');

function buildPriorities() {
  const body = $('#priorities-body');
  weightRows.clear();
  presetButtons.length = 0;
  body.replaceChildren();
  append(body, [ // append() skips null: presetsControl() is null when the server sends no presets.
    presetsControl(),
    h('div', { class: 'section-tools' },
      h('p', { class: 'hint' }, 'Each slider sets how much a criterion counts. 0 ignores it.'),
      h('button', { type: 'button', class: 'link-btn', onclick: () => setWeights(defaultWeights()) }, 'Reset')),
  ]);
  for (const [pass, title] of [[1, 'From search data'], [2, 'From photos — needs Inspect']]) {
    const items = state.criteria.filter((c) => passOf(c) === pass);
    if (items.length) body.append(h('h3', { class: 'group-title' }, title), h('div', { class: 'weights' }, items.map(weightRow)));
  }
  syncWeights();
}

// "Balanced" goes first: it is the mode where you set only limits and the tool weighs the rest.
function presetsControl() {
  if (!state.presets.length) return null;
  const ordered = [...state.presets].sort((a, b) => Number(b.id === 'balanced') - Number(a.id === 'balanced'));
  return h('div', { class: 'presets', role: 'group', 'aria-label': 'Priority presets' }, ordered.map((preset) => {
    const btn = h('button', {
      type: 'button', class: 'pill', title: isText(preset.help) ? preset.help : null, 'aria-pressed': 'false',
      onclick: () => setWeights({ ...state.weights, ...preset.weights }),
    }, isText(preset.label) ? preset.label : preset.id);
    presetButtons.push({ btn, preset });
    return btn;
  }));
}

const LIMIT_LABELS = {
  price_min: 'Minimum rent', price_max: 'Maximum rent', beds_min: 'Minimum bedrooms', beds_max: 'Maximum bedrooms',
  baths_min: 'Minimum bathrooms', sqft_min: 'Minimum size', move_in_from: 'Move-in from', move_in_by: 'Move-in by',
  strict_move_in: 'Require a known move-in date', areas: 'Areas', max_tier: 'Lowest neighborhood tier',
  max_walk_min: 'Maximum subway walk', no_ground_floor: 'No ground floor', must_have: 'Must-haves',
  sources: 'Sources', include_building_groups: 'Include building groups', use_net_effective: 'Use net effective rent',
};

const preferenceSnapshot = () => clone({ limits: state.limits, weights: state.weights, tiers: state.tiers });
const preferenceSignature = () => JSON.stringify(preferenceSnapshot());

function preferenceValue(group, key, value) {
  if (value === null || value === undefined) return 'Any';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (group === 'weights') return `${value}/10`;
  if (group === 'tiers') return `Tier ${value}`;
  if (key.startsWith('price_')) return fmtMoney(value);
  if (key === 'sqft_min') return `${fmtInt(value)} ft²`;
  if (key === 'max_walk_min') return `${value} min`;
  if (key === 'beds_max' && value === 4) return '4+';
  if (Array.isArray(value)) {
    return value.map((v) => key === 'areas' ? (tree.byId.get(Number(v)) || {}).name || v
      : key === 'sources' ? SITE_NAMES[v] || v : (state.amenities.find((a) => a.id === v) || {}).label || v).join(', ') || 'None';
  }
  return String(value);
}

function applyPreferences(next) {
  state.limits = clone(next.limits);
  state.weights = clone(next.weights);
  state.tiers = clone(next.tiers);
  buildLimits();
  syncWeights();
  syncTierEditor();
  ['limits', 'weights', 'tiers'].forEach(changed);
}

function describeControl() {
  const text = h('textarea', {
    id: 'search-description', class: 'input textarea', rows: '4', maxlength: '2000',
    placeholder: 'A 1-bedroom in Chelsea or West Village, under $6,500. Lots of light matters most; I don’t need a doorman.',
    'aria-describedby': 'search-description-hint',
  });
  const button = h('button', { type: 'button', class: 'btn btn-outline btn-small' }, 'Preview changes');
  const apply = h('button', { type: 'button', class: 'btn btn-primary btn-small', hidden: true }, 'Apply changes');
  const undo = h('button', { type: 'button', class: 'btn btn-outline btn-small', hidden: true }, 'Undo');
  const result = h('p', { class: 'describe-result', hidden: true, role: 'status', 'aria-live': 'polite' });
  const preview = h('div', { class: 'preference-preview', hidden: true });
  let proposed = null;
  let before = null;
  let appliedSignature = null;
  let requestId = 0;
  const show = (message, level) => {
    result.textContent = message;
    result.className = `describe-result is-${level}`;
    result.hidden = false;
  };
  const invalidate = () => {
    requestId += 1;
    proposed = null;
    apply.hidden = true;
    preview.hidden = true;
    result.hidden = true;
  };
  text.addEventListener('input', invalidate);
  const run = async () => {
    if (button.disabled) return;
    const value = text.value.trim();
    if (!value) {
      show('Describe what you want to change first.', 'error');
      text.focus();
      return;
    }
    invalidate();
    const seq = requestId;
    const base = preferenceSnapshot();
    const signature = JSON.stringify(base);
    button.disabled = true;
    button.textContent = 'Reading your request…';
    button.setAttribute('aria-busy', 'true');
    try {
      const res = await api('/api/preferences', { text: value, ...base });
      if (seq !== requestId) return;
      if (signature !== preferenceSignature()) {
        show('Your settings changed while the request was being read. Preview again to use the latest settings.', 'info');
        return;
      }
      if (!isObj(res.limits) || !isObj(res.weights) || !isObj(res.tiers) || !Array.isArray(res.changes)) {
        throw new Error('The server returned an invalid preview. Nothing changed.');
      }
      proposed = { result: res, base, signature };
      const rows = res.changes.map((c) => {
        const label = c.group === 'weights' ? criterionLabel(c.id)
          : c.group === 'tiers' ? (tree.byId.get(Number(c.id)) || {}).name || c.id : LIMIT_LABELS[c.id] || c.id;
        return h('li', { title: isText(c.evidence) ? `From your request: “${c.evidence}”` : null },
          h('strong', null, label),
          h('span', null, `${preferenceValue(c.group, c.id, c.from)} → ${preferenceValue(c.group, c.id, c.to)}`));
      });
      const notes = Array.isArray(res.notes) ? res.notes.filter(isText) : [];
      preview.replaceChildren(rows.length ? h('ul', { class: 'preference-changes' }, rows) : null,
        notes.length ? h('ul', { class: 'preference-notes' }, notes.map((note) => h('li', null, note))) : null);
      preview.hidden = !rows.length && !notes.length;
      apply.hidden = !rows.length;
      show(rows.length ? `${rows.length} proposed change${rows.length === 1 ? '' : 's'}. Apply to re-rank saved listings.`
        : 'No changes proposed. Try a specific limit or priority.', rows.length ? 'ok' : 'info');
    } catch (error) {
      if (seq === requestId) show(error.message, 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Preview changes';
      button.removeAttribute('aria-busy');
    }
  };
  apply.addEventListener('click', () => {
    if (!proposed) return;
    if (proposed.signature !== preferenceSignature()) {
      apply.hidden = true;
      show('Your settings changed since this preview. Preview again before applying.', 'info');
      return;
    }
    before = proposed.base;
    applyPreferences(proposed.result);
    appliedSignature = preferenceSignature();
    undo.hidden = false;
    apply.hidden = true;
    proposed = null;
    show('Applied to saved listings. Search fetches new listings when you’re ready.', 'ok');
  });
  undo.addEventListener('click', () => {
    if (appliedSignature !== preferenceSignature()) {
      undo.hidden = true;
      show('Settings changed after applying. Undo would overwrite those edits; adjust the controls instead.', 'info');
      return;
    }
    applyPreferences(before);
    undo.hidden = true;
    proposed = null;
    apply.hidden = true;
    preview.hidden = true;
    show('Restored your previous settings.', 'ok');
  });
  button.addEventListener('click', run);
  text.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      run();
    }
  });
  return h('div', { class: 'describe' },
    h('label', { class: 'visually-hidden', for: text.id }, 'Describe your search'), text,
    h('p', { id: 'search-description-hint', class: 'field-hint' },
      'Type or use keyboard dictation. Change limits, priorities, or neighborhood tiers. Search runs only when you click Search.'),
    h('div', { class: 'describe-actions' }, button, apply, undo), result, preview);
}

function weightRow(c) {
  const id = uid('weight');
  const helpId = uid('help');
  const help = isText(c.help) ? c.help : null;
  const input = h('input', { type: 'range', class: 'range', id, min: '0', max: '10', step: '1', 'aria-describedby': help ? helpId : null });
  const out = h('output', { class: 'weight-value', for: id });
  const row = h('div', { class: 'weight-row', title: help },
    h('label', { class: 'weight-label', for: id }, isText(c.label) ? c.label : c.id),
    input,
    out,
    help ? h('span', { class: 'visually-hidden', id: helpId }, help) : null);
  input.addEventListener('input', () => {
    state.weights[c.id] = Number(input.value);
    syncWeight(c.id);
    syncPresets();
    changed('weights');
  });
  weightRows.set(c.id, { input, out, row });
  return row;
}

function syncWeight(id) {
  const r = weightRows.get(id);
  if (!r) return;
  const v = state.weights[id];
  r.input.value = String(v);
  r.out.textContent = String(v);
  r.input.setAttribute('aria-valuetext', `${v} of 10`);
  setRangeFill(r.input);
  r.row.classList.toggle('is-off', v === 0);
}

// A preset is active when every criterion weight equals the preset's weight.
function syncPresets() {
  for (const { btn, preset } of presetButtons) {
    const on = state.criteria.every((c) => Number(preset.weights[c.id]) === state.weights[c.id]);
    btn.classList.toggle('is-on', on);
    btn.setAttribute('aria-pressed', String(on));
  }
}

function syncWeights() {
  for (const id of weightRows.keys()) syncWeight(id);
  syncPresets();
}

function setWeights(next) {
  state.weights = normalizeWeights(next);
  syncWeights();
  changed('weights');
}

// ---------------------------------------------------------------- sidebar: safety

const safetyInputs = new Map();

function buildSafety() {
  const body = $('#safety-body');
  safetyInputs.clear();
  body.replaceChildren(h('p', { class: 'safety-note' },
    'Identical searches reuse saved data for 10 minutes. After a human check or an HTTP block, that site pauses for at least 15 minutes. No automatic retries.'));
  for (const f of SAFETY_FIELDS) {
    if (state.safety[f.key] === undefined) continue;
    const id = uid('safety');
    const input = numberInput({ id, min: f.min, max: f.max, step: 1, current: () => state.safety[f.key] },
      state.safety[f.key], (v) => setSafety(f.key, v));
    safetyInputs.set(f.key, input);
    body.append(h('div', { class: 'safety-row' },
      h('label', { for: id }, f.label),
      h('span', { class: 'with-unit' }, input, f.unit ? h('span', { class: 'unit' }, f.unit) : null)));
  }
  const s = isObj(state.config.settings) ? state.config.settings : null;
  if (s) {
    const facts = [['Chrome mode', s.chrome_mode], ['Text model', s.text_model], ['Photo model', s.vision_model], ['Judgment model', s.typesafe_model]]
      .filter(([, v]) => isText(v));
    if (facts.length) body.append(h('dl', { class: 'fine-print' }, facts.map(([k, v]) => [h('dt', null, k), h('dd', null, v)])));
  }
}

function setSafety(key, v) {
  state.safety[key] = v;
  const input = safetyInputs.get(key);
  if (input) input.value = String(v);
  if (key === 'inspect_top_n') $('#inspect-n').value = String(v);
  changed('safety');
}

// ---------------------------------------------------------------- sidebar: neighborhood tiers

const tierRows = new Map();
const tierGroups = [];

function buildTierEditor() {
  const body = $('#tiers-body');
  tierRows.clear();
  tierGroups.length = 0;
  if (!tree.roots.length) {
    body.replaceChildren(h('p', { class: 'field-hint' }, 'The server sent no area list.'));
    return;
  }
  const filter = h('input', { type: 'search', class: 'input tier-filter', placeholder: 'Find a neighborhood', 'aria-label': 'Find a neighborhood' });
  filter.addEventListener('input', () => applyTierFilter(filter.value));
  const list = h('div', { class: 'tier-list' });
  for (const root of tree.roots) {
    const group = h('div', { class: 'tier-borough', role: 'group', 'aria-label': `Tiers in ${root.name}` });
    const walk = (area, depth) => {
      group.append(tierRow(area, depth));
      for (const kid of tree.children.get(area.id) || []) walk(kid, depth + 1);
    };
    walk(root, 0);
    tierGroups.push({ root, group });
    list.append(group);
  }
  body.replaceChildren(
    h('div', { class: 'section-tools' },
      h('p', { class: 'hint' }, 'Tier 1 is best. An area without its own tier uses its parent’s tier, shown lighter.'),
      h('button', { type: 'button', class: 'link-btn', onclick: resetTiers }, 'Reset tiers')),
    filter,
    list);
  syncTierEditor();
}

function tierRow(area, depth) {
  const buttons = TIER_OPTIONS.map(([t]) => h('button', {
    type: 'button', class: 'tier-btn', dataset: { tier: String(t) }, onclick: () => setAreaTier(area.id, t),
  }, String(t)));
  const row = h('div', { class: `tier-row depth-${Math.min(depth, 4)}` },
    h('span', { class: 'tier-name', style: { paddingLeft: `${depth * 12}px` }, title: area.name }, area.name),
    h('span', { class: 'tier-seg', role: 'group', 'aria-label': `Tier for ${area.name}` }, buttons));
  tierRows.set(area.id, { row, buttons, area, key: area.name.toLowerCase() });
  return row;
}

// Rows for the boroughs that hold a selected area (all boroughs when nothing is selected).
function syncTierEditor() {
  if (!tierRows.size) return;
  for (const [id, r] of tierRows) {
    const info = tierInfo(id);
    r.row.classList.toggle('is-own', info.own);
    for (const b of r.buttons) {
      const t = Number(b.dataset.tier);
      const on = t === info.tier;
      b.classList.toggle('is-on', on && info.own);
      b.classList.toggle('is-inherited', on && !info.own);
      b.setAttribute('aria-pressed', String(on));
      if (!on) b.title = `Set tier ${t} for ${r.area.name}`;
      else if (info.own) b.title = `Tier ${t}, set for ${r.area.name}`;
      else b.title = `Tier ${t}, from ${info.fromName || 'the default'}. Click to set it for ${r.area.name}.`;
    }
  }
  const sel = selectedAreas();
  const inUse = tierGroups.filter(({ root }) => sel.has(root.id) || (tree.desc.get(root.id) || []).some((d) => sel.has(d)));
  for (const g of tierGroups) g.group.hidden = inUse.length > 0 && !inUse.includes(g);
}

function setAreaTier(id, tier) {
  state.tiers[String(id)] = tier;
  syncTierEditor();
  changed('tiers');
}

function resetTiers() {
  const source = isObj(state.config.default_tiers) ? state.config.default_tiers : state.config.tiers;
  state.tiers = normalizeTiers(clone(source));
  syncTierEditor();
  changed('tiers');
}

function applyTierFilter(query) {
  const q = query.trim().toLowerCase();
  for (const r of tierRows.values()) r.row.hidden = q !== '' && !r.key.includes(q);
}

// ---------------------------------------------------------------- list

const cardEls = new Map(); // listing id -> card element, for the cards that are in the page
const TIER_HELP = 'Tiers split the matching listings by rank: the top 10 percent, the next 20, the next 30, and the rest.';

function groupedListings() {
  const groups = { 1: [], 2: [], 3: [], 4: [] };
  for (const l of state.listings) groups[tierOf(l)].push(l);
  return [1, 2, 3, 4].map((t) => [t, groups[t]]);
}

const renderOrder = () => groupedListings().flatMap(([, items]) => items);

function exclusionReasons() {
  const excluded = state.result && isObj(state.result.excluded) ? state.result.excluded : {};
  return Object.entries(excluded).filter(([, n]) => isNum(n) && n > 0).sort((a, b) => b[1] - a[1]);
}

function reasonsTable(reasons) {
  return h('table', { class: 'reasons' }, h('tbody', null, reasons.map(([reason, n]) => h('tr', null,
    h('td', null, reason), h('td', { class: 'num' }, fmtInt(n))))));
}

function renderList() {
  const pane = $('#list');
  cardEls.clear();
  if (!state.result) {
    pane.replaceChildren(state.rankError
      ? h('div', { class: 'empty' }, h('p', { class: 'empty-title' }, 'The listings did not load.'), h('p', null, state.rankError))
      : h('p', { class: 'list-loading' }, 'Loading listings…'));
    return;
  }
  if (!state.listings.length) {
    const counts = isObj(state.result.counts) ? state.result.counts : {};
    pane.replaceChildren(isNum(counts.total) && counts.total > 0 ? noMatchBlock() : emptyBlock());
    return;
  }
  const frag = document.createDocumentFragment();
  let budget = state.renderLimit;
  for (const [tier, items] of groupedListings()) {
    if (!items.length || budget <= 0) continue;
    const shown = items.slice(0, budget);
    budget -= shown.length;
    frag.append(h('section', { class: 'tier-group', 'aria-label': `Tier ${tier}, ${TIER_NAMES[tier]}` },
      h('h2', { class: 'tier-head', title: TIER_HELP },
        h('span', { class: 'tier-swatch', style: { backgroundColor: TIER_COLORS[tier] } }),
        h('span', { class: 'tier-title' }, `Tier ${tier} · ${TIER_NAMES[tier]}`),
        h('span', { class: 'tier-count' }, fmtInt(items.length))),
      h('div', { class: 'cards' }, shown.map(card))));
  }
  const hidden = state.listings.length - Math.min(state.listings.length, state.renderLimit);
  if (hidden > 0) {
    frag.append(h('div', { class: 'show-more' },
      h('button', {
        type: 'button', class: 'btn btn-outline',
        onclick: () => { state.renderLimit += RENDER_STEP; renderList(); },
      }, `Show ${fmtInt(Math.min(hidden, RENDER_STEP))} more`),
      h('span', { class: 'hint' }, `${fmtInt(hidden)} listings not shown yet`)));
  }
  pane.replaceChildren(frag);
}

function emptyBlock() {
  return h('div', { class: 'empty' }, icon(ICON_HOME, 'empty-icon'),
    h('p', { class: 'empty-title' }, 'No listings yet.'),
    h('p', null, 'Set your limits and click Search. The tool opens StreetEasy and Zillow in your Chrome, one page each.'));
}

function noMatchBlock() {
  const reasons = exclusionReasons();
  return h('div', { class: 'empty' },
    h('p', { class: 'empty-title' }, 'No listings match your limits.'),
    h('p', null, 'Loosen a limit in the sidebar. To fetch listings that the last search did not get, run Search.'),
    reasons.length ? reasonsTable(reasons) : null);
}

// ---------------------------------------------------------------- cards

function card(l) {
  const title = listingTitle(l);
  const el = h('article', { class: `card${l.id === state.selectedId ? ' is-selected' : ''}`, 'aria-label': title });
  el.style.setProperty('--tier', TIER_COLORS[tierOf(l)]);
  el.addEventListener('mouseenter', () => hoverMarker(l.id, true));
  el.addEventListener('mouseleave', () => hoverMarker(l.id, false));
  el.append(h('div', { class: 'card-top' }, photoBlock(l, title), infoBlock(l, title)), barsBlock(l));
  const notes = notesBlock(l);
  if (notes) el.append(notes);
  el.append(footBlock(l));
  cardEls.set(l.id, el);
  return el;
}

function photoFallback(text) {
  return h('div', { class: 'photo-fallback' }, icon(ICON_HOME, 'photo-fallback-icon'), h('span', null, text));
}

function photoBlock(l, title) {
  const photos = listingPhotos(l);
  const box = h('div', { class: 'photo' });
  if (!photos.length) {
    box.append(photoFallback('No photo'));
  } else {
    // StreetEasy map records carry one photo until a deep look, so a total like "1/38" would mislead.
    const mapOnly = l.detail_level === 'map' && !isObj(l.detail);
    const total = Math.max(isNum(l.photo_count) ? l.photo_count : 0, photos.length);
    let index = clamp(state.photoIndex.get(l.id) || 0, 0, photos.length - 1);
    const img = h('img', {
      loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer', alt: `Photo of ${title}`, width: '320', height: '200',
    });
    const badge = h('span', { class: 'photo-count' });
    const show = () => {
      box.classList.remove('is-broken');
      img.src = photos[index];
      badge.textContent = mapOnly ? plural(photos.length, 'photo') : `${index + 1}/${total}`;
      state.photoIndex.set(l.id, index);
    };
    img.addEventListener('error', () => box.classList.add('is-broken'));
    box.append(img, photoFallback('Photo did not load'), badge); // CSS shows the fallback only after an error.
    if (photos.length > 1) {
      const step = (d) => { index = (index + d + photos.length) % photos.length; show(); };
      box.append(
        h('button', { type: 'button', class: 'photo-nav is-prev', 'aria-label': 'Previous photo', onclick: () => step(-1) }, '‹'),
        h('button', { type: 'button', class: 'photo-nav is-next', 'aria-label': 'Next photo', onclick: () => step(1) }, '›'));
    }
    show();
  }
  if (l.is_new) box.append(h('span', { class: 'badge-new' }, 'New'));
  return box;
}

function infoBlock(l, title) {
  const url = primaryUrl(l);
  const name = isText(l.building_name) ? l.building_name.trim() : null;
  const building = name && !title.toLowerCase().includes(name.toLowerCase()) ? name : null;
  return h('div', { class: 'card-info' },
    h('div', { class: 'card-head' },
      h('div', { class: 'card-titles' },
        h('h3', { class: 'card-title' }, url
          ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', title: 'Open the listing in a new tab' }, title)
          : title),
        building ? h('p', { class: 'card-building' }, building) : null),
      scoreBlock(l)),
    placeLine(l),
    priceLine(l),
    factsLine(l),
    subwayLine(l));
}

function scoreBlock(l) {
  const score = scoreOf(l);
  const rank = isNum(l.rank) ? l.rank : null;
  const label = score === null ? 'No score yet'
    : `Score ${score} of 100${rank ? `, rank ${fmtInt(rank)} of ${fmtInt(state.listings.length)}` : ''}`;
  return h('div', { class: 'score', title: label },
    h('span', { class: 'visually-hidden' }, label),
    h('span', { class: 'score-num', 'aria-hidden': 'true' }, score === null ? '—' : String(score)),
    rank ? h('span', { class: 'score-rank', 'aria-hidden': 'true' }, `#${fmtInt(rank)}`) : null);
}

// The neighborhood chip shows the user's tier for the area (area_tier), not the ranking tier.
function placeLine(l) {
  const areaName = isText(l.area_name) ? l.area_name.trim() : null;
  const borough = isText(l.borough) ? l.borough.trim() : null;
  const areaTier = neighborhoodTier(l);
  return h('div', { class: 'card-place' },
    h('span', { class: 'place-name', title: [areaName, borough].filter(Boolean).join(', ') || null }, areaName || borough || 'Area unknown'),
    areaTier ? h('span', { class: 'area-tier', title: `Neighborhood tier ${areaTier}, from your tier settings` }, `T${areaTier}`) : null);
}

function priceLine(l) {
  const deal = [];
  if (isNum(l.net_effective) && isNum(l.price) && l.net_effective > 0 && l.net_effective < l.price) deal.push(`net ${fmtMoney(l.net_effective)}`);
  if (isNum(l.months_free) && l.months_free > 0) deal.push(`${plural(l.months_free, 'month')} free`);
  return h('div', { class: 'card-price' },
    h('span', { class: 'price-main' },
      l.price_is_from ? h('span', { class: 'price-from' }, 'from ') : null,
      isNum(l.price) ? fmtMoney(l.price) : 'Price unknown'),
    deal.length ? h('span', { class: 'price-deal', title: isNum(l.lease_months) ? `On a ${fmtInt(l.lease_months)}-month lease` : null }, deal.join(' · ')) : null);
}

function factsLine(l) {
  const items = [];
  if (isNum(l.beds)) items.push(l.beds === 0 ? 'Studio' : plural(l.beds, 'bed'));
  if (isNum(l.baths) && l.baths > 0) items.push(plural(l.baths, 'bath'));
  if (isNum(l.sqft) && l.sqft > 0) items.push(`${fmtInt(l.sqft)} ft²`);
  else if (isNum(l.sqft_estimated) && l.sqft_estimated > 0) {
    items.push(h('span', { title: 'Estimated from bedrooms and bathrooms' }, `~${fmtInt(l.sqft_estimated)} ft²`));
  }
  const floor = floorItem(l);
  if (floor) items.push(floor);
  const available = availabilityItem(l);
  if (available) items.push(available);
  if (isNum(l.units_available) && l.units_available > 0) items.push(`${plural(l.units_available, 'unit')} available`);
  if (l.furnished === true) items.push('Furnished');
  return items.length ? h('ul', { class: 'card-facts' }, items.map((item) => h('li', null, item))) : null;
}

function floorItem(l) {
  if (l.is_penthouse === true) return 'Penthouse';
  const fromPhotos = (n) => h('span', { title: 'Estimated from the photos' },
    n <= 0 ? 'Ground floor (from photos)' : `Floor ~${fmtInt(n)} (from photos)`);
  if (isNum(l.floor)) {
    if (l.floor_source === 'vision') return fromPhotos(l.floor);
    return l.floor === 0 ? 'Ground floor' : `Floor ${fmtInt(l.floor)}`;
  }
  return isNum(l.floor_estimated) ? fromPhotos(l.floor_estimated) : null;
}

function availabilityItem(l) {
  const date = parseDay(l.available_at);
  if (!date) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const by = parseDay(state.limits.move_in_by);
  const late = Boolean(by) && date > by;
  return h('span', { class: late ? 'is-late' : null, title: late ? 'Available after your move-in window' : null },
    date <= today ? 'Available now' : `Available ${fmtDay(date)}`);
}

function subwayLine(l) {
  const s = isObj(l.subway) ? l.subway : null;
  if (!s) return h('div', { class: 'card-subway is-unknown' }, 'No subway data');
  const lines = (Array.isArray(s.lines) ? s.lines : []).filter(isText);
  const nearby = (Array.isArray(l.lines_nearby) ? l.lines_nearby : []).filter((x) => isText(x) && !lines.includes(x));
  const tip = [
    isNum(s.distance_m) && isText(s.station) ? `${fmtInt(s.distance_m)} m to ${s.station}` : null,
    nearby.length ? `Other lines within an 8-minute walk: ${nearby.join(' ')}` : null,
  ].filter(Boolean).join('. ');
  return h('div', { class: 'card-subway', title: tip || null },
    isNum(s.walk_min) ? h('span', { class: 'walk' }, `${Math.max(1, Math.round(s.walk_min))} min`) : null,
    isText(s.station) ? h('span', { class: 'station' }, s.station) : null,
    lines.length ? h('span', { class: 'bullets' }, lines.map((x) => bullet(x))) : null,
    nearby.length ? h('span', { class: 'bullets is-nearby' },
      h('span', { class: 'bullets-plus', 'aria-hidden': 'true' }, '+'), nearby.map((x) => bullet(x, true))) : null);
}

function bullet(line, small) {
  const key = String(line).trim().toUpperCase();
  const color = LINE_COLORS[key] || { bg: '#6B7482', fg: '#FFFFFF' };
  const text = LINE_DISPLAY[key] || key;
  return h('span', {
    class: `bullet${small ? ' is-small' : ''}${text.length > 1 ? ' is-wide' : ''}`,
    style: { backgroundColor: color.bg, color: color.fg }, role: 'img', 'aria-label': `${key} train`, title: `${key} train`,
  }, text);
}

// One small bar per criterion: pass 1 on the first row, pass 2 (photos) on the second. Unknown values are hatched.
function barsBlock(l) {
  const scores = isObj(l.scores) ? l.scores : {};
  const rows = [1, 2].map((pass) => state.criteria.filter((c) => passOf(c) === pass));
  const cols = Math.max(rows[0].length, rows[1].length, 1);
  const wrap = h('div', { class: 'bars' });
  wrap.style.setProperty('--cols', String(cols));
  rows.forEach((items, index) => {
    if (!items.length) return;
    const row = h('div', { class: 'bar-row' }, items.map((c) => barCell(c, scores[c.id])));
    if (index === 1) {
      const status = inspectState(l);
      status.style.gridColumn = cols > items.length ? `span ${cols - items.length}` : '1 / -1';
      row.append(status);
    }
    wrap.append(row);
  });
  return wrap;
}

function barCell(c, value) {
  const known = isNum(value);
  const pct = known ? Math.round(clamp(value, 0, 1) * 100) : null;
  const weight = isNum(state.weights[c.id]) ? state.weights[c.id] : 0;
  const text = `${isText(c.label) ? c.label : c.id}: ${known ? `${pct} of 100` : 'unknown, counts as 50'}. Weight ${weight}.`;
  return h('div', { class: `bar${known ? '' : ' is-unknown'}${weight === 0 ? ' is-off' : ''}`, role: 'img', 'aria-label': text, title: text },
    h('span', { class: 'bar-label', 'aria-hidden': 'true' }, SHORT_LABELS[c.id] || c.label || c.id),
    h('span', { class: 'bar-track', 'aria-hidden': 'true' }, known ? h('span', { class: 'bar-fill', style: { width: `${pct}%` } }) : null));
}

function inspectState(l) {
  const ins = isObj(l.inspection) ? l.inspection : null;
  if (!ins) return h('span', { class: 'inspect-state', title: 'Inspect scores a listing from its photos.' }, 'Not inspected');
  const n = ins.photos_used;
  return h('span', { class: 'inspect-state is-done' }, isNum(n) ? `Inspected · ${plural(n, 'photo')}` : 'Inspected');
}

function obsText(value, skipNone) {
  const raw = Array.isArray(value) ? value.filter(isText).join('; ') : value;
  if (!isText(raw)) return null;
  let text = raw.trim().replace(/\s+/g, ' ');
  if (skipNone && /^(none|no|n\/a|nothing)\.?$/i.test(text)) return null;
  text = text.charAt(0).toUpperCase() + text.slice(1);
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function notesBlock(l) {
  const parts = [];
  const ins = isObj(l.inspection) ? l.inspection : null;
  if (ins) {
    const obs = isObj(ins.observations) ? ins.observations : {};
    const judgments = isObj(ins.judgments) ? ins.judgments : {};
    const p = isObj(judgments.real_unit) && isNum(judgments.real_unit.p) ? judgments.real_unit.p : null;
    if (p !== null && p < 0.5) {
      parts.push(h('p', { class: 'note is-warn', title: `About ${Math.round(p * 100)}% likely that the photos show this unit.` },
        'Photos may not show this unit'));
    }
    const said = [['View', obsText(obs.view)], ['Light', obsText(obs.light)]].filter(([, v]) => v);
    if (said.length) {
      parts.push(h('p', { class: 'note is-obs', title: said.map(([k, v]) => `${k}: ${v}`).join(' ') },
        said.map(([k, v]) => [h('span', { class: 'obs-key' }, k), ` ${v} `])));
    }
    const flags = obsText(obs.red_flags, true);
    if (flags) parts.push(h('p', { class: 'note is-warn' }, `Red flags: ${flags}`));
  }
  const unverified = (Array.isArray(l.unverified_must_have) ? l.unverified_must_have : []).filter(isText);
  if (unverified.length) {
    parts.push(h('p', { class: 'note' }, h('span', { class: 'chip is-muted', title: 'Zillow search cannot filter these amenities. Check the listing.' },
      `Not verified: ${unverified.join(', ')}`)));
  }
  if (isObj(l.detail)) parts.push(detailBlock(l));
  return parts.length ? h('div', { class: 'card-notes' }, parts) : null;
}

function detailBlock(l) {
  const d = l.detail;
  const read = fmtStamp(d.read_at);
  const wrap = h('div', { class: 'detail' },
    h('p', { class: 'detail-head' }, h('span', { class: 'badge' }, 'Deep look done'), read ? h('span', { class: 'hint' }, `Read ${read}`) : null));
  if (isText(d.description)) {
    const full = d.description.trim().replace(/\s+/g, ' ');
    const cut = full.length > DESCRIPTION_PREVIEW ? `${full.slice(0, DESCRIPTION_PREVIEW).replace(/\s+\S*$/, '')}…` : full;
    const open = state.openDetails.has(l.id);
    const text = h('span', null, open ? full : cut);
    const p = h('p', { class: 'detail-text' }, text);
    if (cut !== full) {
      const toggle = h('button', { type: 'button', class: 'link-btn', 'aria-expanded': String(open) }, open ? 'less' : 'more');
      toggle.addEventListener('click', () => {
        const next = !state.openDetails.has(l.id);
        if (next) state.openDetails.add(l.id);
        else state.openDetails.delete(l.id);
        text.textContent = next ? full : cut;
        toggle.textContent = next ? 'less' : 'more';
        toggle.setAttribute('aria-expanded', String(next));
      });
      p.append(' ', toggle);
    }
    wrap.append(p);
  }
  const amenities = (Array.isArray(d.amenities) ? d.amenities : []).filter(isText);
  if (amenities.length) {
    const extra = amenities.length - 16;
    wrap.append(h('ul', { class: 'chips', 'aria-label': 'Amenities' },
      amenities.slice(0, 16).map((a) => h('li', { class: 'chip' }, a)),
      extra > 0 ? h('li', { class: 'chip is-muted' }, `+${extra} more`) : null));
  }
  return wrap;
}

function sourceLinks(l) {
  const urls = listingUrls(l);
  const keys = ['streeteasy', 'zillow', ...Object.keys(urls).filter((k) => k !== 'streeteasy' && k !== 'zillow')];
  const out = [];
  for (const key of keys) {
    const href = safeUrl(urls[key]);
    if (!href) continue;
    const name = SITE_NAMES[key] || key;
    out.push(h('a', { class: 'src-link', href, target: '_blank', rel: 'noopener noreferrer', title: `Open on ${name} in a new tab` }, name));
  }
  return out;
}

function footBlock(l) {
  const links = sourceLinks(l);
  return h('div', { class: 'card-foot' },
    h('div', { class: 'card-links' }, links.length ? links : h('span', { class: 'hint' }, 'No link')),
    h('div', { class: 'card-actions' },
      h('button', { type: 'button', class: 'text-btn js-deep', disabled: isActive(state.job), title: DEEP_TITLE, onclick: () => deepLook(l.id) }, 'Deep look'),
      hasPoint(l)
        ? h('button', { type: 'button', class: 'text-btn', onclick: () => showOnMap(l.id) }, 'Show on map')
        : h('span', { class: 'hint', title: 'This listing has no map point.' }, 'Not on the map')));
}

// ---------------------------------------------------------------- map

let map = null;
let listingLayer = null;
const markers = new Map(); // listing id -> Leaflet circle marker
let hoveredId = null;

const mapVisible = () => Boolean(map) && state.view !== 'list' && $('#map').clientWidth > 0;

function initMap() {
  const el = $('#map');
  const Leaf = window.L;
  if (!Leaf || typeof Leaf.map !== 'function') {
    el.append(h('div', { class: 'map-missing' },
      h('p', { class: 'empty-title' }, 'The map did not load.'),
      h('p', null, 'It needs internet access to unpkg.com and server.arcgisonline.com. The list still works.')));
    return;
  }
  map = Leaf.map(el, { zoomControl: true, maxZoom: TILE_OPTIONS.maxZoom }).setView(MAP_CENTER, MAP_ZOOM);
  Leaf.tileLayer(TILE_BASE_URL, { ...TILE_OPTIONS, attribution: TILE_ATTRIBUTION }).addTo(map);
  Leaf.tileLayer(TILE_LABELS_URL, { ...TILE_OPTIONS }).addTo(map); // Street and place names, above the base.
  map.createPane('stations').style.zIndex = '390'; // Under the listing markers (overlay pane, 400).
  listingLayer = Leaf.layerGroup().addTo(map);
  const stations = stationLayer(Leaf);
  if (stations) {
    stations.addTo(map);
    Leaf.control.layers(null, { 'Subway stations': stations }, { collapsed: false, position: 'topright' }).addTo(map);
  }
  addLegend(Leaf);
  if (typeof ResizeObserver === 'function') new ResizeObserver(onMapResize).observe(el);
}

function onMapResize() {
  if (!map) return;
  map.invalidateSize({ animate: false });
  if (state.fitOnShow && mapVisible()) {
    state.fitOnShow = false;
    fitToListings();
  }
}

function stationLayer(Leaf) {
  const stations = state.stations.filter((s) => isNum(s.lat) && isNum(s.lon));
  if (!stations.length) return null;
  const group = Leaf.layerGroup();
  for (const s of stations) {
    const marker = Leaf.circleMarker([s.lat, s.lon], {
      pane: 'stations', radius: 3, color: '#FFFFFF', weight: 1, opacity: 0.9, fillColor: '#262B33', fillOpacity: 0.9,
    });
    marker.bindTooltip(() => h('span', { class: 'station-tip' },
      h('span', { class: 'station-name' }, isText(s.name) ? s.name : 'Station'),
      h('span', { class: 'bullets' }, (Array.isArray(s.lines) ? s.lines : []).filter(isText).map((x) => bullet(x, true)))),
    { direction: 'top', offset: [0, -4], opacity: 1 });
    group.addLayer(marker);
  }
  return group;
}

function addLegend(Leaf) {
  const Legend = Leaf.Control.extend({
    options: { position: 'topright' }, // Under the layer toggle: the long attribution owns the bottom edge.
    onAdd() {
      const box = h('div', { class: 'map-legend' },
        [1, 2, 3, 4].map((t) => h('span', { class: 'legend-item', title: TIER_NAMES[t] },
          h('span', { class: 'legend-dot', style: { backgroundColor: TIER_COLORS[t] } }), `Tier ${t}`)),
        h('span', { class: 'legend-note' }, 'Bigger dot, higher score'));
      Leaf.DomEvent.disableClickPropagation(box);
      return box;
    },
  });
  new Legend().addTo(map);
}

function markerStyle(l) {
  const score = isNum(l.score) ? clamp(l.score, 0, 1) : 0.5;
  const selected = l.id === state.selectedId;
  const hovered = l.id === hoveredId;
  return {
    radius: 4 + score * 6 + (selected || hovered ? 2.5 : 0),
    color: selected ? '#000000' : hovered ? '#1D232B' : '#FFFFFF',
    weight: selected ? 2.5 : hovered ? 2 : 1.25,
    opacity: 1,
    fillColor: TIER_COLORS[tierOf(l)],
    fillOpacity: 0.92,
  };
}

// Update markers in place so an open popup survives a re-rank.
function renderMarkers() {
  if (!map) return;
  const Leaf = window.L;
  const keep = new Set();
  for (const l of state.listings) {
    if (!hasPoint(l)) continue;
    keep.add(l.id);
    let marker = markers.get(l.id);
    if (!marker) {
      const id = l.id;
      marker = Leaf.circleMarker([l.lat, l.lon], markerStyle(l));
      marker.bindPopup(() => popupContent(state.byId.get(id)), { maxWidth: 300, minWidth: 260, autoPanPadding: [24, 24], className: 'listing-popup' });
      marker.on('click', () => selectListing(id, true));
      marker.addTo(listingLayer);
      markers.set(id, marker);
    } else {
      marker.setLatLng([l.lat, l.lon]);
      marker.setStyle(markerStyle(l));
    }
  }
  for (const [id, marker] of markers) {
    if (keep.has(id)) continue;
    listingLayer.removeLayer(marker);
    markers.delete(id);
  }
  // Tier 1 on top: bring weaker tiers and lower scores to the front first.
  const order = state.listings.filter((l) => markers.has(l.id))
    .sort((a, b) => tierOf(b) - tierOf(a) || (a.score || 0) - (b.score || 0));
  for (const l of order) markers.get(l.id).bringToFront();
  const selected = markers.get(state.selectedId);
  if (selected) selected.bringToFront();
  for (const marker of markers.values()) if (marker.isPopupOpen()) marker.getPopup().update();
}

function refreshMarker(id) {
  const marker = markers.get(id);
  const l = state.byId.get(id);
  if (marker && l) marker.setStyle(markerStyle(l));
}

function hoverMarker(id, on) {
  if (!map) return;
  const prev = hoveredId;
  hoveredId = on ? id : (hoveredId === id ? null : hoveredId);
  if (prev !== null && prev !== hoveredId) refreshMarker(prev);
  if (hoveredId !== null) refreshMarker(hoveredId);
}

function selectListing(id, scroll) {
  const prev = state.selectedId;
  state.selectedId = id;
  if (prev !== null && prev !== id) {
    const prevCard = cardEls.get(prev);
    if (prevCard) prevCard.classList.remove('is-selected');
    refreshMarker(prev);
  }
  refreshMarker(id);
  const marker = markers.get(id);
  if (marker) marker.bringToFront();
  if (scroll) {
    scrollToCard(id);
  } else {
    const el = cardEls.get(id);
    if (el) el.classList.add('is-selected');
  }
}

function scrollToCard(id) {
  let el = cardEls.get(id);
  if (!el) {
    const position = renderOrder().findIndex((l) => l.id === id);
    if (position < 0) return;
    state.renderLimit = Math.max(state.renderLimit, Math.ceil((position + 1) / RENDER_STEP) * RENDER_STEP);
    renderList();
    el = cardEls.get(id);
  }
  if (!el) return;
  el.classList.add('is-selected');
  if (state.view === 'map') return;
  el.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' });
  el.classList.remove('is-flash');
  void el.offsetWidth; // Restart the highlight animation.
  el.classList.add('is-flash');
}

function showOnMap(id) {
  const l = state.byId.get(id);
  if (!l || !hasPoint(l)) return;
  if (!map) {
    setNotice('The map is not available. It needs internet access.', 'error');
    return;
  }
  if (state.view === 'list') setView('split');
  map.invalidateSize({ animate: false });
  selectListing(id, false);
  map.setView([l.lat, l.lon], Math.max(map.getZoom(), 15), { animate: !reducedMotion() });
  const marker = markers.get(id);
  if (marker) marker.openPopup();
}

function fitToListings() {
  if (!map) return;
  if (!mapVisible()) {
    state.fitOnShow = true; // Fit when the map shows again.
    return;
  }
  const points = state.listings.filter(hasPoint).map((l) => [l.lat, l.lon]);
  if (!points.length) return;
  map.invalidateSize({ animate: false });
  map.fitBounds(points, { padding: [32, 32], maxZoom: 15, animate: !reducedMotion() });
}

function popupContent(l) {
  if (!l) return h('p', { class: 'popup-gone' }, 'This listing is no longer in the list.');
  const title = listingTitle(l);
  const photos = listingPhotos(l);
  const photo = h('div', { class: 'popup-photo' });
  if (photos.length) {
    const img = h('img', { decoding: 'async', referrerpolicy: 'no-referrer', alt: `Photo of ${title}` });
    img.addEventListener('error', () => img.replaceWith(photoFallback('Photo did not load')));
    img.src = photos[clamp(state.photoIndex.get(l.id) || 0, 0, photos.length - 1)];
    photo.append(img);
  } else {
    photo.append(photoFallback('No photo'));
  }
  const tier = tierOf(l);
  const score = scoreOf(l);
  const url = primaryUrl(l);
  return h('div', { class: 'popup' }, photo,
    h('div', { class: 'popup-body' },
      h('p', { class: 'popup-title' }, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, title) : title),
      h('p', { class: 'popup-price' }, l.price_is_from ? h('span', { class: 'price-from' }, 'from ') : null, fmtMoney(l.price)),
      h('p', { class: 'popup-meta' },
        h('span', { class: 'rank-chip' }, h('span', { class: 'legend-dot', style: { backgroundColor: TIER_COLORS[tier] } }), `Tier ${tier}`),
        score !== null ? h('span', null, `Score ${score}`) : null,
        isNum(l.rank) ? h('span', null, `#${fmtInt(l.rank)}`) : null),
      h('div', { class: 'popup-links' }, sourceLinks(l),
        h('button', {
          type: 'button', class: 'text-btn',
          onclick: () => { if (state.view === 'map') setView('split'); scrollToCard(l.id); },
        }, 'Show in list'))));
}

function setView(view, save) {
  const v = ['list', 'map', 'split'].includes(view) ? view : 'split';
  state.view = v;
  $('#main').dataset.view = v;
  const radio = $(`#view-${v}`);
  if (radio) radio.checked = true;
  if (save !== false) {
    try {
      window.localStorage.setItem(VIEW_KEY, v);
    } catch (error) {
      // Storage can be off; the view then resets on the next load.
    }
  }
  if (map) {
    map.invalidateSize({ animate: false });
    if (state.fitOnShow && mapVisible()) {
      state.fitOnShow = false;
      fitToListings();
    }
  }
}

function savedView() {
  try {
    return window.localStorage.getItem(VIEW_KEY) || 'split';
  } catch (error) {
    return 'split';
  }
}

// ---------------------------------------------------------------- ranking and settings

let rankSeq = 0;

// Every change: re-rank after 200 ms, save settings after 1 s. Safety changes do not change the ranking.
function changed(kind) {
  dirty.add(kind);
  clearTimeout(timers.settings);
  timers.settings = setTimeout(saveSettings, SETTINGS_DEBOUNCE_MS);
  if (kind !== 'safety') scheduleRank();
  renderWiderNote();
  renderButtons();
}

function scheduleRank(delay) {
  clearTimeout(timers.rank);
  timers.rank = setTimeout(runRank, delay === undefined ? RANK_DEBOUNCE_MS : delay);
}

async function runRank() {
  clearTimeout(timers.rank);
  timers.rank = null;
  rankSeq += 1;
  const seq = rankSeq;
  clearTimeout(timers.slow);
  timers.slow = setTimeout(() => setUpdating(true), SLOW_RANK_MS);
  try {
    const res = await api('/api/rank', { limits: state.limits, weights: state.weights, tiers: state.tiers });
    if (seq === rankSeq) applyRank(res);
  } catch (error) {
    if (seq === rankSeq) {
      state.rankError = error.message;
      setNotice(`The ranking failed: ${error.message}`, 'error', 'rank');
      if (!state.result) renderList();
    }
  } finally {
    if (seq === rankSeq) {
      clearTimeout(timers.slow);
      setUpdating(false);
    }
  }
}

function setUpdating(on) {
  const pane = $('#list');
  pane.classList.toggle('is-updating', on);
  pane.setAttribute('aria-busy', String(on));
  $('#main-note').textContent = on ? 'Updating…' : '';
}

function applyRank(res) {
  state.result = res;
  state.rankError = null;
  state.listings = (Array.isArray(res.listings) ? res.listings : []).filter((l) => isObj(l) && (isText(l.id) || isNum(l.id)));
  state.byId = new Map(state.listings.map((l) => [l.id, l]));
  if (state.selectedId !== null && !state.byId.has(state.selectedId)) state.selectedId = null;
  if (state.notice && state.notice.source === 'rank') state.notice = null;
  renderCounts();
  renderList();
  renderMarkers();
  renderButtons();
  renderStatus();
  if (state.pendingFit) {
    state.pendingFit = false;
    fitToListings();
  }
}

function settingsBody() {
  const body = {};
  for (const key of dirty) body[key] = state[key];
  return body;
}

async function saveSettings() {
  timers.settings = null;
  if (!dirty.size) return;
  const body = settingsBody();
  dirty.clear();
  try {
    await api('/api/settings', body);
    if (state.notice && state.notice.source === 'settings') clearNotice();
  } catch (error) {
    Object.keys(body).forEach((key) => dirty.add(key));
    setNotice(`Your settings were not saved: ${error.message}`, 'error', 'settings');
  }
}

// The page may close inside the 1-second debounce: send the last change with keepalive.
function flushSettingsOnExit() {
  if (!dirty.size) return;
  const body = JSON.stringify(settingsBody());
  dirty.clear();
  fetch('/api/settings', {
    method: 'POST', keepalive: true, body,
    headers: { 'Content-Type': 'application/json', 'X-Hunter-Token': TOKEN },
  }).catch(() => {});
}

// ---------------------------------------------------------------- status line, banner, log, counts

function setNotice(text, level, source) {
  state.notice = { text, level: level || 'info', source: source || null };
  renderStatus();
}

function clearNotice() {
  state.notice = null;
  renderStatus();
}

const levelClass = (level) => (level === 'error' ? 'error' : level === 'warn' || level === 'warning' ? 'warn' : 'info');

function jobEvents(job) {
  if (!job || !isText(job.started)) return state.events.slice(-5);
  return state.events.filter((e) => isText(e.t) && e.t >= job.started);
}

function renderStatus() {
  const job = state.job;
  const active = isActive(job);
  const jobEl = $('#status-job');
  jobEl.hidden = !active;
  if (active) {
    const waiting = job.status === 'waiting_for_user';
    jobEl.classList.toggle('is-waiting', waiting);
    $('#job-text').textContent = isText(job.message) ? job.message
      : waiting ? 'Waiting for you in Chrome' : `${JOB_NAMES[job.kind] || 'Job'} running`;
    const p = isObj(job.progress) ? job.progress : null;
    $('#job-progress').textContent = p && isNum(p.done) && isNum(p.total) && p.total > 0 ? `${fmtInt(p.done)} of ${fmtInt(p.total)}` : '';
    const cancel = $('#btn-cancel');
    cancel.disabled = state.cancelPending;
    cancel.textContent = state.cancelPending ? 'Stopping…' : 'Cancel';
  }
  renderStatusMessage(active);
  renderLog();
}

// Priority: an error or job summary, then the latest event of a running job, then the last search.
function renderStatusMessage(active) {
  const el = $('#status-msg');
  const n = state.notice;
  el.className = 'status-msg';
  if (n) {
    el.classList.add(`is-${n.level}`);
    el.replaceChildren(
      h('span', { class: 'msg-text', title: n.text }, n.text),
      h('button', { type: 'button', class: 'msg-close', 'aria-label': 'Dismiss this message', onclick: clearNotice }, '×'));
    return;
  }
  if (active) {
    const latest = jobEvents(state.job).filter((e) => isText(e.message)).pop();
    const text = latest && latest.message !== state.job.message ? latest.message : '';
    el.replaceChildren(text ? h('span', { class: 'msg-text is-latest', title: text }, text) : '');
    return;
  }
  const idle = state.config ? lastSearchText() : '';
  el.replaceChildren(idle ? h('span', { class: 'msg-text is-idle', title: idle }, idle) : '');
}

// Per-site results from job or run stats: {streeteasy: {found, total, error?}, ...}. Other keys are totals.
function siteStats(stats) {
  if (!isObj(stats)) return [];
  return Object.entries(stats).filter(([, s]) => isObj(s) && isNum(s.found)).map(([site, s]) => {
    const name = SITE_NAMES[site] || site;
    const count = isNum(s.total) ? `${fmtInt(s.found)} of ${fmtInt(s.total)}` : fmtInt(s.found);
    const notes = [];
    if (s.cached_pages) notes.push(`${s.cached_pages} cached page${s.cached_pages === 1 ? '' : 's'}`);
    if (isNum(s.cooldown_until) && s.cooldown_until * 1000 > Date.now()) notes.push('further loads paused');
    if (isText(s.error)) notes.push(s.error);
    return { text: `${name} ${count}${notes.length ? ` (${notes.join('; ')})` : ''}`, error: isText(s.error) };
  });
}

function lastSearchText() {
  const last = state.lastSearch;
  if (!last) return 'No search yet.';
  const when = fmtStamp(last.finished) || fmtStamp(last.started);
  const sites = siteStats(last.stats).map((x) => x.text);
  return `Last search${when ? ` ${when}` : ''}${sites.length ? `: ${sites.join(', ')}` : ''}.`;
}

let logSignature = '';

function renderLog() {
  const events = state.events.slice(-40).reverse();
  const signature = `${state.events.length}|${events.length ? `${events[0].t}${events[0].message}` : ''}`;
  if (signature === logSignature) return;
  logSignature = signature;
  $('#log-panel').replaceChildren(
    h('p', { class: 'dropdown-title' }, 'Recent events'),
    events.length
      ? h('ol', { class: 'log-list' }, events.map((e) => h('li', { class: `log-item is-${levelClass(e.level)}` },
        h('time', { class: 'log-time' }, fmtClock(e.t)),
        h('span', { class: 'log-text' }, isText(e.message) ? e.message : ''))))
      : h('p', { class: 'hint' }, 'No events yet.'));
}

function renderBanner() {
  const job = state.job;
  const show = Boolean(job) && job.status === 'waiting_for_user';
  if (show) {
    const site = SITE_NAMES[job.site] || 'The listing site';
    const what = job.kind === 'deep' ? 'The deep look' : job.kind === 'inspect' ? 'The inspection' : 'The search';
    $('#human-banner-text').textContent = `${site} asks you to confirm you are human. Chrome now shows that tab. `
      + `Complete the check there. ${what} continues by itself.`;
    const wait = state.safety.human_wait_s;
    const where = SITE_NAMES[job.site] || 'that site';
    $('#human-banner-sub').textContent = !isNum(wait) ? ''
      : job.kind === 'deep' ? `If the check is still open after ${fmtSeconds(wait)}, the deep look stops.`
        : `If the check is still open after ${fmtSeconds(wait)}, the tool skips ${where} and keeps the other results.`;
  }
  $('#human-banner').hidden = !show;
}

function renderCounts() {
  const el = $('#counts');
  const res = state.result;
  if (!res) {
    el.hidden = true;
    return;
  }
  const c = isObj(res.counts) ? res.counts : {};
  const shown = isNum(c.shown) ? c.shown : state.listings.length;
  const inspected = isNum(c.inspected) ? c.inspected : state.listings.filter((l) => isObj(l.inspection)).length;
  const reasons = exclusionReasons();
  const sum = reasons.reduce((total, [, n]) => total + n, 0);
  const excluded = sum || (isNum(c.total) ? Math.max(0, c.total - shown) : 0);
  const current = $('details', el);
  const wasOpen = Boolean(current && current.open);
  const sep = () => h('span', { class: 'count-sep', 'aria-hidden': 'true' }, '·');
  const parts = [
    h('span', { class: 'count-main' }, `${fmtInt(shown)} ${shown === 1 ? 'listing matches' : 'listings match'}`), sep(),
    h('span', null, `${fmtInt(inspected)} inspected`), sep(),
  ];
  if (reasons.length) {
    parts.push(h('details', { class: 'dropdown is-right', open: wasOpen },
      h('summary', { class: 'dropdown-toggle', title: 'Show why listings are excluded' }, `${fmtInt(excluded)} excluded`),
      h('div', { class: 'dropdown-panel' }, h('p', { class: 'dropdown-title' }, 'Excluded by your limits'), reasonsTable(reasons))));
  } else {
    parts.push(h('span', null, `${fmtInt(excluded)} excluded`));
  }
  el.replaceChildren(...parts);
  el.hidden = false;
}

function renderWiderNote() {
  $('#wider-note').hidden = !state.config || isActive(state.job) || !limitsWider();
}

function renderButtons() {
  const active = isActive(state.job);
  const busy = active ? 'A job is running. Wait for it or cancel it.' : null;
  const noSources = !state.limits.sources || !state.limits.sources.length;
  const noAreas = !state.limits.areas || !state.limits.areas.length;
  const search = $('#btn-search');
  search.disabled = !state.config || active || noSources || noAreas;
  search.title = busy || (noSources ? 'Turn on StreetEasy or Zillow under Sources first.'
    : noAreas ? 'Select at least one area first.'
      : 'Load one search page on each site in your Chrome and read the listings.');
  const open = state.listings.filter((l) => !isObj(l.inspection)).length;
  const inspect = $('#btn-inspect');
  inspect.disabled = !state.config || active || open === 0;
  inspect.title = busy || (open === 0 ? 'Every listing in the list is inspected.'
    : 'Score the best listings that are not inspected yet from their photos. Loads no StreetEasy or Zillow pages.');
  $('#inspect-n').disabled = !state.config || active;
  for (const b of $$('.js-deep')) b.disabled = active;
}

// ---------------------------------------------------------------- jobs and polling

let pollInFlight = false;

async function startJob(path, body) {
  if (isActive(state.job)) return;
  if (state.notice && state.notice.source !== 'settings') state.notice = null;
  try {
    const res = await api(path, body);
    if (isObj(res.job)) {
      state.job = res.job;
      state.progressDone = null;
    }
  } catch (error) {
    setNotice(error.message, 'error', 'job'); // A 409 means a job already runs: the poll below shows it.
  }
  afterStatusChange();
  startPolling();
}

function doSearch() {
  startJob('/api/search', { limits: state.limits, safety: state.safety });
}

// The top N of the current ranked list that have no inspection yet.
function doInspect() {
  const input = $('#inspect-n');
  const n = toStep(input.value, 1, 60, 1, state.safety.inspect_top_n || 25);
  input.value = String(n);
  const ids = state.listings.filter((l) => !isObj(l.inspection)).slice(0, n).map((l) => l.id);
  if (!ids.length) {
    setNotice('Every listing in the list is inspected.', 'info');
    return;
  }
  startJob('/api/inspect', { ids });
}

function deepLook(id) {
  startJob('/api/deep', { ids: [id], safety: state.safety });
}

async function doCancel() {
  if (!isActive(state.job) || state.cancelPending) return;
  state.cancelPending = true;
  renderStatus();
  try {
    await api('/api/cancel', {});
  } catch (error) {
    state.cancelPending = false;
    setNotice(`Cancel failed: ${error.message}`, 'error', 'job');
  }
  startPolling();
}

function startPolling() {
  if (timers.poll !== null || pollInFlight) return;
  poll();
}

async function poll() {
  timers.poll = null;
  pollInFlight = true;
  let delay = POLL_MS;
  try {
    applyStatus(await api('/api/status'));
    if (state.notice && state.notice.source === 'status') clearNotice();
  } catch (error) {
    delay = POLL_RETRY_MS;
    setNotice(`The status check failed: ${error.message}`, 'error', 'status');
  } finally {
    pollInFlight = false;
  }
  if (isActive(state.job)) timers.poll = setTimeout(poll, delay);
}

function applyStatus(data) {
  const prev = state.job;
  const next = isObj(data.job) ? data.job : null;
  state.events = (Array.isArray(data.events) ? data.events : []).filter(isObj);
  state.chrome = isObj(data.chrome) ? data.chrome : null;
  state.job = next;
  const wasActive = isActive(prev);
  const nowActive = isActive(next);
  if (wasActive && !nowActive) {
    onJobEnded(next && next.id === prev.id ? next : { ...prev, status: 'done' });
  } else if (nowActive) {
    const done = isObj(next.progress) ? next.progress.done : null;
    if (state.progressDone !== null && done !== state.progressDone) scheduleRank(0); // Results arrive while the job runs.
    state.progressDone = done;
  }
  if (!nowActive) {
    state.cancelPending = false;
    state.progressDone = null;
  }
  afterStatusChange();
}

function onJobEnded(job) {
  state.notice = jobSummary(job);
  if (job.kind === 'search') {
    state.pendingFit = true;
    refreshLastSearch();
  }
  runRank();
}

// A search summary uses the per-site stats. Other jobs use their last events (a solved human check
// leaves a stale "waiting" warning in the log, so the summary does not pick warnings by level).
function jobSummary(job) {
  const name = JOB_NAMES[job.kind] || 'The job';
  const message = isText(job.message) ? job.message.trim() : '';
  const events = jobEvents(job).filter((e) => isText(e.message));
  if (job.status === 'failed') {
    const errors = events.filter((e) => levelClass(e.level) === 'error').map((e) => e.message.trim());
    return { text: `${name} failed. ${message || errors.pop() || 'The log has the details.'}`, level: 'error', source: 'job' };
  }
  if (job.status === 'cancelled') return { text: `${name} cancelled.`, level: 'info', source: 'job' };
  const head = message || `${name} finished.`;
  const sites = siteStats(job.stats);
  if (sites.length) {
    return { text: [head, ...sites.map((x) => x.text)].join(' · '), level: sites.some((x) => x.error) ? 'warn' : 'ok', source: 'job' };
  }
  const recent = events.slice(-3).filter((e) => e.message.trim() !== message).slice(-2);
  return {
    text: [head, ...recent.map((e) => e.message.trim())].join(' · '),
    level: recent.some((e) => levelClass(e.level) !== 'info') ? 'warn' : 'ok',
    source: 'job',
  };
}

async function refreshLastSearch() {
  try {
    const cfg = await api('/api/config');
    state.lastSearch = isObj(cfg.last_search) ? cfg.last_search : null;
    renderWiderNote();
    renderStatus();
  } catch (error) {
    // Keep the old value. The next page load reads it again.
  }
}

function afterStatusChange() {
  renderStatus();
  renderBanner();
  renderButtons();
  renderWiderNote();
}

// ---------------------------------------------------------------- page events and start

function bindPage() {
  $('#btn-search').addEventListener('click', doSearch);
  $('#btn-inspect').addEventListener('click', doInspect);
  $('#btn-cancel').addEventListener('click', doCancel);
  $('#inspect-n').addEventListener('change', () => {
    const input = $('#inspect-n');
    const n = toStep(input.value, 1, 60, 1, state.safety.inspect_top_n || 25);
    if (state.safety.inspect_top_n !== undefined) setSafety('inspect_top_n', n);
    else input.value = String(n);
  });
  for (const radio of $$('input[name="view"]')) {
    radio.addEventListener('change', () => { if (radio.checked) setView(radio.value); });
  }
  document.addEventListener('click', (e) => {
    for (const d of $$('details.dropdown[open]')) if (!d.contains(e.target)) d.open = false;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    for (const d of $$('details.dropdown[open]')) {
      d.open = false;
      const summary = $('summary', d);
      if (summary) summary.focus();
    }
  });
  window.addEventListener('pagehide', flushSettingsOnExit);
}

async function boot() {
  bindPage();
  setView(savedView(), false);
  renderButtons();
  renderList();
  let cfg;
  try {
    cfg = await api('/api/config');
  } catch (error) {
    state.rankError = error.message;
    setNotice(`The settings did not load: ${error.message}`, 'error', 'config');
    renderList();
    return;
  }
  applyConfig(cfg);
  $('#inspect-n').value = String(state.safety.inspect_top_n || 25);
  $('#search-prompt-body').replaceChildren(describeControl());
  buildLimits();
  buildPriorities();
  buildTierEditor();
  buildSafety();
  initMap();
  afterStatusChange();
  await runRank();
  startPolling(); // One status check: a job may already run.
}

boot();
