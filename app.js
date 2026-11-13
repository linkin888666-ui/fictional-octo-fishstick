/* BRUCE 5.0: shared rendering, bounded requests, resilient local state. */
'use strict';
const VERSION = '5.0.0';
function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function parseCodes(raw, fallback = []) {
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? [...new Set(parsed.filter(x => typeof x === 'string' && /^[0-9]{4}$/.test(x)))].slice(0, 50) : fallback;
  } catch { return fallback; }
}
function filterStocks(data, options) {
  const {ma, rsi, volume, macd, rsiLimit, volumeLimit} = options;
  if ((rsi && (!Number.isFinite(rsiLimit) || rsiLimit < 50 || rsiLimit > 100)) ||
      (volume && (!Number.isFinite(volumeLimit) || volumeLimit < 0 || volumeLimit > 100))) {
    throw new Error('門檻超出允許範圍，請修正後再套用');
  }
  return Object.keys(data).filter(code => {
    const d = data[code];
    return d && !d.error && !d.loading && (!ma || d.trend_pass === true) &&
      (!rsi || (Number.isFinite(d.rsi5) && d.rsi5 < rsiLimit)) &&
      (!volume || (Number.isFinite(d.volume_ratio) && d.volume_ratio >= volumeLimit)) &&
      (!macd || (Number.isFinite(d.macd_hist) && d.macd_hist > 0));
  });
}
// Pure functions are also exercised by Node's built-in test runner.
if (typeof module !== 'undefined') module.exports = {esc, parseCodes, filterStocks};
if (typeof document !== 'undefined') {
const $ = s => document.querySelector(s);
const defaults = ['1802','1815','1303','2330','2317','2409','3481'];
function readStore(key) { try { return localStorage.getItem(key); } catch { return null; } }
function saveStore(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { toast('此瀏覽器無法儲存偏好；本次操作仍可使用'); }
}
let favorites = new Set(parseCodes(readStore('bruce-favorites')));
let codes = [...new Set([...defaults, ...parseCodes(readStore('bruce-watchlist')), ...favorites])].slice(0, 50);
let data = {}, expanded = new Set(), catalog = {}, activeTab = 'home';
let filtersApplied = false, batchBusy = false, searching = false, toastTimer;
const pending = new Map();
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('#toast').style.display = 'none'; }, 3200);
}
function spark(arr) {
  if (!Array.isArray(arr) || arr.length < 2) return '';
  const low = Math.min(...arr), range = Math.max(...arr) - low || 1;
  const points = arr.map((x, i) => (i * 320 / (arr.length - 1)).toFixed(1) + ',' + (48 - (x - low) / range * 42).toFixed(1)).join(' ');
  return '<svg class="chart" viewBox="0 0 320 54" preserveAspectRatio="none" aria-label="最近30個交易日收盤走勢"><polyline points="' + points + '" fill="none" stroke="#37dfff" stroke-width="2.5"/></svg>';
}
function card(code) {
  const d = data[code], title = esc(catalog[code]?.name || code);
  const remove = defaults.includes(code) ? '' : '<button class="btn" data-remove="' + code + '">移除此股票</button>';
  if (!d || d.loading) return '<article class="panel stock"><strong>' + title + ' ' + code + '</strong><div class="status">正在取得官方資料…</div></article>';
  if (d.error) return '<article class="panel stock err"><strong>' + title + ' ' + code + '</strong><p>行情讀取失敗：' + esc(d.error) + '</p><button class="btn" data-retry="' + code + '">重試此股票</button>' + remove + '</article>';
  const open = expanded.has(code);
  const warnings = (d.data_warnings || []).map(x => '<p class="data-warning">⚠ ' + esc(x) + '</p>').join('');
  return '<article class="panel stock ' + (open ? 'open' : '') + '" data-code="' + code + '">' +
    '<div class="stock-head"><div><h3>' + esc(d.name) + '</h3><small class="muted">' + code + ' · ' + esc(d.date) + ' · ' + esc(d.market) + '</small></div><div><div class="price">' + d.close + '</div><div class="' + (d.change >= 0 ? 'up' : 'down') + '">' + (d.change > 0 ? '+' : '') + d.change + '%</div></div></div>' + warnings +
    '<div class="tags">' + (d.tags || []).map(x => '<span class="tag ' + (x.includes('過熱') ? 'warn' : '') + '">' + esc(x) + '</span>').join('') + '</div>' + spark(d.series) +
    '<div class="stock-actions"><button class="btn" aria-expanded="' + open + '" data-expand="' + code + '">' + (open ? '收起指標' : '查看分析') + '</button><button class="btn" aria-pressed="' + favorites.has(code) + '" data-fav="' + code + '">' + (favorites.has(code) ? '★ 已收藏' : '☆ 收藏') + '</button>' + remove + '</div>' +
    '<div class="detail"><div class="line"></div>技術評分 <strong>' + d.score + '/100</strong> ｜ 量比 ' + d.volume_ratio +
    '<br>5MA ' + d.ma5 + ' ｜ 20MA ' + d.ma20 + '<br>RSI(5) ' + d.rsi5 + ' ｜ RSI(10) ' + d.rsi10 +
    '<br>RSI(10) ≥90 連續 ' + d.rsi10_overheat_days + ' 個交易日' +
    '<br>DIF ' + d.dif + ' ｜ MACD柱（DIF − 訊號線） ' + d.macd_hist +
    '<br>訊號：' + esc((d.alerts || []).join('、') || '無觸發警示') +
    '<br>通過均線趨勢條件：' + (d.trend_pass ? '是' : '否') + ' ｜ 風險 ' + esc(d.risk_level) +
    '<br>近20日收盤區間 ' + d.support20 + ' ～ ' + d.resistance20 +
    '<br>資料 ' + esc(d.data_source) + ' · ' + esc(d.cache) + ' · 歷史 ' + d.history_days + ' 日' +
    '<br><a href="' + esc(d.source_url) + '" target="_blank" rel="noopener noreferrer">核對官方日線來源</a>' +
    '<br><small>未還原權息日線；分數不是勝率，收盤區間不是保證支撐或壓力。</small></div></article>';
}
function filterOptions() {
  return {ma: $('#f-ma').checked, rsi: $('#f-rsi').checked, volume: $('#f-volume').checked, macd: $('#f-macd').checked,
    rsiLimit: $('#f-rsi-limit').value.trim() ? Number($('#f-rsi-limit').value) : NaN,
    volumeLimit: $('#f-volume-limit').value.trim() ? Number($('#f-volume-limit').value) : NaN};
}
function renderFilters() {
  if (!filtersApplied) return;
  try {
    const matches = filterStocks(data, filterOptions());
    const loaded = Object.values(data).filter(d => d && !d.error && !d.loading).length;
    $('#filter-status').textContent = '已分析 ' + loaded + ' 檔，符合 ' + matches.length + ' 檔；未載入與失敗股票不列入。';
    $('#filter-results').innerHTML = matches.map(card).join('') || '<div class="panel info">沒有符合條件的已載入股票。可調整條件，或到雷達頁新增股票。</div>';
  } catch (error) {
    $('#filter-status').textContent = error.message;
    $('#filter-results').innerHTML = '';
  }
}
function render() {
  const valid = Object.values(data).filter(d => d && !d.error && !d.loading);
  $('#count').textContent = valid.length + '/' + codes.length;
  $('#avg').textContent = valid.length ? Math.round(valid.reduce((sum, d) => sum + d.score, 0) / valid.length) : '--';
  $('#strong').textContent = valid.filter(d => d.trend_pass).length;
  const only = $('#favorites-only').checked;
  const visible = codes.filter(c => !only || favorites.has(c));
  $('#home-list').innerHTML = visible.map(card).join('') || '<div class="panel info">目前沒有收藏股票。關閉「只看收藏」以檢視其他股票。</div>';
  const q = $('#search').value.trim().toLowerCase();
  const filtered = visible.filter(c => !q || c.includes(q) || (data[c]?.name || catalog[c]?.name || '').toLowerCase().includes(q))
    .sort((a,b) => (data[b]?.score ?? -1) - (data[a]?.score ?? -1));
  $('#radar-list').innerHTML = filtered.map(card).join('') || '<div class="panel info">沒有符合的已載入股票。輸入代碼或公司簡稱，再按查詢。</div>';
  $('#radar-count').textContent = filtered.length + ' 檔';
  renderFilters();
}
async function getJSON(url, timeout = 60000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {cache:'no-store', signal:controller.signal});
    let result;
    try { result = await response.json(); } catch { throw new Error('伺服器回應格式異常，請稍後重試'); }
    if (!response.ok || result.error) throw new Error(result.error || '服務暫時無法使用（' + response.status + '）');
    return result;
  } catch (error) {
    throw new Error(error.name === 'AbortError' ? '查詢逾時，請稍後按重試' : error.message);
  } finally { clearTimeout(timer); }
}
async function fetchOne(code, refresh = false) {
  if (pending.has(code)) return pending.get(code);
  if (!refresh && data[code] && !data[code].error && !data[code].loading) return data[code];
  const task = (async () => {
    data[code] = {loading:true}; render();
    try {
      const result = await getJSON('/api/stocks?code=' + code + (refresh ? '&refresh=1' : ''));
      if (result.code !== code || !Number.isFinite(result.close) || !Number.isFinite(result.score) || !Array.isArray(result.tags)) {
        throw new Error('行情資料不完整，請稍後重試');
      }
      data[code] = result;
    } catch (error) { data[code] = {error:error.message}; }
    finally { pending.delete(code); render(); }
    return data[code];
  })();
  pending.set(code, task);
  return task;
}
async function load(refresh = false) {
  if (batchBusy) return;
  batchBusy = true;
  const buttons = ['#refresh','#radar-refresh','#settings-refresh'].map($);
  buttons.forEach(b => { b.disabled = true; });
  let complete = 0;
  const queue = [...codes];
  async function worker() {
    while (queue.length) {
      const code = queue.shift();
      await fetchOne(code, refresh);
      complete++;
      $('#status').textContent = '官方日線載入中：' + complete + '/' + codes.length + ' 檔';
    }
  }
  $('#status').textContent = '正在取得官方日線…';
  try { await Promise.all([worker(), worker(), worker()]); }
  finally {
    batchBusy = false; buttons.forEach(b => { b.disabled = false; });
    const valid = codes.filter(c => data[c] && !data[c].error && !data[c].loading).length;
    $('#status').textContent = '載入完成 · ' + valid + '/' + codes.length + ' 檔成功' + (valid < codes.length ? '，失敗股票可單獨重試' : '') + ' · 各卡片標示實際交易日';
    render();
  }
}
function switchTab(tab) {
  activeTab = tab;
  ['home','radar-tab','indicators','settings'].forEach(id => $('#' + id).classList.toggle('hidden', id !== tab));
  document.querySelectorAll('[data-tab]').forEach(b => { b.classList.toggle('active', b.dataset.tab === tab); b.setAttribute('aria-current', b.dataset.tab === tab ? 'page' : 'false'); });
  if (tab === 'indicators') filtersApplied = true;
  render(); window.scrollTo(0, 0);
}
async function lookupStock() {
  if (searching) return;
  const query = $('#search').value.trim();
  let code = query;
  if (!/^[0-9]{4}$/.test(code)) {
    const matches = Object.keys(catalog).filter(c => catalog[c].name.toLowerCase() === query.toLowerCase());
    if (matches.length === 1) code = matches[0];
    else { $('#search-status').textContent = '請輸入4位股票代碼或完整公司簡稱，例如 1815、富喬'; return; }
  }
  if (!codes.includes(code) && codes.length >= 50) { $('#search-status').textContent = '最多載入50檔股票；請先移除不需要的股票'; return; }
  searching = true; $('#search-submit').disabled = true;
  $('#search').value = code;
  if (!codes.includes(code)) codes.push(code);
  if ($('#favorites-only').checked && !favorites.has(code)) {
    $('#favorites-only').checked = false;
    saveStore('bruce-favorites-only', false);
  }
  $('#search-status').textContent = '正在查詢 ' + code + ' 的官方上市／上櫃日線…';
  try {
    const result = await fetchOne(code);
    $('#search-status').textContent = result.error ? '查詢未成功：' + result.error : '已載入 ' + code + ' ' + result.name + '（' + result.market + '），請查看下方結果';
    if (!result.error) saveStore('bruce-watchlist', codes);
  } finally { searching = false; $('#search-submit').disabled = false; }
}
document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.dataset.tab) switchTab(button.dataset.tab);
  if (button.dataset.expand) {
    const code = button.dataset.expand;
    expanded.has(code) ? expanded.delete(code) : expanded.add(code);
    render();
  }
  if (button.dataset.fav) {
    const code = button.dataset.fav;
    favorites.has(code) ? favorites.delete(code) : favorites.add(code);
    saveStore('bruce-favorites', [...favorites]); render(); toast('收藏清單已更新');
  }
  if (button.dataset.retry) fetchOne(button.dataset.retry, true);
  if (button.dataset.remove && !pending.has(button.dataset.remove)) {
    const code = button.dataset.remove;
    codes = codes.filter(c => c !== code); delete data[code]; expanded.delete(code); favorites.delete(code);
    saveStore('bruce-watchlist', codes); saveStore('bruce-favorites', [...favorites]); render();
  }
});
$('#search-submit').onclick = lookupStock;
$('#search').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); lookupStock(); } });
$('#search').oninput = render;
['#refresh','#radar-refresh','#settings-refresh'].forEach(id => { $(id).onclick = () => load(true); });
$('#filter-apply').onclick = () => { filtersApplied = true; renderFilters(); };
$('#filter-reset').onclick = () => {
  $('#f-ma').checked = true;
  ['#f-rsi','#f-volume','#f-macd'].forEach(id => { $(id).checked = false; });
  $('#f-rsi-limit').value = '90'; $('#f-volume-limit').value = '1.2';
  filtersApplied = true; renderFilters();
};
['#f-ma','#f-rsi','#f-volume','#f-macd','#f-rsi-limit','#f-volume-limit'].forEach(id => {
  $(id).addEventListener('change', () => { filtersApplied = true; renderFilters(); });
});
$('#favorites-only').checked = readStore('bruce-favorites-only') === 'true';
$('#favorites-only').onchange = () => { saveStore('bruce-favorites-only', $('#favorites-only').checked); render(); };
const reduced = readStore('bruce-motion') === 'false' || matchMedia('(prefers-reduced-motion: reduce)').matches;
$('#motion').checked = !reduced; document.body.classList.toggle('reduce-motion', reduced);
$('#motion').onchange = e => { document.body.classList.toggle('reduce-motion', !e.target.checked); saveStore('bruce-motion', e.target.checked); };
async function bootstrap() {
  render();
  getJSON('/health', 15000).then(d => {
    $('#server-version').textContent = '前端 ' + VERSION + ' ｜ 服務 ' + d.version;
    if (d.version !== VERSION) toast('前後端版本不同，請重新整理或等待部署完成');
  }).catch(() => { $('#server-version').textContent = '無法確認服務狀態，請稍後重新整理'; });
  try {
    const result = await getJSON('/api/catalog', 15000);
    catalog = result.stocks || {};
    $('#catalog-date').textContent = '公司名錄更新：' + (result.fetched_at || '未知').slice(0,10) + ' · ' + Object.keys(catalog).length + ' 家';
    $('#stock-catalog').innerHTML = Object.keys(catalog).map(code => '<option value="' + code + '">' + esc(catalog[code].name) + ' · ' + catalog[code].market + '</option>').join('');
  } catch { $('#catalog-date').textContent = '公司名錄暫時無法取得；仍可用4位代碼查詢'; }
  const initial = new URLSearchParams(location.search).get('stock');
  if (initial && /^[0-9]{4}$/.test(initial)) {
    $('#search').value = initial; switchTab('radar-tab');
    if (!codes.includes(initial)) codes.push(initial);
    lookupStock();
  }
  await load();
}
bootstrap();
}
