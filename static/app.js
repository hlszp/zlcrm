/* 工厂 CRM 前端（原生 JS，hash 路由） */
'use strict';

let ME = null;
let DICTS = {};
const charts = {};

const dictLabels = code => (DICTS[code]?.items || []).filter(i => i.active).map(i => i.label);
const statusOptions = (type, cur) => dictLabels('contract_status_' + type)
  .map(s => `<option ${cur === s ? 'selected' : ''}>${s}</option>`).join('');

/* ---------------- 基础工具 ---------------- */
async function api(url, opts = {}) {
  if (opts.body && typeof opts.body !== 'string' && !(opts.body instanceof FormData)) {
    opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch(url, opts);
  if (r.status === 401) { location.href = '/login.html'; throw new Error('unauthorized'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `请求失败(${r.status})`);
  return j;
}
const get = u => api(u);
const post = (u, b) => api(u, { method: 'POST', body: b || {} });
const put = (u, b) => api(u, { method: 'PUT', body: b || {} });
const del = u => api(u, { method: 'DELETE' });

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = n => '¥' + Number(n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const h = html => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };

function toast(msg, ok = true) {
  const el = h(`<div style="position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:999;
    padding:10px 22px;border-radius:8px;color:#fff;background:${ok ? '#12b76a' : '#d92d20'};box-shadow:0 4px 16px rgba(0,0,0,.2)">${esc(msg)}</div>`);
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

function openModal(title, bodyHtml, wide) {
  const root = document.getElementById('modalRoot');
  root.innerHTML = '';
  const mask = h(`<div class="modal-mask"><div class="modal${wide ? ' wide' : ''}">
    <div class="modal-head"><h3>${esc(title)}</h3><button class="modal-close">×</button></div>
    <div class="modal-body"></div></div></div>`);
  mask.querySelector('.modal-body').append(typeof bodyHtml === 'string' ? h(`<div>${bodyHtml}</div>`) : bodyHtml);
  const close = () => { root.innerHTML = ''; };
  mask.querySelector('.modal-close').onclick = close;
  mask.onclick = e => { if (e.target === mask) close(); };
  root.appendChild(mask);
  return { el: mask, close };
}

function confirmDo(msg, fn) {
  const { el, close } = openModal('确认操作', `<p style="margin-bottom:8px">${esc(msg)}</p>
    <div class="form-actions"><button class="btn" id="cNo">取消</button><button class="btn btn-danger" id="cYes">确认</button></div>`);
  el.querySelector('#cNo').onclick = close;
  el.querySelector('#cYes').onclick = async () => { close(); await fn(); };
}

function statusTag(s) {
  const map = { '草拟': 'gray', '已签': 'blue', '履约中': 'orange', '已完成': 'green', '已归档': 'gray' };
  return `<span class="tag tag-${map[s] || 'gray'}">${esc(s)}</span>`;
}
function planStateTag(p) {
  const map = { '已收': 'green', '部分': 'orange', '待收': 'blue', '已逾期': 'red', '即将到期': 'orange', '未到期': 'gray' };
  return `<span class="tag tag-${map[p.state] || 'gray'}">${esc(p.state)}</span>`;
}

function makeChart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  const el = document.getElementById(id);
  if (el && window.Chart) charts[id] = new Chart(el, cfg);
}

/* ---------------- 路由 ---------------- */
const ROUTES = {
  dashboard: { title: '仪表盘', render: renderDashboard },
  customers: { title: '客户管理', render: renderCustomers },
  contracts: { title: '合同管理', render: renderContracts },
  shipments: { title: '发货管理', render: renderShipments },
  production: { title: '生产协同', render: renderProduction },
  process:   { title: '工艺寻优', render: renderProcess },
  plans:     { title: '回款管理', render: renderPlans },
  invoices:  { title: '开票台账', render: renderInvoices },
  products:  { title: '产品管理', render: renderProducts },
  services:  { title: '服务管理', render: renderServices },
  reminders: { title: '到期提醒', render: renderReminders },
  settings:  { title: '系统设置', render: renderSettings },
  analytics: { title: '数据分析', render: renderAnalytics },
  reports:   { title: '统计报表', render: renderReports },
  admin:     { title: '用户管理', render: renderAdmin },
};

function route() {
  const name = (location.hash.replace('#/', '') || 'dashboard').split('?')[0];
  const r = ROUTES[name] || ROUTES.dashboard;
  document.getElementById('pageTitle').textContent = r.title;
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('active', a.dataset.route === name));
  document.getElementById('sidebar').classList.remove('open');
  const view = document.getElementById('view');
  view.innerHTML = '<div class="loading">加载中…</div>';
  r.render(view).catch(e => { view.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; });
}

/* ---------------- 仪表盘 ---------------- */
async function renderDashboard(view) {
  const d = await get('/api/stats/dashboard');
  const links = [];
  if (ME.role === 'admin') {
    links.push(['👔 老板视角', '#/analytics?tab=boss', '签约 · 回款 · 欠款全景']);
    links.push(['移动端驾驶舱', '/mobile', '手机查看回款、逾期与交付风险']);
  }
  if (['admin', 'manager'].includes(ME.role)) links.push(['🏭 工厂视角', '#/analytics?tab=plant', '在手合同 · 待发货 · 交付预警']);
  if (['admin', 'finance'].includes(ME.role)) links.push(['💼 财务视角', '#/analytics?tab=finance', '回款达成 · 逾期 · 开票']);
  links.push(['📊 统计报表', '#/reports', '筛选统计 · 导出 Excel']);
  view.innerHTML = `
    <div class="entry-grid">${links.map(([t, href, desc]) =>
      `<a class="entry-card" href="${href}"><div class="entry-title">${t}</div><div class="entry-desc">${desc}</div></a>`).join('')}</div>
    <div class="stat-grid">
      <div class="stat-card"><div class="label">本月新签合同</div><div class="value">${money(d.signed_amount)}</div><div class="label">${d.signed_count} 份</div></div>
      <div class="stat-card"><div class="label">本月已回款</div><div class="value green">${money(d.received_month)}</div></div>
      <div class="stat-card"><div class="label">应收未收总额</div><div class="value red">${money(d.outstanding)}</div></div>
      <div class="stat-card"><div class="label">逾期未收</div><div class="value red">${money(d.overdue_amount)}</div><div class="label">${d.overdue_count} 笔</div></div>
      <div class="stat-card"><div class="label">未开票金额</div><div class="value">${money(d.uninvoiced)}</div></div>
      <div class="stat-card"><div class="label">未排期应收</div><div class="value ${d.unscheduled > 0 ? 'red' : ''}">${money(d.unscheduled)}</div><div class="label">需补回款计划</div></div>
      <div class="stat-card"><div class="label">待核销收款</div><div class="value">${money(d.unallocated)}</div><div class="label">未分配回款期次</div></div>
      <div class="stat-card"><div class="label">客户总数</div><div class="value">${d.customers}</div></div>
    </div>
    <div class="grid-2">
      <div class="card"><h3>近 12 个月回款趋势</h3><div class="chart-box"><canvas id="chTrend"></canvas></div></div>
      <div class="card"><h3>未来各月预计回款</h3><div class="chart-box"><canvas id="chFuture"></canvas></div></div>
    </div>
    <div class="card"><h3>客户欠款排行（前 10）</h3>
      <div class="table-wrap"><table><thead><tr><th>客户</th><th class="num">合同额</th><th class="num">已回款</th><th class="num">欠款</th></tr></thead>
      <tbody>${d.top_debtors.map(t => `<tr><td>${esc(t.name)}</td><td class="num">${money(t.contracted)}</td>
        <td class="num">${money(t.received)}</td><td class="num money-red">${money(t.outstanding)}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">暂无欠款</td></tr>'}</tbody></table></div>
    </div>`;
  makeChart('chTrend', {
    type: 'bar',
    data: { labels: d.received_trend.map(x => x.m), datasets: [{ label: '回款额', data: d.received_trend.map(x => x.s), backgroundColor: '#1a56db' }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });
  const fm = Object.keys(d.future_by_month).sort();
  makeChart('chFuture', {
    type: 'bar',
    data: { labels: fm, datasets: [{ label: '预计回款', data: fm.map(m => d.future_by_month[m]), backgroundColor: '#12b76a' }] },
    options: { maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });
}

/* ---------------- 客户 ---------------- */
async function renderCustomers(view) {
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" placeholder="搜索客户名 / 联系人 / 电话" style="flex:1;min-width:200px">
      <button class="btn" id="btnSearch">搜索</button>
      <button class="btn btn-primary" id="btnAdd">+ 新增客户</button>
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const q = view.querySelector('#q').value.trim();
    const list = await get('/api/customers' + (q ? `?q=${encodeURIComponent(q)}` : ''));
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>客户名称</th><th>联系人</th><th>电话</th><th>级别</th><th>负责人</th>
        <th class="num">合同额</th><th class="num">欠款</th></tr></thead>
      <tbody>${list.map(c => `<tr class="clickable" data-id="${c.id}">
        <td>${esc(c.name)}</td><td>${esc(c.contact)}</td><td>${esc(c.phone)}</td>
        <td><span class="tag tag-${c.level === 'A' ? 'red' : c.level === 'B' ? 'blue' : 'gray'}">${c.level} 类</span></td>
        <td>${esc(c.owner_name || '')}</td>
        <td class="num">${money(c.contracted)}</td>
        <td class="num ${c.outstanding > 0 ? 'money-red' : ''}">${money(c.outstanding)}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无客户，点击右上角新增</td></tr>'}</tbody></table>`;
    view.querySelectorAll('tr.clickable').forEach(tr => tr.onclick = () => customerModal(+tr.dataset.id, load));
  };
  view.querySelector('#btnSearch').onclick = load;
  view.querySelector('#q').onkeydown = e => { if (e.key === 'Enter') load(); };
  view.querySelector('#btnAdd').onclick = () => customerForm(null, load);
  await load();
}

async function customerForm(c, reload) {
  const users = ME.role === 'admin' ? await get('/api/users') : [];
  const { el, close } = openModal(c ? '编辑客户' : '新增客户', `
    <form id="f" class="form-grid">
      <label class="full">客户名称 *<input name="name" required value="${esc(c?.name || '')}"></label>
      <label>联系人<input name="contact" value="${esc(c?.contact || '')}"></label>
      <label>电话<input name="phone" value="${esc(c?.phone || '')}"></label>
      <label>行业<input name="industry" value="${esc(c?.industry || '')}"></label>
      <label>客户级别<select name="level">${['A', 'B', 'C'].map(l => `<option ${c?.level === l ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      ${['admin', 'finance'].includes(ME.role) ? `<label>信用额度(元，0为未设置)<input name="credit_limit" type="number" min="0" step="0.01" value="${c?.credit_limit ?? 0}"></label>
      <label>接单控制<select name="credit_hold"><option value="0" ${!c?.credit_hold ? 'selected' : ''}>正常接单</option><option value="1" ${c?.credit_hold ? 'selected' : ''}>停接新单</option></select></label>` : ''}
      ${ME.role === 'admin' ? `<label>负责人<select name="owner_id">${users.filter(u => u.active).map(u =>
        `<option value="${u.id}" ${c?.owner_id === u.id ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}</select></label>` : ''}
      <label class="full">地址<input name="address" value="${esc(c?.address || '')}"></label>
      <label class="full">备注<textarea name="remark" rows="2">${esc(c?.remark || '')}</textarea></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    if (d.owner_id) d.owner_id = +d.owner_id;
    try {
      if (c) await put(`/api/customers/${c.id}`, d); else await post('/api/customers', d);
      toast('已保存'); close(); reload();
    } catch (err) { toast(err.message, false); }
  };
}

async function customerModal(id, reload) {
  const c = await get(`/api/customers/${id}`);
  const { el, close } = openModal(c.name, `
    <div class="form-grid">
      <div><span style="color:var(--text2)">联系人：</span>${esc(c.contact) || '-'}</div>
      <div><span style="color:var(--text2)">电话：</span>${esc(c.phone) || '-'}</div>
      <div><span style="color:var(--text2)">行业：</span>${esc(c.industry) || '-'}</div>
      <div><span style="color:var(--text2)">负责人：</span>${esc(c.owner_name) || '-'}</div>
      <div><span style="color:var(--text2)">信用额度：</span>${c.credit_limit > 0 ? money(c.credit_limit) : '未设置'}</div>
      <div><span style="color:var(--text2)">接单状态：</span>${c.credit_hold ? '停接新单' : '正常接单'}</div>
      <div class="full"><span style="color:var(--text2)">地址：</span>${esc(c.address) || '-'}</div>
      <div class="full"><span style="color:var(--text2)">备注：</span>${esc(c.remark) || '-'}</div>
    </div>
    <div style="margin:12px 0;display:flex;gap:16px;flex-wrap:wrap">
      <span>合同额 <b>${money(c.contracted)}</b></span>
      <span>已回款 <b class="money-green">${money(c.received)}</b></span>
      <span>欠款 <b class="money-red">${money(c.outstanding)}</b></span>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-sm" id="btnEdit">编辑资料</button>
      <button class="btn btn-sm btn-primary" id="btnNewContract">+ 新建合同</button>
      ${ME.role === 'admin' ? '<button class="btn btn-sm btn-danger" id="btnDel">删除客户</button>' : ''}
    </div>
    <div class="section-title">跟进记录
      <span style="display:flex;gap:6px"><input id="fuContent" placeholder="记录一次跟进…" style="padding:6px 10px;border:1px solid var(--border);border-radius:8px;width:220px">
      <input id="fuNext" type="date" style="padding:6px;border:1px solid var(--border);border-radius:8px" title="下次跟进日期">
      <button class="btn btn-sm btn-primary" id="btnFu">添加</button></span>
    </div>
    <div class="table-wrap"><table><tbody>
      ${c.followups.map(f => `<tr><td style="white-space:normal">${esc(f.content)}</td>
        <td>${esc(f.created_by_name || '')}</td><td>${f.next_date ? '下次: ' + f.next_date : ''}</td>
        <td>${(f.created_at || '').slice(0, 16)}</td></tr>`).join('') || '<tr><td class="empty">暂无跟进记录</td></tr>'}
    </tbody></table></div>
    <div class="section-title">名下合同</div>
    <div class="table-wrap"><table><thead><tr><th>编号</th><th>标题</th><th class="num">金额</th><th class="num">已收</th><th class="num">已开票</th><th>状态</th></tr></thead><tbody>
      ${c.contracts.map(ct => `<tr class="clickable" data-cid="${ct.id}"><td>${esc(ct.contract_no)}</td><td>${esc(ct.title)}</td>
        <td class="num">${money(ct.amount)}</td><td class="num">${money(ct.received)}</td><td class="num">${money(ct.invoiced)}</td>
        <td>${statusTag(ct.status)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">暂无合同</td></tr>'}
    </tbody></table></div>`, true);
  el.querySelector('#btnEdit').onclick = async () => { close(); await customerForm(c, reload); };
  el.querySelector('#btnNewContract').onclick = async () => { close(); await contractForm(null, c.id, reload); };
  if (el.querySelector('#btnDel')) el.querySelector('#btnDel').onclick = () =>
    confirmDo('确定删除该客户？（名下有合同时无法删除）', async () => {
      try { await del(`/api/customers/${c.id}`); toast('已删除'); close(); reload(); }
      catch (e) { toast(e.message, false); }
    });
  el.querySelector('#btnFu').onclick = async () => {
    const content = el.querySelector('#fuContent').value.trim();
    if (!content) return;
    await post(`/api/customers/${c.id}/followups`, { content, next_date: el.querySelector('#fuNext').value });
    close(); customerModal(id, reload);
  };
  el.querySelectorAll('tr[data-cid]').forEach(tr => tr.onclick = () => { close(); contractModal(+tr.dataset.cid); });
}

/* ---------------- 合同 ---------------- */
async function renderContracts(view) {
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" placeholder="搜索编号 / 标题 / 客户" style="flex:1;min-width:180px">
      <select id="st"><option value="">全部状态</option>${[...new Set([...dictLabels('contract_status_product'), ...dictLabels('contract_status_service')])].map(s => `<option>${s}</option>`).join('')}</select>
      <button class="btn" id="btnSearch">搜索</button>
      <button class="btn btn-primary" id="btnAdd">+ 新建合同</button>
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const p = new URLSearchParams();
    if (view.querySelector('#q').value.trim()) p.set('q', view.querySelector('#q').value.trim());
    if (view.querySelector('#st').value) p.set('status', view.querySelector('#st').value);
    const list = await get('/api/contracts?' + p);
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>合同编号</th><th>类型</th><th>标题</th><th>客户</th><th class="num">金额</th>
        <th class="num">已回款</th><th class="num">未回款</th><th class="num">已开票</th><th class="num">未开票</th><th>状态</th><th>负责人</th></tr></thead>
      <tbody>${list.map(c => `<tr class="clickable" data-id="${c.id}">
        <td>${esc(c.contract_no)}</td>
        <td><span class="tag tag-${c.type === 'service' ? 'green' : 'blue'}">${c.type === 'service' ? '服务' : '产品'}</span></td>
        <td>${esc(c.title)}</td><td>${esc(c.customer_name)}</td>
        <td class="num">${money(c.amount)}</td>
        <td class="num money-green">${money(c.received)}</td>
        <td class="num ${c.outstanding > 0 ? 'money-red' : ''}">${money(c.outstanding)}</td>
        <td class="num">${money(c.invoiced)}</td>
        <td class="num ${c.uninvoiced > 0 ? 'money-red' : ''}">${money(c.uninvoiced)}</td>
        <td>${statusTag(c.status)}</td><td>${esc(c.owner_name || '')}</td></tr>`).join('')
        || '<tr><td colspan="10" class="empty">暂无合同</td></tr>'}</tbody></table>`;
    view.querySelectorAll('tr.clickable').forEach(tr => tr.onclick = () => contractModal(+tr.dataset.id, load));
  };
  view.querySelector('#btnSearch').onclick = load;
  view.querySelector('#q').onkeydown = e => { if (e.key === 'Enter') load(); };
  view.querySelector('#btnAdd').onclick = () => contractForm(null, null, load);
  await load();
}

async function contractForm(c, presetCustomer, reload) {
  const custs = await get('/api/customers');
  const users = ME.role === 'admin' ? await get('/api/users') : [];
  const { el, close } = openModal(c ? '编辑合同' : '新建合同', `
    <form id="f" class="form-grid">
      <label>合同编号 *<input name="contract_no" required value="${esc(c?.contract_no || '')}" ${c ? 'readonly' : ''}></label>
      <label>客户 *<select name="customer_id" ${c ? 'disabled' : ''}>${custs.map(x =>
        `<option value="${x.id}" ${(c?.customer_id || presetCustomer) === x.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>
      <label class="full">合同标题 *<input name="title" required value="${esc(c?.title || '')}"></label>
      <label>合同类型<select name="type" id="ctType" ${c ? '' : ''}>
        <option value="product" ${c?.type !== 'service' ? 'selected' : ''}>产品合同</option>
        <option value="service" ${c?.type === 'service' ? 'selected' : ''}>服务合同</option></select></label>
      <label>合同金额(元)${c?.items?.length ? '（由明细合计）' : ' *'}<input name="amount" type="number" step="0.01" min="0" required value="${c?.amount ?? ''}" ${c?.items?.length ? 'readonly title="由合同明细合计，请通过明细变更调整"' : ''}></label>
      <label>状态<select name="status" id="ctStatus"></select></label>
      <label>签订日期<input name="sign_date" type="date" value="${c?.sign_date || today()}"></label>
      <label>交付日期<input name="delivery_date" type="date" value="${c?.delivery_date || ''}"></label>
      ${ME.role === 'admin' ? `<label>负责人<select name="owner_id">${users.filter(u => u.active).map(u =>
        `<option value="${u.id}" ${c?.owner_id === u.id ? 'selected' : ''}>${esc(u.name)}</option>`).join('')}</select></label>` : ''}
      ${!c ? `<label>回款计划模板<select name="plan_template">
        <option value="">暂不生成</option><option value="361">3-6-1（订金30%/发货60%/尾款10%）</option>
        <option value="541">5-4-1（订金50%/发货40%/质保10%）</option>
        <option value="100">一次性付款</option><option value="m30">月结 30 天</option></select></label>` : ''}
      <label class="full">备注<textarea name="remark" rows="2">${esc(c?.remark || '')}</textarea></label>
      ${c ? '<label class="full">变更原因（已有收款/开票时改价必填）<input name="change_reason" placeholder="如：补充协议 HT-1-01 调整合同额"></label>' : ''}
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  const typeSel = el.querySelector('#ctType'), stSel = el.querySelector('#ctStatus');
  const refillStatus = () => { stSel.innerHTML = statusOptions(typeSel.value, c?.status || '已签'); };
  typeSel.onchange = refillStatus; refillStatus();
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.amount = +d.amount;
    if (d.customer_id) d.customer_id = +d.customer_id;
    if (d.owner_id) d.owner_id = +d.owner_id;
    if (!d.plan_template) delete d.plan_template;
    try {
      if (c) await put(`/api/contracts/${c.id}`, d);
      else await post('/api/contracts', d);
      toast('已保存'); close(); reload && reload();
    } catch (err) { toast(err.message, false); }
  };
}

async function contractModal(id, reload) {
  const c = await get(`/api/contracts/${id}`);
  const canEdit = ['admin', 'sales'].includes(ME.role);
  const canFinance = ['admin', 'finance'].includes(ME.role);
  const canPay = ['admin', 'finance', 'sales'].includes(ME.role);
  const { el, close } = openModal(`${c.contract_no} ${c.title}`, `
    <div class="form-grid">
      <div><span style="color:var(--text2)">客户：</span>${esc(c.customer_name)}
        <span class="tag tag-${c.type === 'service' ? 'green' : 'blue'}" style="margin-left:6px">${c.type === 'service' ? '服务合同' : '产品合同'}</span></div>
      <div><span style="color:var(--text2)">状态：</span>${statusTag(c.status)}
        <select id="selStatus" style="margin-left:8px;padding:3px 8px;border:1px solid var(--border);border-radius:6px">
        ${statusOptions(c.type || 'product', c.status)}</select></div>
      <div><span style="color:var(--text2)">签订：</span>${c.sign_date || '-'}</div>
      <div><span style="color:var(--text2)">交付：</span>${c.delivery_date || '-'}</div>
      <div><span style="color:var(--text2)">负责人：</span>${esc(c.owner_name) || '-'}</div>
      <div><span style="color:var(--text2)">收货地址：</span>${esc(c.customer_address) || '-'}</div>
      <div class="full"><span style="color:var(--text2)">备注：</span>${esc(c.remark) || '-'}</div>
    </div>
    <div style="margin:12px 0;display:flex;gap:14px;flex-wrap:wrap">
      <span>合同额 <b>${money(c.amount)}</b></span>
      <span>已回款 <b class="money-green">${money(c.received)}</b></span>
      <span>未回款 <b class="money-red">${money(c.outstanding)}</b></span>
      <span>已开票 <b>${money(c.invoiced)}</b></span>
      <span>未开票 <b class="${c.uninvoiced > 0 ? 'money-red' : ''}">${money(c.uninvoiced)}</b></span>
      <span>未排期 <b class="${c.unscheduled_outstanding > 0 ? 'money-red' : ''}">${money(c.unscheduled_outstanding)}</b></span>
      <span>待核销 <b>${money(c.unallocated)}</b></span>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      ${canEdit ? '<button class="btn btn-sm" id="btnEdit">编辑合同</button>' : ''}
      ${canPay ? '<button class="btn btn-sm btn-primary" id="btnPay">登记收款</button>' : ''}
      ${canFinance ? '<button class="btn btn-sm btn-primary" id="btnInv">登记开票</button>' : ''}
      ${ME.role === 'admin' ? '<button class="btn btn-sm btn-danger" id="btnDel">删除合同</button>' : ''}
    </div>
    <div class="section-title">合同文本附件
      ${canEdit ? '<label class="btn btn-sm">上传（可多选）<input type="file" id="fileUp" multiple style="display:none"></label>' : ''}</div>
    <div class="table-wrap"><table><tbody>
      ${(c.files || []).map(f => `<tr><td>📎 ${esc(f.orig_name)}</td>
        <td>${(f.size / 1024).toFixed(0)} KB</td><td>${esc(f.uploaded_by_name || '')}</td><td>${(f.created_at || '').slice(0, 10)}</td>
        <td><a class="btn btn-sm" href="/api/files/${f.id}" target="_blank">预览</a>
            <a class="btn btn-sm" href="/api/files/${f.id}?dl=1">下载</a>
            ${canEdit ? `<button class="btn btn-sm btn-danger" data-delfile="${f.id}">删</button>` : ''}</td></tr>`).join('')
        || '<tr><td class="empty">暂无附件（PDF/图片可在线预览，Word/Excel 请下载查看）</td></tr>'}
    </tbody></table></div>
    <div class="section-title">合同明细（产品/服务） ${canEdit ? '<button class="btn btn-sm" id="btnAddItem">+ 添加明细</button>' : ''}</div>
    <div class="table-wrap"><table><thead><tr><th>类型</th><th>名称</th><th>规格/型号</th><th class="num">数量</th><th class="num">已发货</th><th class="num">单价</th><th class="num">金额</th><th></th></tr></thead><tbody>
      ${(c.items || []).map(i => `<tr>
        <td><span class="tag tag-${i.item_type === 'product' ? 'blue' : i.item_type === 'service' ? 'green' : 'gray'}">${{ product: '产品', service: '服务', other: '其他' }[i.item_type]}</span></td>
        <td>${esc(i.name)}</td><td>${esc(i.spec || '-')}</td>
        <td class="num">${i.quantity}${esc(i.unit || '')}</td>
        <td class="num ${i.shipped >= i.quantity ? 'money-green' : ''}">${i.shipped || 0}${esc(i.unit || '')}</td>
        <td class="num">${money(i.unit_price)}</td><td class="num">${money(i.amount)}</td>
        <td>${canEdit ? `<button class="btn btn-sm btn-danger" data-delitem="${i.id}">删</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="8" class="empty">暂无明细，可点击右上添加（添加后合同金额自动按明细合计）</td></tr>'}
    </tbody></table></div>
    <div class="section-title">回款计划 ${['admin', 'finance'].includes(ME.role) ? '<button class="btn btn-sm" id="btnAddPlan">+ 添加期次</button>' : ''}</div>
    <div class="table-wrap"><table><thead><tr><th>期次</th><th>应收日期</th><th class="num">计划金额</th><th class="num">已收</th><th class="num">未收</th><th>状态</th><th></th></tr></thead><tbody>
      ${c.plans.map(p => `<tr><td>${esc(p.name)}</td><td>${p.due_date}${p.overdue ? ' <span class="tag tag-red">逾期</span>' : ''}</td>
        <td class="num">${money(p.amount)}</td><td class="num">${money(p.received)}</td>
        <td class="num ${p.remain > 0 ? 'money-red' : ''}">${money(p.remain)}</td>
        <td>${planStateTag(p)}</td>
        <td>${p.received === 0 && ['admin', 'finance'].includes(ME.role) ? `<button class="btn btn-sm btn-danger" data-delplan="${p.id}">删</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无回款计划，点击右上添加</td></tr>'}
    </tbody></table></div>
    <div class="section-title">收款记录</div>
    <div class="table-wrap"><table><thead><tr><th>日期</th><th class="num">金额</th><th>对应期次</th><th>方式</th><th>备注</th><th>登记人</th><th></th></tr></thead><tbody>
      ${c.payments.map(p => `<tr><td>${p.pay_date}</td><td class="num money-green">${money(p.amount)}</td>
        <td>${(p.allocations || []).map(a => `<div>${esc(a.plan_name)} ${money(a.amount)} ${canFinance ? `<button class="btn btn-sm" data-cancelalloc="${a.id}">取消</button>` : ''}</div>`).join('') || '-'}</td>
        <td>${esc(p.method)}</td><td>${esc(p.remark)}</td><td>${esc(p.created_by_name || '')}</td>
        <td>${canFinance && p.unallocated > 0 ? `<button class="btn btn-sm btn-primary" data-alloc="${p.id}">核销</button>` : ''}${ME.role === 'admin' ? `<button class="btn btn-sm btn-danger" data-delpay="${p.id}">删</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无收款记录</td></tr>'}
    </tbody></table></div>
    <div class="section-title">开票记录</div>
    <div class="table-wrap"><table><thead><tr><th>开票日期</th><th>发票号码</th><th>类型</th><th class="num">金额</th><th>状态</th><th>备注</th><th></th></tr></thead><tbody>
      ${c.invoices.map(i => `<tr><td>${i.invoice_date}</td><td>${esc(i.invoice_no)}</td><td>${esc(i.type)}</td>
        <td class="num">${money(i.amount)}</td>
        <td><span class="tag tag-${i.status === '已开' ? 'green' : 'gray'}">${i.status}</span></td><td>${esc(i.remark)}</td>
        <td>${i.status === '已开' && canFinance ? `${i.red_remaining > 0 ? `<button class="btn btn-sm btn-danger" data-redinv="${i.id}">红冲</button>` : ''}<button class="btn btn-sm" data-voidinv="${i.id}">作废</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无开票记录</td></tr>'}
    </tbody></table></div>
    <div class="section-title">合同变更记录</div>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>变更前金额</th><th>变更后金额</th><th>原因</th><th>操作人</th></tr></thead><tbody>
      ${(c.changes || []).map(x => `<tr><td>${esc(x.created_at)}</td><td class="num">${money(x.before_amount)}</td><td class="num">${money(x.after_amount)}</td><td>${esc(x.reason)}</td><td>${esc(x.created_by_name || '')}</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">暂无变更记录</td></tr>'}
    </tbody></table></div>
    <div class="section-title">审计日志</div>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>原因</th><th>操作人</th></tr></thead><tbody>
      ${(c.audit_logs || []).map(x => `<tr><td>${esc(x.created_at)}</td><td>${esc(x.action)}</td><td>${esc(x.reason || '-')}</td><td>${esc(x.actor_name || '')}</td></tr>`).join('')
        || '<tr><td colspan="4" class="empty">暂无审计日志</td></tr>'}
    </tbody></table></div>`, true);

  const refresh = () => { close(); contractModal(id, reload); };
  if (canEdit) {
    el.querySelector('#selStatus').onchange = async e => {
      await put(`/api/contracts/${c.id}`, { status: e.target.value }); toast('状态已更新'); refresh();
    };
    if (el.querySelector('#btnEdit')) el.querySelector('#btnEdit').onclick = async () => { close(); await contractForm(c, null, () => { reload && reload(); contractModal(id, reload); }); };
    if (el.querySelector('#btnAddItem')) el.querySelector('#btnAddItem').onclick = () => itemForm(c, refresh);
  } else {
    el.querySelector('#selStatus').disabled = true;
  }
  if (el.querySelector('#btnPay')) el.querySelector('#btnPay').onclick = () => paymentForm(c, null, refresh);
  if (el.querySelector('#btnInv')) el.querySelector('#btnInv').onclick = () => invoiceForm(c, refresh);
  if (el.querySelector('#btnAddPlan')) el.querySelector('#btnAddPlan').onclick = () => planForm(c, refresh);
  el.querySelectorAll('[data-delitem]').forEach(b => b.onclick = () =>
    confirmDo('删除该条明细？合同金额将按剩余明细重新合计。', async () => {
      try { await del(`/api/items/${b.dataset.delitem}`); toast('已删除'); refresh(); } catch (e) { toast(e.message, false); }
    }));
  if (el.querySelector('#fileUp')) el.querySelector('#fileUp').onchange = async e => {
    if (!e.target.files.length) return;
    const fd = new FormData();
    for (const f of e.target.files) fd.append('files', f);
    try { await api(`/api/contracts/${c.id}/files`, { method: 'POST', body: fd }); toast('附件已上传'); refresh(); }
    catch (err) { toast(err.message, false); }
  };
  el.querySelectorAll('[data-delfile]').forEach(b => b.onclick = () =>
    confirmDo('删除该附件？', async () => { try { await del(`/api/files/${b.dataset.delfile}`); toast('已删除'); refresh(); } catch (e) { toast(e.message, false); } }));
  if (el.querySelector('#btnDel')) el.querySelector('#btnDel').onclick = () =>
    confirmDo('确定删除该合同？相关回款计划、收款和开票记录将一并删除！', async () => {
      await del(`/api/contracts/${c.id}`); toast('已删除'); close(); reload && reload();
    });
  el.querySelectorAll('[data-delplan]').forEach(b => b.onclick = () =>
    confirmDo('删除该期回款计划？', async () => { try { await del(`/api/plans/${b.dataset.delplan}`); refresh(); } catch (e) { toast(e.message, false); } }));
  el.querySelectorAll('[data-delpay]').forEach(b => b.onclick = () =>
    confirmDo('删除该笔收款记录？', async () => { try { await del(`/api/payments/${b.dataset.delpay}`); refresh(); } catch (e) { toast(e.message, false); } }));
  el.querySelectorAll('[data-voidinv]').forEach(b => b.onclick = () =>
    confirmDo('作废该发票？', async () => { await put(`/api/invoices/${b.dataset.voidinv}/void`); refresh(); }));
  el.querySelectorAll('[data-alloc]').forEach(b => b.onclick = () =>
    allocationForm(c, c.payments.find(p => p.id === +b.dataset.alloc), refresh));
  el.querySelectorAll('[data-cancelalloc]').forEach(b => b.onclick = () =>
    confirmDo('取消这笔核销？原始收款会保留。', async () => {
      try { await del(`/api/allocations/${b.dataset.cancelalloc}`); toast('已取消核销'); refresh(); }
      catch (e) { toast(e.message, false); }
    }));
  el.querySelectorAll('[data-redinv]').forEach(b => b.onclick = () =>
    redInvoiceForm(c.invoices.find(i => i.id === +b.dataset.redinv), refresh));
}

async function planForm(c, refresh) {
  const { el, close } = openModal('添加回款期次', `
    <form id="f" class="form-grid">
      <label>期次名称 *<input name="name" required placeholder="如：订金 / 发货款 / 尾款"></label>
      <label>应收日期 *<input name="due_date" type="date" required value="${today()}"></label>
      <label>计划金额(元) *<input name="amount" type="number" step="0.01" min="0.01" required></label>
      <label>占合同比例<input name="ratio" type="number" step="0.01" min="0" max="1" placeholder="如 0.3"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.amount = +d.amount; d.ratio = +d.ratio || 0;
    try { await post(`/api/contracts/${c.id}/plans`, d); toast('已添加'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

async function paymentForm(c, planId, refresh) {
  const { el, close } = openModal(`登记收款 - ${c.contract_no}`, `
    <form id="f" class="form-grid">
      <label>对应期次<select name="plan_id"><option value="">不指定</option>
        ${(c.plans || []).filter(p => p.remain > 0).map(p =>
          `<option value="${p.id}" ${planId === p.id ? 'selected' : ''}>${esc(p.name)}（未收 ${money(p.remain)}）</option>`).join('')}</select></label>
      <label>收款金额(元) *<input name="amount" type="number" step="0.01" min="0.01" required></label>
      <label>收款日期<input name="pay_date" type="date" value="${today()}"></label>
      <label>收款方式<select name="method">${(dictLabels('pay_method').length ? dictLabels('pay_method') : ['银行转账', '承兑汇票', '现金', '微信/支付宝', '其他']).map(m => `<option>${m}</option>`).join('')}</select></label>
      <label class="full">备注<input name="remark"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.contract_id = c.id; d.amount = +d.amount; d.plan_id = d.plan_id ? +d.plan_id : null;
    try { await post('/api/payments', d); toast('收款已登记'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

async function invoiceForm(c, refresh) {
  const { el, close } = openModal(`登记开票 - ${c.contract_no}`, `
    <form id="f" class="form-grid">
      <label>发票号码 *<input name="invoice_no" required></label>
      <label>发票类型<select name="type">${['增值税普通发票', '增值税专用发票', '收据', '其他'].map(t => `<option>${t}</option>`).join('')}</select></label>
      <label>开票金额(元) *<input name="amount" type="number" step="0.01" min="0.01" required value="${c.uninvoiced > 0 ? c.uninvoiced : ''}"></label>
      <label>开票日期<input name="invoice_date" type="date" value="${today()}"></label>
      <label class="full">备注<input name="remark"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.contract_id = c.id; d.amount = +d.amount;
    try { await post('/api/invoices', d); toast('开票已登记'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

function allocationForm(c, payment, refresh) {
  const { el, close } = openModal(`收款核销 - ${c.contract_no}`, `
    <form id="f" class="form-grid">
      <p class="full">收款 ${money(payment.amount)}，待核销 ${money(payment.unallocated)}</p>
      <label class="full">回款期次<select name="plan_id" required>${c.plans.filter(p => p.remain > 0).map(p => `<option value="${p.id}">${esc(p.name)}（未收 ${money(p.remain)}）</option>`).join('')}</select></label>
      <label>核销金额(元) *<input name="amount" type="number" step="0.01" min="0.01" max="${payment.unallocated}" required value="${payment.unallocated}"></label>
      <label>核销说明<input name="reason"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button><button class="btn btn-primary">确认核销</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target)); d.plan_id = +d.plan_id; d.amount = +d.amount;
    try { await post(`/api/payments/${payment.id}/allocations`, d); toast('核销完成'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

function redInvoiceForm(invoice, refresh) {
  const remaining = invoice.red_remaining ?? invoice.amount;
  const { el, close } = openModal(`红冲发票 - ${invoice.invoice_no}`, `
    <form id="f" class="form-grid">
      <label>红字发票号码 *<input name="invoice_no" required></label>
      <label>红冲金额(元) *<input name="amount" type="number" step="0.01" min="0.01" max="${remaining}" required value="${remaining}"></label>
      <label>红冲日期<input name="invoice_date" type="date" value="${today()}"></label>
      <label class="full">红冲原因 *<input name="reason" required placeholder="如：折让、退回或开票信息错误"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button><button class="btn btn-danger">确认红冲</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target)); d.amount = +d.amount;
    try { await post(`/api/invoices/${invoice.id}/red`, d); toast('红冲已登记'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

/* ---------------- 合同明细 ---------------- */
async function itemForm(c, refresh) {
  const [products, services] = await Promise.all([get('/api/products'), get('/api/services')]);
  const { el, close } = openModal(`添加合同明细 - ${c.contract_no}`, `
    <form id="f" class="form-grid">
      <label>类型<select name="item_type" id="itType">
        <option value="product" ${!products.length && services.length ? '' : 'selected'}>产品</option>
        <option value="service">服务</option><option value="other">其他（手动填写）</option></select></label>
      <label id="refWrap">选择产品/服务<select name="ref_id" id="itRef"></select></label>
      <label id="nameWrap" style="display:none">名称 *<input name="name" id="itName"></label>
      <label>数量 *<input name="quantity" type="number" step="0.01" min="0.01" value="1" required></label>
      <label>单价(元)<input name="unit_price" type="number" step="0.01" min="0" id="itPrice" placeholder="留空取标准价"></label>
      <label>备注<input name="remark"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">添加</button></div>
    </form>`);
  const typeSel = el.querySelector('#itType'), refSel = el.querySelector('#itRef');
  const refill = () => {
    const t = typeSel.value;
    const manual = t === 'other';
    el.querySelector('#refWrap').style.display = manual ? 'none' : '';
    el.querySelector('#nameWrap').style.display = manual ? '' : 'none';
    el.querySelector('#itName').required = manual;
    const src = t === 'product' ? products : services;
    refSel.innerHTML = src.length
      ? src.map(x => `<option value="${x.id}">${esc(x.name)}${x.model ? ' ' + esc(x.model) : ''}${x.type ? '（' + esc(x.type) + '）' : ''} - ${money(x.price)}</option>`).join('')
      : '<option value="">（暂无，请先到产品/服务管理添加）</option>';
  };
  typeSel.onchange = refill; refill();
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.quantity = +d.quantity;
    d.unit_price = d.unit_price ? +d.unit_price : 0;
    d.ref_id = d.ref_id ? +d.ref_id : null;
    try { await post(`/api/contracts/${c.id}/items`, d); toast('已添加'); close(); refresh(); }
    catch (err) { toast(err.message, false); }
  };
}

/* ---------------- 产品管理 ---------------- */
async function renderProducts(view) {
  const canWrite = ['admin', 'finance'].includes(ME.role);
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" placeholder="搜索名称 / 型号 / 规格 / 分类" style="flex:1;min-width:200px">
      <button class="btn" id="btnSearch">搜索</button>
      ${canWrite ? '<button class="btn btn-primary" id="btnAdd">+ 新增产品</button>' : ''}
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const q = view.querySelector('#q').value.trim();
    const list = await get('/api/products?all=1' + (q ? `&q=${encodeURIComponent(q)}` : ''));
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>产品名称</th><th>型号</th><th>规格</th><th>分类</th><th>单位</th>
        <th class="num">标准价</th><th>状态</th><th>备注</th>${canWrite ? '<th></th>' : ''}</tr></thead>
      <tbody>${list.map(p => `<tr>
        <td>${esc(p.name)}</td><td>${esc(p.model)}</td><td>${esc(p.spec)}</td><td>${esc(p.category)}</td>
        <td>${esc(p.unit)}</td><td class="num">${money(p.price)}</td>
        <td><span class="tag tag-${p.active ? 'green' : 'gray'}">${p.active ? '在售' : '停用'}</span></td>
        <td>${esc(p.remark)}</td>
        ${canWrite ? `<td><button class="btn btn-sm" data-edit="${p.id}">编辑</button>
          <button class="btn btn-sm ${p.active ? 'btn-danger' : ''}" data-tgl="${p.id}" data-act="${p.active ? 0 : 1}">${p.active ? '停用' : '启用'}</button></td>` : ''}</tr>`).join('')
        || '<tr><td colspan="9" class="empty">暂无产品</td></tr>'}</tbody></table>`;
    view.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => productForm(list.find(x => x.id === +b.dataset.edit), load));
    view.querySelectorAll('[data-tgl]').forEach(b => b.onclick = async () => {
      await put(`/api/products/${b.dataset.tgl}`, { active: !!+b.dataset.act }); toast('已更新'); load();
    });
  };
  view.querySelector('#btnSearch').onclick = load;
  view.querySelector('#q').onkeydown = e => { if (e.key === 'Enter') load(); };
  if (view.querySelector('#btnAdd')) view.querySelector('#btnAdd').onclick = () => productForm(null, load);
  await load();
}

function productForm(p, reload) {
  const { el, close } = openModal(p ? '编辑产品' : '新增产品', `
    <form id="f" class="form-grid">
      <label>产品名称 *<input name="name" required value="${esc(p?.name || '')}"></label>
      <label>型号<input name="model" value="${esc(p?.model || '')}"></label>
      <label>规格<input name="spec" value="${esc(p?.spec || '')}"></label>
      <label>分类<input name="category" value="${esc(p?.category || '')}" placeholder="如：设备 / 配件"></label>
      <label>单位<input name="unit" value="${esc(p?.unit || '台')}"></label>
      <label>标准价(元)<input name="price" type="number" step="0.01" min="0" value="${p?.price ?? ''}"></label>
      <label class="full">备注<textarea name="remark" rows="2">${esc(p?.remark || '')}</textarea></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.price = +d.price || 0;
    try {
      if (p) await put(`/api/products/${p.id}`, d); else await post('/api/products', d);
      toast('已保存'); close(); reload();
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------------- 服务管理 ---------------- */
async function renderServices(view) {
  const canWrite = ['admin', 'finance'].includes(ME.role);
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" placeholder="搜索名称 / 类型 / 内容" style="flex:1;min-width:200px">
      <button class="btn" id="btnSearch">搜索</button>
      ${canWrite ? '<button class="btn btn-primary" id="btnAdd">+ 新增服务</button>' : ''}
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const q = view.querySelector('#q').value.trim();
    const list = await get('/api/services?all=1' + (q ? `&q=${encodeURIComponent(q)}` : ''));
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>服务名称</th><th>类型</th><th>服务内容</th><th>单位</th>
        <th class="num">定价</th><th>状态</th><th>备注</th>${canWrite ? '<th></th>' : ''}</tr></thead>
      <tbody>${list.map(s => `<tr>
        <td>${esc(s.name)}</td><td><span class="tag tag-blue">${esc(s.type || '未分类')}</span></td>
        <td style="white-space:normal;max-width:260px">${esc(s.content)}</td>
        <td>${esc(s.unit)}</td><td class="num">${money(s.price)}</td>
        <td><span class="tag tag-${s.active ? 'green' : 'gray'}">${s.active ? '提供中' : '停用'}</span></td>
        <td>${esc(s.remark)}</td>
        ${canWrite ? `<td><button class="btn btn-sm" data-edit="${s.id}">编辑</button>
          <button class="btn btn-sm ${s.active ? 'btn-danger' : ''}" data-tgl="${s.id}" data-act="${s.active ? 0 : 1}">${s.active ? '停用' : '启用'}</button></td>` : ''}</tr>`).join('')
        || '<tr><td colspan="8" class="empty">暂无服务</td></tr>'}</tbody></table>`;
    view.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => serviceForm(list.find(x => x.id === +b.dataset.edit), load));
    view.querySelectorAll('[data-tgl]').forEach(b => b.onclick = async () => {
      await put(`/api/services/${b.dataset.tgl}`, { active: !!+b.dataset.act }); toast('已更新'); load();
    });
  };
  view.querySelector('#btnSearch').onclick = load;
  view.querySelector('#q').onkeydown = e => { if (e.key === 'Enter') load(); };
  if (view.querySelector('#btnAdd')) view.querySelector('#btnAdd').onclick = () => serviceForm(null, load);
  await load();
}

function serviceForm(s, reload) {
  const { el, close } = openModal(s ? '编辑服务' : '新增服务', `
    <form id="f" class="form-grid">
      <label>服务名称 *<input name="name" required value="${esc(s?.name || '')}"></label>
      <label>服务类型<input name="type" list="svcTypes" value="${esc(s?.type || '')}" placeholder="如：刀具涂层 / 装饰镀膜">
        <datalist id="svcTypes">${dictLabels('service_type').map(t => `<option value="${t}">`).join('')}</datalist></label>
      <label class="full">服务内容<textarea name="content" rows="2">${esc(s?.content || '')}</textarea></label>
      <label>单位<input name="unit" value="${esc(s?.unit || '炉')}" placeholder="炉 / 件 / 批"></label>
      <label>定价(元)<input name="price" type="number" step="0.01" min="0" value="${s?.price ?? ''}"></label>
      <label class="full">备注<textarea name="remark" rows="2">${esc(s?.remark || '')}</textarea></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">保存</button></div>
    </form>`);
  el.querySelector('#cancel').onclick = close;
  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.price = +d.price || 0;
    try {
      if (s) await put(`/api/services/${s.id}`, d); else await post('/api/services', d);
      toast('已保存'); close(); reload();
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------------- 系统设置 ---------------- */
async function renderSettings(view) {
  if (ME.role !== 'admin') { view.innerHTML = '<div class="empty">仅管理员可访问</div>'; return; }
  const [s, comp] = await Promise.all([get('/api/settings'), get('/api/settings/company')]);
  const CF = [
    ['company_name', '公司名称'], ['invoice_title', '开票抬头'], ['tax_no', '纳税人识别号'],
    ['bank_name', '开户银行'], ['bank_account', '银行账号'], ['company_phone', '公司电话'],
    ['reg_address', '注册地址'], ['prod_address', '生产地址'], ['ship_address', '默认发货地址'],
  ];
  view.innerHTML = `
    <div class="card" style="max-width:720px">
      <h3>工厂信息（显示在登录页和侧边栏）</h3>
      <form id="f" class="form-grid" style="grid-template-columns:1fr">
        <label>显示名称<input name="factory_name" required maxlength="50" value="${esc(s.factory_name)}"></label>
        <div class="form-actions" style="justify-content:flex-start"><button class="btn btn-primary">保存名称</button></div>
      </form>
    </div>
    <div class="card" style="max-width:720px">
      <h3>系统 LOGO</h3>
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <div id="logoPreview" style="width:120px;height:80px;border:1px dashed var(--border);border-radius:8px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#f8fafc">
          ${s.logo ? `<img src="/api/settings/logo?t=${Date.now()}" style="max-width:100%;max-height:100%">` : '<span style="color:var(--text2)">未设置</span>'}
        </div>
        <label class="btn btn-primary">选择图片并上传<input type="file" id="logoFile" accept="image/*" style="display:none"></label>
      </div>
    </div>
    <div class="card" style="max-width:720px">
      <h3>公司基础信息（用于发货单默认地址、开票信息）</h3>
      <form id="fc" class="form-grid">
        ${CF.map(([k, label]) => `<label class="${k.includes('address') ? 'full' : ''}">${label}<input name="${k}" maxlength="200" value="${esc(comp[k] || '')}"></label>`).join('')}
        <div class="form-actions full"><button class="btn btn-primary">保存公司信息</button></div>
      </form>
    </div>
    <div class="card" style="max-width:720px">
      <h3>数据字典维护</h3>
      <div class="toolbar" style="margin-bottom:10px">
        <select id="dictSel">${Object.entries(DICTS).map(([code, d]) => `<option value="${code}">${esc(d.name)}（${code}）</option>`).join('')}</select>
        <button class="btn btn-sm" id="btnNewType">+ 新建字典类型</button>
      </div>
      <div class="table-wrap" id="dictItems"></div>
    </div>`;
  view.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    try { await put('/api/settings', Object.fromEntries(new FormData(e.target))); toast('已保存'); applySettings(); }
    catch (err) { toast(err.message, false); }
  };
  view.querySelector('#fc').onsubmit = async e => {
    e.preventDefault();
    try { await put('/api/settings/company', Object.fromEntries(new FormData(e.target))); toast('公司信息已保存'); }
    catch (err) { toast(err.message, false); }
  };
  view.querySelector('#logoFile').onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const pv = view.querySelector('#logoPreview');
    pv.innerHTML = `<img src="${URL.createObjectURL(file)}" style="max-width:100%;max-height:100%">`;
    const fd = new FormData(); fd.append('file', file);
    try { await api('/api/settings/logo', { method: 'POST', body: fd }); toast('LOGO 已更新'); applySettings(); }
    catch (err) { toast(err.message, false); pv.innerHTML = '<span style="color:var(--text2)">上传失败</span>'; }
  };
  // ---- 数据字典维护 ----
  const dictSel = view.querySelector('#dictSel');
  const renderDictItems = () => {
    const code = dictSel.value;
    const d = DICTS[code];
    view.querySelector('#dictItems').innerHTML = `
      <table><thead><tr><th>字典项</th><th class="num">排序</th><th>状态</th><th></th></tr></thead>
      <tbody>${d.items.map(i => `<tr>
        <td>${esc(i.label)}</td><td class="num">${i.sort}</td>
        <td><span class="tag tag-${i.active ? 'green' : 'gray'}">${i.active ? '启用' : '停用'}</span></td>
        <td><button class="btn btn-sm ${i.active ? 'btn-danger' : ''}" data-tgl="${i.id}" data-act="${i.active ? 0 : 1}">${i.active ? '停用' : '启用'}</button>
            <button class="btn btn-sm btn-danger" data-rm="${i.id}">删除</button></td></tr>`).join('')}
        <tr><td colspan="4">
          <input id="newLabel" placeholder="新字典项名称" style="padding:6px 10px;border:1px solid var(--border);border-radius:8px;width:200px">
          <input id="newSort" type="number" placeholder="排序" value="99" style="padding:6px;border:1px solid var(--border);border-radius:8px;width:70px;margin-left:6px">
          <button class="btn btn-sm btn-primary" id="btnAddItem" style="margin-left:6px">添加</button>
        </td></tr>
      </tbody></table>`;
    const refresh = async () => { DICTS = await get('/api/dicts'); renderDictItems(); };
    view.querySelectorAll('[data-tgl]').forEach(b => b.onclick = async () => {
      await put(`/api/dict-items/${b.dataset.tgl}`, { active: !!+b.dataset.act }); toast('已更新'); refresh();
    });
    view.querySelectorAll('[data-rm]').forEach(b => b.onclick = () =>
      confirmDo('删除该字典项？（历史数据中的旧值不受影响）', async () => {
        try { await del(`/api/dict-items/${b.dataset.rm}`); toast('已删除'); refresh(); }
        catch (e) { toast(e.message, false); }
      }));
    view.querySelector('#btnAddItem').onclick = async () => {
      const label = view.querySelector('#newLabel').value.trim();
      if (!label) return;
      try {
        await post(`/api/dicts/${code}/items`, { label, sort: +view.querySelector('#newSort').value || 99 });
        toast('已添加'); refresh();
      } catch (e) { toast(e.message, false); }
    };
  };
  dictSel.onchange = renderDictItems;
  view.querySelector('#btnNewType').onclick = () => {
    const { el, close } = openModal('新建字典类型', `
      <form id="f" class="form-grid">
        <label>编码（英文/数字/下划线）*<input name="code" required pattern="[A-Za-z0-9_]+" placeholder="如 order_source"></label>
        <label>名称 *<input name="name" required placeholder="如 订单来源"></label>
        <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
        <button class="btn btn-primary">创建</button></div>
      </form>`);
    el.querySelector('#cancel').onclick = close;
    el.querySelector('#f').onsubmit = async e => {
      e.preventDefault();
      try {
        await post('/api/dicts', Object.fromEntries(new FormData(e.target)));
        toast('已创建'); close(); renderSettings(view);
      } catch (err) { toast(err.message, false); }
    };
  };
  renderDictItems();
}

async function applySettings() {
  try {
    const s = await get('/api/settings');
    document.title = s.factory_name;
    document.getElementById('logoText').textContent = s.factory_name;
    const img = document.getElementById('logoImg');
    if (s.logo) { img.src = '/api/settings/logo?t=' + Date.now(); img.style.display = ''; }
  } catch (e) { /* ignore */ }
}

/* ---------------- 发货管理 ---------------- */
async function renderShipments(view) {
  view.innerHTML = `
    <div class="toolbar">
      <input id="q" placeholder="搜索发货单号 / 客户 / 合同号" style="flex:1;min-width:180px">
      <select id="tp"><option value="">全部类型</option><option value="contract">合同发货</option><option value="temp">临时发货</option></select>
      <button class="btn" id="btnSearch">搜索</button>
      <button class="btn btn-primary" id="btnAdd">+ 新建发货单</button>
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const p = new URLSearchParams();
    if (view.querySelector('#q').value.trim()) p.set('q', view.querySelector('#q').value.trim());
    if (view.querySelector('#tp').value) p.set('type', view.querySelector('#tp').value);
    const list = await get('/api/shipments?' + p);
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>发货单号</th><th>类型</th><th>发货日期</th><th>客户</th><th>关联合同</th>
        <th class="num">数量合计</th><th class="num">金额合计</th><th>运输方式</th><th>收货地址</th><th></th></tr></thead>
      <tbody>${list.map(s => `<tr class="clickable" data-id="${s.id}">
        <td>${esc(s.shipment_no)}</td>
        <td><span class="tag tag-${s.type === 'temp' ? 'orange' : 'blue'}">${s.type === 'temp' ? '临时发货' : '合同发货'}</span></td>
        <td>${s.ship_date}</td><td>${esc(s.customer_name)}</td>
        <td>${esc(s.contract_no || '-')}</td>
        <td class="num">${s.total_qty}</td><td class="num">${money(s.total_amount)}</td>
        <td>${esc(s.transport_method || '-')}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${esc(s.to_address || '-')}</td>
        <td>${ME.role === 'admin' ? `<button class="btn btn-sm btn-danger" data-del="${s.id}">删</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="10" class="empty">暂无发货单</td></tr>'}</tbody></table>`;
    view.querySelectorAll('tr[data-id]').forEach(tr => tr.onclick = e => {
      if (e.target.dataset.del) return;
      shipmentModal(+tr.dataset.id);
    });
    view.querySelectorAll('[data-del]').forEach(b => b.onclick = () =>
      confirmDo('删除该发货单？', async () => { try { await del(`/api/shipments/${b.dataset.del}`); toast('已删除'); load(); } catch (e) { toast(e.message, false); } }));
  };
  view.querySelector('#btnSearch').onclick = load;
  view.querySelector('#tp').onchange = load;
  view.querySelector('#q').onkeydown = e => { if (e.key === 'Enter') load(); };
  view.querySelector('#btnAdd').onclick = () => shipmentForm(load);
  await load();
}

async function shipmentModal(sid) {
  const s = await get(`/api/shipments/${sid}`);
  openModal(`发货单 ${s.shipment_no}`, `
    <div class="form-grid">
      <div><span style="color:var(--text2)">类型：</span>${s.type === 'temp' ? '临时发货' : '合同发货'}</div>
      <div><span style="color:var(--text2)">发货日期：</span>${s.ship_date}</div>
      <div><span style="color:var(--text2)">客户：</span>${esc(s.customer_name)}（${esc(s.contact || '')} ${esc(s.phone || '')}）</div>
      <div><span style="color:var(--text2)">关联合同：</span>${esc(s.contract_no || '-')}</div>
      <div><span style="color:var(--text2)">来料批次：</span>${esc(s.batch_no || '-')}</div>
      <div><span style="color:var(--text2)">发货地址：</span>${esc(s.from_address) || '-'}</div>
      <div><span style="color:var(--text2)">收货地址：</span>${esc(s.to_address) || '-'}</div>
      <div><span style="color:var(--text2)">运输方式：</span>${esc(s.transport_method) || '-'}</div>
      <div><span style="color:var(--text2)">运输金额：</span>${s.transport_fee ? money(s.transport_fee) : '-'}</div>
      <div class="full"><span style="color:var(--text2)">备注：</span>${esc(s.remark) || '-'}</div>
    </div>
    <div class="section-title">发货明细</div>
    <div class="table-wrap"><table><thead><tr><th>名称</th><th>规格</th><th class="num">数量</th><th class="num">单价</th><th class="num">金额</th></tr></thead><tbody>
      ${s.items.map(i => `<tr><td>${esc(i.name)}</td><td>${esc(i.spec || '-')}</td>
        <td class="num">${i.quantity}${esc(i.unit || '')}</td><td class="num">${money(i.unit_price)}</td>
        <td class="num">${money(i.amount)}</td></tr>`).join('')}
      <tr><td colspan="4" class="num"><b>合计</b></td><td class="num"><b>${money(s.total_amount)}</b></td></tr>
    </tbody></table></div>`);
}

async function shipmentForm(reload) {
  const [contracts, customers, company, batches] = await Promise.all([
    get('/api/contracts'), get('/api/customers'), get('/api/settings/company'), get('/api/production/materials')]);
  const transportOpts = dictLabels('transport_method');
  const { el, close } = openModal('新建发货单', `
    <form id="f" class="form-grid">
      <label>发货类型<select name="type" id="shType">
        <option value="contract">合同发货（关联已签合同）</option>
        <option value="temp">临时发货（自动创建临时合同）</option></select></label>
      <label id="ctWrap">选择合同 *<select name="contract_id" id="shContract">
        ${contracts.filter(c => !['已完成', '已归档'].includes(c.status)).map(c =>
          `<option value="${c.id}">${esc(c.contract_no)} ${esc(c.title)}（${esc(c.customer_name)}）</option>`).join('')}
      </select></label>
      <label id="batchWrap" class="full">关联来料批次（可选）<select name="batch_id" id="shBatch"></select></label>
      <label id="custWrap" style="display:none">选择客户 *<select name="customer_id" id="shCustomer">
        ${customers.map(c => `<option value="${c.id}" data-addr="${esc(c.address || '')}">${esc(c.name)}</option>`).join('')}
      </select></label>
      <label>发货日期<input name="ship_date" type="date" value="${today()}"></label>
      <label class="full">发货地址（本厂）<input name="from_address" value="${esc(company.ship_address || company.prod_address || '')}"></label>
      <label class="full">收货地址<input name="to_address" id="shToAddr"></label>
      <label>运输方式<select name="transport_method">${transportOpts.map(t => `<option>${t}</option>`).join('')}</select></label>
      <label>运输金额(元，可选)<input name="transport_fee" type="number" step="0.01" min="0"></label>
      <label class="full">备注<input name="remark"></label>
      <div class="full"><div class="section-title" style="margin-top:4px">发货明细</div>
        <div id="shipItems"></div>
        <div id="tempAddRow" style="display:none;margin-top:8px">
          <button type="button" class="btn btn-sm" id="btnAddRow">+ 添加一行</button></div>
      </div>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">提交发货</button></div>
    </form>`, true);
  el.querySelector('#cancel').onclick = close;
  const typeSel = el.querySelector('#shType');
  const ctSel = el.querySelector('#shContract');
  const custSel = el.querySelector('#shCustomer');
  const itemsBox = el.querySelector('#shipItems');
  let contractItems = [];

  const renderContractItems = async () => {
    const cid = ctSel.value;
    if (!cid) { itemsBox.innerHTML = '<div class="empty">请先创建合同</div>'; return; }
    const c = await get(`/api/contracts/${cid}`);
    el.querySelector('#shToAddr').value = c.customer_address || '';
    el.querySelector('#shBatch').innerHTML = '<option value="">不关联批次</option>' + batches.filter(b => b.contract_id === +cid).map(b => `<option value="${b.id}">${esc(b.batch_no)} ${esc(b.item_name)}</option>`).join('');
    contractItems = (c.items || []).filter(i => i.quantity > 0);
    itemsBox.innerHTML = contractItems.length ? `<table><thead><tr><th>名称</th><th>规格</th><th class="num">合同数量</th><th class="num">已发</th><th class="num">本次发货数量</th></tr></thead><tbody>
      ${contractItems.map(i => `<tr><td>${esc(i.name)}</td><td>${esc(i.spec || '-')}</td>
        <td class="num">${i.quantity}${esc(i.unit || '')}</td>
        <td class="num">${i.shipped || 0}${esc(i.unit || '')}</td>
        <td class="num"><input type="number" min="0" step="0.01" value="${Math.max(i.quantity - (i.shipped || 0), 0)}"
          data-ciid="${i.id}" data-price="${i.unit_price}" style="width:90px;padding:5px;border:1px solid var(--border);border-radius:6px"></td></tr>`).join('')}
      </tbody></table>` : '<div class="empty">该合同暂无明细，请先在合同详情中添加</div>';
  };

  const tempRows = [];
  const renderTempItems = () => {
    itemsBox.innerHTML = `<table><thead><tr><th>名称 *</th><th>规格</th><th class="num">数量</th><th>单位</th><th class="num">单价</th><th></th></tr></thead>
      <tbody>${tempRows.map((r, i) => `<tr>
        <td><input data-k="name" data-i="${i}" value="${esc(r.name)}" style="width:150px;padding:5px;border:1px solid var(--border);border-radius:6px"></td>
        <td><input data-k="spec" data-i="${i}" value="${esc(r.spec)}" style="width:110px;padding:5px;border:1px solid var(--border);border-radius:6px"></td>
        <td><input data-k="quantity" data-i="${i}" type="number" min="0.01" step="0.01" value="${r.quantity}" style="width:80px;padding:5px;border:1px solid var(--border);border-radius:6px"></td>
        <td><input data-k="unit" data-i="${i}" value="${esc(r.unit)}" style="width:60px;padding:5px;border:1px solid var(--border);border-radius:6px"></td>
        <td><input data-k="unit_price" data-i="${i}" type="number" min="0" step="0.01" value="${r.unit_price}" style="width:90px;padding:5px;border:1px solid var(--border);border-radius:6px"></td>
        <td><button type="button" class="btn btn-sm btn-danger" data-rm="${i}">删</button></td></tr>`).join('')}</tbody></table>`;
    itemsBox.querySelectorAll('input[data-k]').forEach(inp => inp.oninput = () => {
      const r = tempRows[+inp.dataset.i];
      r[inp.dataset.k] = inp.dataset.k === 'quantity' || inp.dataset.k === 'unit_price' ? +inp.value : inp.value;
    });
    itemsBox.querySelectorAll('[data-rm]').forEach(b => b.onclick = () => { tempRows.splice(+b.dataset.rm, 1); renderTempItems(); });
  };

  const switchType = () => {
    const t = typeSel.value;
    el.querySelector('#ctWrap').style.display = t === 'contract' ? '' : 'none';
    el.querySelector('#batchWrap').style.display = t === 'contract' ? '' : 'none';
    el.querySelector('#custWrap').style.display = t === 'temp' ? '' : 'none';
    el.querySelector('#tempAddRow').style.display = t === 'temp' ? '' : 'none';
    if (t === 'contract') renderContractItems();
    else {
      el.querySelector('#shBatch').value = '';
      const opt = custSel.selectedOptions[0];
      el.querySelector('#shToAddr').value = opt?.dataset.addr || '';
      if (!tempRows.length) tempRows.push({ name: '', spec: '', quantity: 1, unit: 'kg', unit_price: 0 });
      renderTempItems();
    }
  };
  typeSel.onchange = switchType;
  ctSel.onchange = renderContractItems;
  custSel.onchange = () => { el.querySelector('#shToAddr').value = custSel.selectedOptions[0]?.dataset.addr || ''; };
  el.querySelector('#btnAddRow').onclick = () => { tempRows.push({ name: '', spec: '', quantity: 1, unit: 'kg', unit_price: 0 }); renderTempItems(); };
  switchType();

  el.querySelector('#f').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.transport_fee = d.transport_fee ? +d.transport_fee : 0;
    let items;
    if (d.type === 'contract') {
      d.contract_id = +d.contract_id;
      items = [...itemsBox.querySelectorAll('input[data-ciid]')]
        .map(inp => ({ contract_item_id: +inp.dataset.ciid, quantity: +inp.value, unit_price: +inp.dataset.price }))
        .filter(i => i.quantity > 0);
    } else {
      d.customer_id = +d.customer_id;
      items = tempRows.filter(r => r.name && r.quantity > 0);
    }
    if (!items.length) return toast('请填写发货明细', false);
    d.items = items;
    try {
      const r = await post('/api/shipments', d);
      toast(`发货单 ${r.shipment_no} 已创建`); close(); reload();
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------------- 回款管理 ---------------- */
async function renderPlans(view) {
  view.innerHTML = `
    <div class="toolbar">
      <select id="flt">
        <option value="all">全部期次</option><option value="overdue">已逾期</option>
        <option value="soon">7 天内到期</option><option value="unpaid">未收完</option>
      </select>
      <button class="btn" id="btnPay2">登记收款</button>
      <span class="spacer"></span>
      <span id="summary" style="color:var(--text2)"></span>
    </div>
    <div class="card table-wrap" id="listWrap"></div>`;
  const load = async () => {
    const list = await get('/api/plans?filter=' + view.querySelector('#flt').value);
    const totalRemain = list.reduce((s, p) => s + (p.state === '已收' ? 0 : p.remain), 0);
    view.querySelector('#summary').textContent = `共 ${list.length} 期，未收合计 ${money(totalRemain)}`;
    view.querySelector('#listWrap').innerHTML = `
      <table><thead><tr><th>应收日期</th><th>客户</th><th>合同</th><th>期次</th>
        <th class="num">计划金额</th><th class="num">未收</th><th>状态</th><th>联系人</th><th></th></tr></thead>
      <tbody>${list.map(p => `<tr>
        <td>${p.due_date}${p.overdue_days ? ` <span class="tag tag-red">逾期${p.overdue_days}天</span>` : ''}</td>
        <td>${esc(p.customer_name)}</td>
        <td><a href="javascript:;" data-cid="${p.contract_id}">${esc(p.contract_no)}</a> ${esc(p.contract_title)}</td>
        <td>${esc(p.name)}</td>
        <td class="num">${money(p.amount)}</td>
        <td class="num ${p.remain > 0 ? 'money-red' : ''}">${money(p.remain)}</td>
        <td>${planStateTag(p)}</td>
        <td>${esc(p.contact || '')} ${esc(p.phone || '')}</td>
        <td>${p.remain > 0 ? `<button class="btn btn-sm btn-primary" data-pay="${p.contract_id}" data-plan="${p.id}">收款</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="9" class="empty">暂无数据</td></tr>'}</tbody></table>`;
    view.querySelectorAll('[data-cid]').forEach(a => a.onclick = () => contractModal(+a.dataset.cid));
    view.querySelectorAll('[data-pay]').forEach(b => b.onclick = async () => {
      const c = await get(`/api/contracts/${b.dataset.pay}`);
      paymentForm(c, +b.dataset.plan, load);
    });
  };
  view.querySelector('#flt').onchange = load;
  view.querySelector('#btnPay2').onclick = async () => {
    const cs = await get('/api/contracts');
    if (!cs.length) return toast('请先创建合同', false);
    const { el, close } = openModal('选择合同', `
      <div class="table-wrap"><table><tbody>
      ${cs.filter(c => c.outstanding > 0).map(c => `<tr class="clickable" data-id="${c.id}">
        <td>${esc(c.contract_no)}</td><td>${esc(c.title)}</td><td>${esc(c.customer_name)}</td>
        <td class="num money-red">${money(c.outstanding)}</td></tr>`).join('') || '<tr><td class="empty">没有待收款的合同</td></tr>'}
      </tbody></table></div>`);
    el.querySelectorAll('tr[data-id]').forEach(tr => tr.onclick = async () => {
      const c = await get(`/api/contracts/${tr.dataset.id}`); close(); paymentForm(c, null, load);
    });
  };
  await load();
}

/* ---------------- 开票台账 ---------------- */
async function renderInvoices(view) {
  const list = await get('/api/invoices');
  view.innerHTML = `
    <div class="card table-wrap"><table>
      <thead><tr><th>开票日期</th><th>发票号码</th><th>客户</th><th>合同</th><th>类型</th><th class="num">金额</th><th>状态</th><th>登记人</th><th></th></tr></thead>
      <tbody>${list.map(i => `<tr>
        <td>${i.invoice_date}</td><td>${esc(i.invoice_no)}</td><td>${esc(i.customer_name)}</td>
        <td><a href="javascript:;" data-cid="${i.contract_id}">${esc(i.contract_no)}</a></td>
        <td>${esc(i.type)}</td><td class="num">${money(i.amount)}</td>
        <td><span class="tag tag-${i.status === '已开' ? 'green' : 'gray'}">${i.status}</span></td>
        <td>${esc(i.created_by_name || '')}</td>
        <td>${i.status === '已开' && ['admin', 'finance'].includes(ME.role) ? `${i.red_remaining > 0 ? `<button class="btn btn-sm btn-danger" data-red="${i.id}">红冲</button>` : ''}<button class="btn btn-sm" data-void="${i.id}">作废</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="9" class="empty">暂无开票记录，请在合同详情中登记</td></tr>'}</tbody></table></div>`;
  view.querySelectorAll('[data-cid]').forEach(a => a.onclick = () => contractModal(+a.dataset.cid));
  view.querySelectorAll('[data-red]').forEach(b => b.onclick = () =>
    redInvoiceForm(list.find(i => i.id === +b.dataset.red), () => renderInvoices(view)));
  view.querySelectorAll('[data-void]').forEach(b => b.onclick = () =>
    confirmDo('作废该发票？', async () => { await put(`/api/invoices/${b.dataset.void}/void`); toast('已作废'); renderInvoices(view); }));
}

/* ---------------- 提醒 ---------------- */
async function renderReminders(view) {
  const d = await get('/api/reminders');
  const block = (title, arr, cls) => `
    <div class="card"><h3>${title}（${arr.length}）</h3>
    <div class="table-wrap"><table><thead><tr><th>应收日期</th><th>客户</th><th>合同</th><th>期次</th>
      <th class="num">未收金额</th><th>联系人</th><th></th></tr></thead><tbody>
    ${arr.map(p => `<tr><td>${p.due_date}${p.overdue_days ? ` <span class="tag tag-red">逾期${p.overdue_days}天</span>` : ''}</td>
      <td>${esc(p.customer_name)}</td>
      <td><a href="javascript:;" data-cid="${p.contract_id}">${esc(p.contract_no)}</a></td>
      <td>${esc(p.name)}</td><td class="num money-red">${money(p.remain)}</td>
      <td>${esc(p.contact || '')} <a href="tel:${esc(p.phone)}">${esc(p.phone || '')}</a></td>
      <td><button class="btn btn-sm btn-primary" data-pay="${p.contract_id}" data-plan="${p.id}">收款</button></td></tr>`).join('')
      || '<tr><td colspan="7" class="empty">暂无</td></tr>'}</tbody></table></div></div>`;
  view.innerHTML = block('🔴 已逾期', d.overdue) + block(`🟠 ${d.remind_days} 天内即将到期`, d.soon);
  view.querySelectorAll('[data-cid]').forEach(a => a.onclick = () => contractModal(+a.dataset.cid));
  view.querySelectorAll('[data-pay]').forEach(b => b.onclick = async () => {
    const c = await get(`/api/contracts/${b.dataset.pay}`);
    paymentForm(c, +b.dataset.plan, () => renderReminders(view));
  });
}

/* ---------------- 统计报表 ---------------- */
function statFilterBar(id, users) {
  const stOpts = [...dictLabels('contract_status_product'), ...dictLabels('contract_status_service')]
    .filter((v, i, a) => a.indexOf(v) === i);
  return `<div class="toolbar" id="${id}">
    <label style="color:var(--text2)">签订日期</label>
    <input type="date" name="from"> <span style="color:var(--text2)">至</span> <input type="date" name="to">
    <select name="status"><option value="">全部状态</option>${stOpts.map(s => `<option>${s}</option>`).join('')}</select>
    ${ME.role !== 'sales' ? `<select name="owner_id"><option value="">全部负责人</option>${users.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join('')}</select>` : ''}
    <button class="btn btn-primary btn-sm">查询</button>
  </div>`;
}

function bindItemStat(view, barId, apiUrl, tableId, chartId, label) {
  const bar = view.querySelector('#' + barId);
  const load = async () => {
    const p = new URLSearchParams();
    ['from', 'to', 'status', 'owner_id'].forEach(k => {
      const inp = bar.querySelector(`[name=${k}]`);
      if (inp && inp.value) p.set(k, inp.value);
    });
    const data = await get(apiUrl + (p.toString() ? '?' + p : ''));
    view.querySelector('#' + tableId).innerHTML = `
      <table><thead><tr><th>${label}</th><th class="num">合同数</th><th class="num">客户数</th>
        <th class="num">合同额</th><th class="num">回款(分摊)</th><th class="num">未收</th><th class="num">开票(分摊)</th></tr></thead>
      <tbody>${data.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${r.contracts}</td><td class="num">${r.customers}</td>
        <td class="num">${money(r.amount)}</td><td class="num money-green">${money(r.received)}</td>
        <td class="num ${r.outstanding > 0 ? 'money-red' : ''}">${money(r.outstanding)}</td>
        <td class="num">${money(r.invoiced)}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无数据（合同需先添加明细）</td></tr>'}
      </tbody></table>`;
    const top = data.slice(0, 10);
    makeChart(chartId, {
      type: 'bar',
      data: {
        labels: top.map(r => r.name.length > 8 ? r.name.slice(0, 8) + '…' : r.name),
        datasets: [
          { label: '合同额', data: top.map(r => r.amount), backgroundColor: '#1a56db' },
          { label: '回款', data: top.map(r => r.received), backgroundColor: '#12b76a' },
          { label: '未收', data: top.map(r => r.outstanding), backgroundColor: '#d92d20' },
        ]
      },
      options: { maintainAspectRatio: false }
    });
  };
  bar.querySelector('button').onclick = load;
  return load();
}

/* ---------------- 数据分析 & 统计报表（标签页） ---------------- */
// 数据分析：老板、工厂、财务、毛利、产能与客户风险看板
function buildAnalyticsTabs() {
  const tabs = [];
  if (ME.role === 'admin') tabs.push(['boss', '👔 老板视角', renderTabBoss]);
  if (['admin', 'manager'].includes(ME.role)) tabs.push(['plant', '🏭 工厂视角', renderTabPlant]);
  if (['admin', 'finance'].includes(ME.role)) {
    tabs.push(['finance', '💼 财务视角', renderTabFinance]);
    tabs.push(['profit', '经营毛利', renderTabProfit]);
  }
  if (['admin', 'finance', 'manager'].includes(ME.role)) tabs.push(['operations', '产能与客户风险', renderTabOperations]);
  return tabs;
}
// 统计报表：台账式报表（筛选 + 明细表 + 导出 Excel，对账出表用）
function buildReportTabs() {
  const tabs = [];
  tabs.push(['contracts', '📄 合同统计', renderTabContracts]);
  tabs.push(['receipts', '💰 回款统计', renderTabReceipts]);
  if (ME.role !== 'sales') {
    if (['admin', 'finance'].includes(ME.role)) tabs.push(['invoicing', '🧾 开票统计', renderTabInvoicing]);
    tabs.push(['aging', '⏳ 账龄分析', renderTabAging]);
    tabs.push(['product', '📦 产品维度', renderTabProduct]);
    tabs.push(['service', '🛠 服务维度', renderTabService]);
    if (['admin', 'finance'].includes(ME.role)) tabs.push(['perf', '🏆 业绩统计', renderTabPerf]);
  }
  return tabs;
}

// 通用标签页渲染器；支持 #/analytics?tab=plant 直达指定标签
async function renderTabbedPage(view, tabs) {
  if (!tabs.length) {
    view.innerHTML = '<div class="empty">当前角色没有可用的分析视图</div>';
    return;
  }
  const wantTab = new URLSearchParams((location.hash.split('?')[1] || '')).get('tab');
  const first = tabs.some(t => t[0] === wantTab) ? wantTab : tabs[0][0];
  view.innerHTML = `
    <div class="tabs">${tabs.map(([k, label]) =>
      `<button class="tab ${k === first ? 'active' : ''}" data-tab="${k}">${label}</button>`).join('')}</div>
    <div id="tabPane"><div class="loading">加载中…</div></div>`;
  const pane = view.querySelector('#tabPane');
  const show = async key => {
    view.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === key));
    pane.innerHTML = '<div class="loading">加载中…</div>';
    const fn = tabs.find(t => t[0] === key)[2];
    try { await fn(pane); } catch (e) { pane.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  view.querySelectorAll('.tab').forEach(t => t.onclick = () => show(t.dataset.tab));
  await show(first);
}

async function renderAnalytics(view) { await renderTabbedPage(view, buildAnalyticsTabs()); }
async function renderReports(view) { await renderTabbedPage(view, buildReportTabs()); }

// 导出 Excel（document 级委托，只绑一次；自动带上按钮所在筛选栏的当前条件）
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-export]');
  if (!btn) return;
  const p = new URLSearchParams();
  const bar = btn.dataset.bar && document.getElementById(btn.dataset.bar);
  if (bar) bar.querySelectorAll('[name]').forEach(inp => { if (inp.value) p.set(inp.name, inp.value); });
  window.open('/api/stats/export/' + btn.dataset.export + (p.toString() ? '?' + p : ''), '_blank');
});

function kpiCards(items) {
  return `<div class="stat-grid">${items.map(([label, val, note, cls]) =>
    `<div class="stat-card"><div class="label">${label}</div>
     <div class="value ${cls || ''}">${val}</div>
     ${note ? `<div class="kpi-note">${note}</div>` : ''}</div>`).join('')}</div>`;
}

function barChartCfg(labels, datasets) {
  return { type: 'bar', data: { labels, datasets }, options: { maintainAspectRatio: false } };
}

/* ---- 老板视角 ---- */
async function renderTabBoss(pane) {
  const d = await get('/api/stats/view/boss');
  const futureMonths = Object.keys(d.future_by_month).sort();
  pane.innerHTML = `
    <div class="toolbar" style="justify-content:flex-end"><button class="btn btn-sm" data-export="boss">📥 导出 Excel</button></div>
    ${kpiCards([
      ['本月签约', money(d.signed_month), `${d.signed_month_count} 份合同`],
      ['本月回款', money(d.received_month), `本年累计 ${money(d.received_year)}`, 'money-green'],
      ['应收未收', money(d.outstanding), `在手合同 ${d.contracts_active} 份`, 'money-red'],
      ['逾期金额', money(d.overdue_amount), `${d.overdue_count} 笔已逾期`, 'money-red'],
    ])}
    <div class="card"><h3>近 12 个月 签约 vs 回款</h3>
      <div class="chart-box"><canvas id="chBossTrend"></canvas></div></div>
    <div class="card"><h3>未来回款预测（按回款计划）</h3>
      ${futureMonths.length ? `<div class="table-wrap"><table><thead><tr>${futureMonths.map(m => `<th class="num">${m}</th>`).join('')}</tr></thead>
        <tbody><tr>${futureMonths.map(m => `<td class="num money-green">${money(d.future_by_month[m])}</td>`).join('')}</tr></tbody></table></div>`
      : '<div class="empty">暂无待回款计划</div>'}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px" class="two-col">
      <div class="card"><h3>欠款客户 TOP5</h3>
        <div class="table-wrap"><table><thead><tr><th>客户</th><th class="num">合同额</th><th class="num">已回款</th><th class="num">欠款</th></tr></thead>
        <tbody>${d.top_debtors.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${money(r.contracted)}</td>
          <td class="num money-green">${money(r.received)}</td><td class="num money-red">${money(r.outstanding)}</td></tr>`).join('')
          || '<tr><td colspan="4" class="empty">暂无欠款</td></tr>'}</tbody></table></div></div>
      <div class="card"><h3>业务员签约 TOP5（本年）</h3>
        ${d.top_sales.length ? '<div class="chart-box"><canvas id="chBossSales"></canvas></div>' : '<div class="empty">暂无数据</div>'}</div>
    </div>`;
  makeChart('chBossTrend', {
    type: 'line',
    data: {
      labels: d.signed_series.map(x => x.m),
      datasets: [
        { label: '签约额', data: d.signed_series.map(x => x.amount), borderColor: '#1a56db', backgroundColor: 'rgba(26,86,219,.12)', fill: true, tension: .3 },
        { label: '回款额', data: d.received_series.map(x => x.amount), borderColor: '#12b76a', backgroundColor: 'rgba(18,183,106,.12)', fill: true, tension: .3 },
      ]
    },
    options: { maintainAspectRatio: false }
  });
  if (d.top_sales.length) {
    makeChart('chBossSales', barChartCfg(d.top_sales.map(r => r.name),
      [{ label: '签约额', data: d.top_sales.map(r => r.signed), backgroundColor: '#7a5af8' }]));
  }
}

/* ---- 工厂经理视角 ---- */
async function renderTabPlant(pane) {
  const d = await get('/api/stats/view/plant');
  pane.innerHTML = `
    <div class="toolbar" style="justify-content:flex-end"><button class="btn btn-sm" data-export="plant">📥 导出 Excel</button></div>
    ${kpiCards([
      ['在手合同', d.active_count + ' 份', `金额 ${money(d.active_amount)}`],
      ['待发货明细', d.pending_item_count + ' 项', `涉及 ${d.pending_contract_count} 份合同`, d.pending_item_count ? 'money-red' : ''],
      ['本月发货', d.ship_month_count + ' 单', `金额 ${money(d.ship_month_amount)}`],
      ['交付逾期', d.overdue_delivery_count + ' 份', d.overdue_delivery_count ? '需立即处理' : '无逾期', d.overdue_delivery_count ? 'money-red' : 'money-green'],
      ['加工中炉次', d.furnaces_active + ' 炉', `待排产来料 ${d.materials_pending} 批`],
      ['质量异常', d.quality_exceptions + ' 次', d.quality_exceptions ? '需复核处理' : '无异常', d.quality_exceptions ? 'money-red' : 'money-green'],
    ])}
    <div class="card"><h3>待发货明细（按交付日期优先，最多15条）</h3>
      <div class="table-wrap"><table><thead><tr><th>合同编号</th><th>客户</th><th>产品/服务</th><th>规格</th>
        <th class="num">合同量</th><th class="num">已发</th><th class="num">待发</th><th>交付日期</th></tr></thead>
      <tbody>${d.pending_items.map(r => `<tr><td>${esc(r.contract_no)}</td><td>${esc(r.customer)}</td>
        <td>${esc(r.name)}</td><td>${esc(r.spec || '-')}</td>
        <td class="num">${r.quantity}${esc(r.unit || '')}</td><td class="num">${r.shipped}</td>
        <td class="num money-red">${r.remain}</td><td>${esc(r.delivery_date || '-')}</td></tr>`).join('')
        || '<tr><td colspan="8" class="empty">全部发完，无待发货明细</td></tr>'}</tbody></table></div></div>
    ${d.overdue_delivery.length ? `
    <div class="card"><h3>⚠️ 交付逾期合同</h3>
      <div class="table-wrap"><table><thead><tr><th>合同编号</th><th>标题</th><th>客户</th><th>交付日期</th><th>状态</th></tr></thead>
      <tbody>${d.overdue_delivery.map(r => `<tr><td>${esc(r.contract_no)}</td><td>${esc(r.title)}</td>
        <td>${esc(r.customer)}</td><td class="money-red">${esc(r.delivery_date)}</td><td>${statusTag(r.status)}</td></tr>`).join('')}
      </tbody></table></div></div>` : ''}
    <div class="card"><h3>近 12 个月发货金额</h3>
      ${d.ship_by_month.length ? '<div class="chart-box"><canvas id="chPlantShip"></canvas></div>' : '<div class="empty">暂无发货记录</div>'}
      <div class="kpi-note">本月临时发货 ${d.temp_month_count} 单</div></div>`;
  if (d.ship_by_month.length) {
    makeChart('chPlantShip', barChartCfg(d.ship_by_month.map(r => r.label),
      [{ label: '发货金额', data: d.ship_by_month.map(r => r.amount), backgroundColor: '#f79009' }]));
  }
}

/* ---- 财务经理视角 ---- */
async function renderTabFinance(pane) {
  const d = await get('/api/stats/view/finance');
  pane.innerHTML = `
    <div class="toolbar" style="justify-content:flex-end"><button class="btn btn-sm" data-export="finance">📥 导出 Excel</button></div>
    ${kpiCards([
      ['本月回款', money(d.received_month), `${d.received_month_count} 笔`, 'money-green'],
      ['本月回款计划达成', d.due_month_rate === null ? '无到期计划' : d.due_month_rate + '%', `本月到期 ${money(d.due_month_amount)}`],
      ['逾期应收', money(d.overdue_amount), `${d.overdue_count} 笔`, 'money-red'],
      ['未开票金额', money(d.uninvoiced), `本月已开 ${money(d.invoiced_month)}（${d.invoiced_month_count} 张）`],
      ['未排期应收', money(d.unscheduled), '需补回款计划', d.unscheduled > 0 ? 'money-red' : ''],
      ['待核销收款', money(d.unallocated), '未分配回款期次'],
    ])}
    <div class="card"><h3>逾期应收明细（TOP10）</h3>
      <div class="table-wrap"><table><thead><tr><th>客户</th><th>合同编号</th><th>期次</th><th class="num">未收金额</th><th class="num">逾期天数</th></tr></thead>
      <tbody>${d.overdue.map(o => `<tr><td>${esc(o.customer)}</td><td>${esc(o.contract_no)}</td><td>${esc(o.plan)}</td>
        <td class="num money-red">${money(o.remain)}</td><td class="num money-red">${o.days} 天</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">无逾期，继续保持</td></tr>'}</tbody></table></div></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px" class="two-col">
      <div class="card"><h3>本年收款方式分布</h3>
        ${d.by_method.length ? '<div class="chart-box"><canvas id="chFinMethod"></canvas></div>' : '<div class="empty">暂无收款</div>'}</div>
      <div class="card"><h3>未来 90 天预计回款</h3>
        <div class="stat-card" style="border:none;box-shadow:none"><div class="value money-green">${money(d.future90)}</div>
        <div class="kpi-note">按回款计划中未收部分汇总</div></div></div>
    </div>`;
  if (d.by_method.length) {
    makeChart('chFinMethod', {
      type: 'doughnut',
      data: {
        labels: d.by_method.map(r => r.label || '未填'),
        datasets: [{ data: d.by_method.map(r => r.amount),
          backgroundColor: ['#1a56db', '#12b76a', '#f79009', '#7a5af8', '#98a2b3'] }]
      },
      options: { maintainAspectRatio: false }
    });
  }
}

/* ---- 成本与预估毛利 ---- */
async function renderTabProfit(pane) {
  pane.innerHTML = `<div class="card">
    <div class="toolbar" id="fltProfit"><label>签订日期</label><input type="date" name="from"><span>至</span><input type="date" name="to"><button class="btn btn-primary btn-sm">查询</button><button type="button" class="btn btn-sm" data-export="profit" data-bar="fltProfit">导出 Excel</button></div>
    <div id="profitKpis"></div>
    <div class="grid-2"><div><h3>成本类别</h3><div class="chart-box"><canvas id="chCostCategory"></canvas></div></div><div><h3>亏损合同</h3><div class="table-wrap" id="lossContracts"></div></div></div>
    <h3>合同预估毛利</h3><div class="table-wrap" id="profitContracts"></div></div>`;
  const load = async () => {
    const p = new URLSearchParams();
    pane.querySelectorAll('#fltProfit [name]').forEach(x => { if (x.value) p.set(x.name, x.value); });
    const d = await get('/api/stats/profitability?' + p);
    pane.querySelector('#profitKpis').innerHTML = kpiCards([
      ['合同额', money(d.amount)], ['已归集成本', money(d.cost), `当月成本 ${money(d.cost_month)}`],
      ['预估毛利', money(d.gross_profit), '', d.gross_profit < 0 ? 'money-red' : 'money-green'],
      ['预估毛利率', d.margin_rate === null ? '-' : d.margin_rate + '%', '合同额减已归集成本'],
    ]);
    pane.querySelector('#lossContracts').innerHTML = `<table><thead><tr><th>合同</th><th class="num">成本</th><th class="num">亏损</th></tr></thead><tbody>${d.loss_contracts.map(x => `<tr><td>${esc(x.contract_no)}</td><td class="num">${money(x.cost)}</td><td class="num money-red">${money(x.gross_profit)}</td></tr>`).join('') || '<tr><td colspan="3" class="empty">暂无亏损合同</td></tr>'}</tbody></table>`;
    pane.querySelector('#profitContracts').innerHTML = `<table><thead><tr><th>合同</th><th class="num">合同额</th><th class="num">成本</th><th class="num">预估毛利</th><th class="num">毛利率</th></tr></thead><tbody>${d.contracts.map(x => `<tr><td>${esc(x.contract_no)}</td><td class="num">${money(x.amount)}</td><td class="num">${money(x.cost)}</td><td class="num ${x.gross_profit < 0 ? 'money-red' : 'money-green'}">${money(x.gross_profit)}</td><td class="num">${x.margin_rate === null ? '-' : x.margin_rate + '%'}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">暂无合同</td></tr>'}</tbody></table>`;
    makeChart('chCostCategory', { type: 'doughnut', data: { labels: d.by_category.map(x => x.label), datasets: [{ data: d.by_category.map(x => x.amount), backgroundColor: ['#1a56db', '#12b76a', '#f79009', '#7a5af8', '#98a2b3', '#d92d20'] }] }, options: { maintainAspectRatio: false } });
  };
  pane.querySelector('#fltProfit button').onclick = load;
  await load();
}

/* ---- 产能、质量与客户风险 ---- */
async function renderTabOperations(pane) {
  pane.innerHTML = `<div class="card"><div class="toolbar" id="fltOps"><label>生产日期</label><input type="date" name="from"><span>至</span><input type="date" name="to"><button class="btn btn-primary btn-sm">查询</button><button type="button" class="btn btn-sm" data-export="operations" data-bar="fltOps">导出 Excel</button></div>
    <div id="opsKpis"></div><h3>设备产能</h3><div class="table-wrap" id="equipmentStats"></div>
    <h3>客户风险</h3><div class="table-wrap" id="customerRisks"></div></div>`;
  const load = async () => {
    const p = new URLSearchParams(); pane.querySelectorAll('#fltOps [name]').forEach(x => { if (x.value) p.set(x.name, x.value); });
    const d = await get('/api/stats/operations?' + p);
    pane.querySelector('#opsKpis').innerHTML = kpiCards([
      ['炉次 / 装炉量', `${d.furnace_count} 炉`, `数量 ${d.quantity}`],
      ['产能利用率', d.capacity_utilization === null ? '未配置工时' : d.capacity_utilization + '%', `实际 ${d.actual_hours}h / 可用 ${d.available_hours}h`],
      ['一次合格率', d.first_pass_rate === null ? '暂无质检' : d.first_pass_rate + '%', `首次检验 ${d.first_inspected}`],
      ['停接 / 关注', `${d.risk_counts['停接']} / ${d.risk_counts['关注']} 家`, `TOP5 集中度 ${d.top5_concentration}%`, d.risk_counts['停接'] ? 'money-red' : ''],
    ]);
    pane.querySelector('#equipmentStats').innerHTML = `<table><thead><tr><th>设备</th><th class="num">炉次</th><th class="num">数量</th><th class="num">实际工时</th><th class="num">平均工时</th><th class="num">可用工时</th><th class="num">利用率</th></tr></thead><tbody>${d.equipment.map(x => `<tr><td>${esc(x.equipment)}</td><td class="num">${x.furnaces}</td><td class="num">${x.quantity}</td><td class="num">${x.actual_hours}</td><td class="num">${x.average_hours ?? '-'}</td><td class="num">${x.available_hours ?? '未配置'}</td><td class="num">${x.utilization === null ? '-' : x.utilization + '%'}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">当前期间没有炉次</td></tr>'}</tbody></table>`;
    pane.querySelector('#customerRisks').innerHTML = `<table><thead><tr><th>客户</th><th>风险</th><th class="num">合同额</th><th class="num">未收</th><th class="num">逾期</th><th class="num">信用使用</th><th>触发原因</th></tr></thead><tbody>${d.customers.map(x => `<tr><td>${esc(x.customer)}</td><td>${statusTag(x.risk)}</td><td class="num">${money(x.contracted)}</td><td class="num">${money(x.outstanding)}</td><td class="num ${x.overdue > 0 ? 'money-red' : ''}">${money(x.overdue)}</td><td class="num">${x.credit_usage === null ? '未设置' : x.credit_usage + '%'}</td><td>${esc(x.reasons.join('；') || '无')}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">暂无客户合同</td></tr>'}</tbody></table>`;
  };
  pane.querySelector('#fltOps button').onclick = load;
  await load();
}

/* ---- 合同统计 ---- */
async function renderTabContracts(pane) {
  let users = [];
  if (ME.role !== 'sales') { try { users = (await get('/api/users')).filter(u => u.active); } catch (e) {} }
  const typeOpts = [['product', '产品合同'], ['service', '服务合同']];
  const stOpts = [...dictLabels('contract_status_product'), ...dictLabels('contract_status_service')]
    .filter((v, i, a) => a.indexOf(v) === i);
  pane.innerHTML = `
    <div class="card">
      <div class="toolbar" id="fltC">
        <label style="color:var(--text2)">签订日期</label>
        <input type="date" name="from"> <span style="color:var(--text2)">至</span> <input type="date" name="to">
        <select name="type"><option value="">全部类型</option>${typeOpts.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select>
        <select name="status"><option value="">全部状态</option>${stOpts.map(s => `<option>${s}</option>`).join('')}</select>
        ${ME.role !== 'sales' ? `<select name="owner_id"><option value="">全部负责人</option>${users.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join('')}</select>` : ''}
        <button class="btn btn-primary btn-sm">查询</button>
        <button type="button" class="btn btn-sm" data-export="contracts" data-bar="fltC">📥 导出 Excel</button>
      </div>
      <div id="kpiC"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px" class="two-col">
        <div><h3>按状态分布</h3><div class="table-wrap" id="tblCStatus"></div></div>
        <div><h3>按类型分布</h3><div class="chart-box" style="height:260px"><canvas id="chCType"></canvas></div></div>
      </div>
      <h3 style="margin-top:16px">月度签约趋势</h3>
      <div class="chart-box"><canvas id="chCMonth"></canvas></div>
      <h3 style="margin-top:16px">签约客户 TOP10</h3>
      <div class="table-wrap" id="tblCTop"></div>
    </div>`;
  const load = async () => {
    const p = new URLSearchParams();
    ['from', 'to', 'type', 'status', 'owner_id'].forEach(k => {
      const inp = pane.querySelector(`#fltC [name=${k}]`);
      if (inp && inp.value) p.set(k, inp.value);
    });
    const d = await get('/api/stats/contracts?' + p);
    pane.querySelector('#kpiC').innerHTML = kpiCards([
      ['合同数', d.count + ' 份'], ['合同总额', money(d.amount)], ['平均单额', money(d.avg)],
    ]);
    pane.querySelector('#tblCStatus').innerHTML = `
      <table><thead><tr><th>状态</th><th class="num">份数</th><th class="num">金额</th></tr></thead>
      <tbody>${d.by_status.map(r => `<tr><td>${statusTag(r.label)}</td><td class="num">${r.n}</td><td class="num">${money(r.amount)}</td></tr>`).join('')
        || '<tr><td colspan="3" class="empty">暂无数据</td></tr>'}</tbody></table>`;
    makeChart('chCType', {
      type: 'doughnut',
      data: {
        labels: d.by_type.map(r => ({ product: '产品合同', service: '服务合同' }[r.label] || r.label)),
        datasets: [{ data: d.by_type.map(r => r.amount), backgroundColor: ['#1a56db', '#12b76a', '#f79009'] }]
      },
      options: { maintainAspectRatio: false }
    });
    makeChart('chCMonth', barChartCfg(d.by_month.map(r => r.label),
      [{ label: '签约额', data: d.by_month.map(r => r.amount), backgroundColor: '#1a56db' }]));
    pane.querySelector('#tblCTop').innerHTML = `
      <table><thead><tr><th>客户</th><th class="num">合同数</th><th class="num">签约额</th></tr></thead>
      <tbody>${d.top_customers.map(r => `<tr><td>${esc(r.label)}</td><td class="num">${r.n}</td><td class="num">${money(r.amount)}</td></tr>`).join('')
        || '<tr><td colspan="3" class="empty">暂无数据</td></tr>'}</tbody></table>`;
  };
  pane.querySelector('#fltC button').onclick = load;
  await load();
}

/* ---- 回款统计 ---- */
async function renderTabReceipts(pane) {
  let users = [];
  if (ME.role !== 'sales') { try { users = (await get('/api/users')).filter(u => u.active); } catch (e) {} }
  pane.innerHTML = `
    <div class="card">
      <div class="toolbar" id="fltR">
        <label style="color:var(--text2)">收款日期</label>
        <input type="date" name="from"> <span style="color:var(--text2)">至</span> <input type="date" name="to">
        <select name="method"><option value="">全部方式</option>${dictLabels('pay_method').map(s => `<option>${s}</option>`).join('')}</select>
        ${ME.role !== 'sales' ? `<select name="owner_id"><option value="">全部负责人</option>${users.map(u => `<option value="${u.id}">${esc(u.name)}</option>`).join('')}</select>` : ''}
        <button class="btn btn-primary btn-sm">查询</button>
        <button type="button" class="btn btn-sm" data-export="receipts" data-bar="fltR">📥 导出 Excel</button>
      </div>
      <div id="kpiR"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px" class="two-col">
        <div><h3>收款方式分布</h3><div class="chart-box" style="height:260px"><canvas id="chRMethod"></canvas></div></div>
        <div><h3>月度回款趋势</h3><div class="chart-box" style="height:260px"><canvas id="chRMonth"></canvas></div></div>
      </div>
      <h3 style="margin-top:16px">回款客户 TOP10</h3>
      <div class="table-wrap" id="tblRTop"></div>
    </div>`;
  const load = async () => {
    const p = new URLSearchParams();
    ['from', 'to', 'method', 'owner_id'].forEach(k => {
      const inp = pane.querySelector(`#fltR [name=${k}]`);
      if (inp && inp.value) p.set(k, inp.value);
    });
    const d = await get('/api/stats/receipts?' + p);
    pane.querySelector('#kpiR').innerHTML = kpiCards([
      ['回款总额', money(d.amount), `${d.count} 笔`, 'money-green'],
      ['计划到期', money(d.plan_due), `${d.plan_count} 期`],
      ['计划达成率', d.plan_rate === null ? '-' : d.plan_rate + '%', `实际核销 ${money(d.plan_received)}`,
        d.plan_rate !== null && d.plan_rate < 80 ? 'money-red' : 'money-green'],
    ]);
    makeChart('chRMethod', {
      type: 'doughnut',
      data: {
        labels: d.by_method.map(r => r.label || '未填'),
        datasets: [{ data: d.by_method.map(r => r.amount),
          backgroundColor: ['#1a56db', '#12b76a', '#f79009', '#7a5af8', '#98a2b3'] }]
      },
      options: { maintainAspectRatio: false }
    });
    makeChart('chRMonth', {
      type: 'line',
      data: {
        labels: d.by_month.map(r => r.label),
        datasets: [{ label: '回款额', data: d.by_month.map(r => r.amount), borderColor: '#12b76a',
          backgroundColor: 'rgba(18,183,106,.12)', fill: true, tension: .3 }]
      },
      options: { maintainAspectRatio: false }
    });
    pane.querySelector('#tblRTop').innerHTML = `
      <table><thead><tr><th>客户</th><th class="num">笔数</th><th class="num">回款额</th></tr></thead>
      <tbody>${d.top_customers.map(r => `<tr><td>${esc(r.label)}</td><td class="num">${r.n}</td><td class="num money-green">${money(r.amount)}</td></tr>`).join('')
        || '<tr><td colspan="3" class="empty">暂无数据</td></tr>'}</tbody></table>`;
  };
  pane.querySelector('#fltR button').onclick = load;
  await load();
}

/* ---- 开票统计 ---- */
async function renderTabInvoicing(pane) {
  pane.innerHTML = `
    <div class="card">
      <div class="toolbar" id="fltI">
        <label style="color:var(--text2)">开票日期</label>
        <input type="date" name="from"> <span style="color:var(--text2)">至</span> <input type="date" name="to">
        <select name="inv_type"><option value="">全部票种</option>${['增值税专用发票', '增值税普通发票', '收据', '其他'].map(s => `<option>${s}</option>`).join('')}</select>
        <button class="btn btn-primary btn-sm">查询</button>
        <button type="button" class="btn btn-sm" data-export="invoicing" data-bar="fltI">📥 导出 Excel</button>
      </div>
      <div id="kpiI"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px" class="two-col">
        <div><h3>票种分布</h3><div class="chart-box" style="height:260px"><canvas id="chIType"></canvas></div></div>
        <div><h3>月度开票趋势</h3><div class="chart-box" style="height:260px"><canvas id="chIMonth"></canvas></div></div>
      </div>
      <h3 style="margin-top:16px">未开票合同排行（全部在手合同）</h3>
      <div class="table-wrap" id="tblITop"></div>
    </div>`;
  const load = async () => {
    const p = new URLSearchParams();
    ['from', 'to', 'inv_type'].forEach(k => {
      const inp = pane.querySelector(`#fltI [name=${k}]`);
      if (inp && inp.value) p.set(k, inp.value);
    });
    const d = await get('/api/stats/invoicing?' + p);
    pane.querySelector('#kpiI').innerHTML = kpiCards([
      ['已开票总额', money(d.amount), `${d.count} 张`],
      ['未开票 TOP10 合计', money(d.uninvoiced_top10_total), '', 'money-red'],
    ]);
    makeChart('chIType', {
      type: 'doughnut',
      data: {
        labels: d.by_type.map(r => r.label),
        datasets: [{ data: d.by_type.map(r => r.amount), backgroundColor: ['#1a56db', '#12b76a', '#f79009', '#98a2b3'] }]
      },
      options: { maintainAspectRatio: false }
    });
    makeChart('chIMonth', barChartCfg(d.by_month.map(r => r.label),
      [{ label: '开票额', data: d.by_month.map(r => r.amount), backgroundColor: '#7a5af8' }]));
    pane.querySelector('#tblITop').innerHTML = `
      <table><thead><tr><th>合同编号</th><th>客户</th><th class="num">合同额</th><th class="num">已开票</th><th class="num">未开票</th></tr></thead>
      <tbody>${d.top_uninvoiced.map(r => `<tr><td>${esc(r.contract_no)}</td><td>${esc(r.customer)}</td>
        <td class="num">${money(r.amount)}</td><td class="num">${money(r.invoiced)}</td>
        <td class="num money-red">${money(r.uninvoiced)}</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">全部开完，无未开票合同</td></tr>'}</tbody></table>`;
  };
  pane.querySelector('#fltI button').onclick = load;
  await load();
}

/* ---- 账龄分析 ---- */
async function renderTabAging(pane) {
  const aging = await get('/api/stats/aging');
  const buckets = ['未排期', '未到期', '1-30天', '31-60天', '61-90天', '90天以上'];
  const colors = ['#475467', '#98a2b3', '#f79009', '#f04438', '#b42318', '#7a271a'];
  pane.innerHTML = `
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
        <h3>账龄分析（按客户，单位：元）</h3>
        <button class="btn btn-sm" data-export="aging">📥 导出 Excel</button></div>
      <div class="table-wrap"><table><thead><tr><th>客户</th>${buckets.map(b => `<th class="num">${b}</th>`).join('')}<th class="num">合计</th></tr></thead>
      <tbody>${aging.map(a => `<tr><td>${esc(a.customer)}</td>
        ${buckets.map(b => `<td class="num ${a[b] > 0 && b !== '未到期' ? 'money-red' : ''}">${a[b] ? money(a[b]) : '-'}</td>`).join('')}
        <td class="num money-red">${money(a.total)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">暂无应收款项</td></tr>'}
      </tbody></table></div>
      ${aging.length ? '<div class="chart-box" style="margin-top:14px"><canvas id="chAging"></canvas></div>' : ''}
    </div>`;
  if (aging.length) {
    makeChart('chAging', {
      type: 'bar',
      data: {
        labels: aging.map(a => a.customer),
        datasets: buckets.map((b, i) => ({ label: b, data: aging.map(a => a[b]), backgroundColor: colors[i], stack: 's' }))
      },
      options: { maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true } } }
    });
  }
}

/* ---- 产品/服务维度 ---- */
async function renderTabProduct(pane) {
  let users = [];
  if (ME.role !== 'sales') { try { users = (await get('/api/users')).filter(u => u.active); } catch (e) {} }
  pane.innerHTML = `
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
        <h3>产品维度统计（按合同明细分摊回款/开票）</h3>
        <button class="btn btn-sm" data-export="by-product" data-bar="fltProd">📥 导出 Excel</button></div>
      ${statFilterBar('fltProd', users)}
      <div class="table-wrap" id="tblProd"></div>
      <div class="chart-box" style="margin-top:14px"><canvas id="chProd"></canvas></div>
    </div>`;
  await bindItemStat(pane, 'fltProd', '/api/stats/by-product', 'tblProd', 'chProd', '产品');
}

async function renderTabService(pane) {
  let users = [];
  if (ME.role !== 'sales') { try { users = (await get('/api/users')).filter(u => u.active); } catch (e) {} }
  pane.innerHTML = `
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
        <h3>服务维度统计（按服务类型汇总）</h3>
        <button class="btn btn-sm" data-export="by-service" data-bar="fltSvc">📥 导出 Excel</button></div>
      ${statFilterBar('fltSvc', users)}
      <div class="table-wrap" id="tblSvc"></div>
      <div class="chart-box" style="margin-top:14px"><canvas id="chSvc"></canvas></div>
    </div>`;
  await bindItemStat(pane, 'fltSvc', '/api/stats/by-service', 'tblSvc', 'chSvc', '服务类型');
}

/* ---- 业绩统计 ---- */
async function renderTabPerf(pane) {
  let perf = { rows: [], year: '' };
  let perfErr = '';
  try { perf = await get('/api/stats/performance'); } catch (e) { perfErr = e.message; }
  pane.innerHTML = `
    <div class="card"><div style="display:flex;justify-content:space-between;align-items:center">
        <h3>业务员业绩统计（${perf.year} 年）</h3>
        <button class="btn btn-sm" data-export="performance">📥 导出 Excel</button></div>
      ${perfErr ? `<div class="empty">${esc(perfErr)}</div>` : `
      <div class="table-wrap"><table><thead><tr><th>业务员</th><th class="num">客户数</th><th class="num">签约合同</th>
        <th class="num">签约额</th><th class="num">回款额</th><th class="num">未收余额</th><th class="num">回款率</th></tr></thead>
      <tbody>${perf.rows.map(r => `<tr><td>${esc(r.name)}</td><td class="num">${r.customers}</td>
        <td class="num">${r.contracts}</td><td class="num">${money(r.signed)}</td>
        <td class="num money-green">${money(r.received)}</td><td class="num money-red">${money(r.outstanding)}</td>
        <td class="num">${r.signed > 0 ? Math.round(r.received / r.signed * 100) + '%' : '-'}</td></tr>`).join('')
        || '<tr><td colspan="7" class="empty">暂无数据</td></tr>'}</tbody></table></div>
      ${perf.rows.length ? '<div class="chart-box" style="margin-top:14px"><canvas id="chPerf"></canvas></div>' : ''}`}
    </div>`;
  if (perf.rows.length) {
    makeChart('chPerf', {
      type: 'bar',
      data: {
        labels: perf.rows.map(r => r.name),
        datasets: [
          { label: '签约额', data: perf.rows.map(r => r.signed), backgroundColor: '#1a56db' },
          { label: '回款额', data: perf.rows.map(r => r.received), backgroundColor: '#12b76a' },
        ]
      },
      options: { maintainAspectRatio: false }
    });
  }
}

/* ---------------- 用户管理 ---------------- */
async function renderAdmin(view) {
  if (ME.role !== 'admin') { view.innerHTML = '<div class="empty">仅管理员可访问</div>'; return; }
  const list = await get('/api/users');
  const roleName = { admin: '老板/管理员', sales: '业务', finance: '财务', manager: '工厂经理', engineer: '工艺工程师' };
  view.innerHTML = `
    <div class="toolbar"><button class="btn btn-primary" id="btnAdd">+ 新增账号</button></div>
    <div class="card table-wrap"><table>
      <thead><tr><th>用户名</th><th>姓名</th><th>角色</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
      <tbody>${list.map(u => `<tr><td>${esc(u.username)}</td><td>${esc(u.name)}</td>
        <td>${roleName[u.role]}</td>
        <td><span class="tag tag-${u.active ? 'green' : 'gray'}">${u.active ? '启用' : '停用'}</span></td>
        <td>${(u.created_at || '').slice(0, 10)}</td>
        <td>
          <button class="btn btn-sm" data-rst="${u.id}">重置密码</button>
          ${u.id !== ME.id ? `<button class="btn btn-sm ${u.active ? 'btn-danger' : ''}" data-tgl="${u.id}" data-act="${u.active ? 0 : 1}">${u.active ? '停用' : '启用'}</button>` : ''}
        </td></tr>`).join('')}</tbody></table></div>`;
  view.querySelector('#btnAdd').onclick = () => {
    const { el, close } = openModal('新增账号', `
      <form id="f" class="form-grid">
        <label>用户名 *<input name="username" required></label>
        <label>姓名<input name="name"></label>
        <label>初始密码 *（至少6位）<input name="password" required minlength="6"></label>
        <label>角色<select name="role"><option value="sales">业务</option><option value="finance">财务</option><option value="manager">工厂经理</option><option value="engineer">工艺工程师</option><option value="admin">老板/管理员</option></select></label>
        <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
        <button class="btn btn-primary">创建</button></div>
      </form>`);
    el.querySelector('#cancel').onclick = close;
    el.querySelector('#f').onsubmit = async e => {
      e.preventDefault();
      try { await post('/api/users', Object.fromEntries(new FormData(e.target))); toast('已创建'); close(); renderAdmin(view); }
      catch (err) { toast(err.message, false); }
    };
  };
  view.querySelectorAll('[data-rst]').forEach(b => b.onclick = () => {
    const { el, close } = openModal('重置密码', `
      <form id="f" class="form-grid"><label class="full">新密码（至少6位）<input name="password" required minlength="6"></label>
      <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
      <button class="btn btn-primary">确定</button></div></form>`);
    el.querySelector('#cancel').onclick = close;
    el.querySelector('#f').onsubmit = async e => {
      e.preventDefault();
      try { await put(`/api/users/${b.dataset.rst}`, Object.fromEntries(new FormData(e.target))); toast('已重置'); close(); }
      catch (err) { toast(err.message, false); }
    };
  });
  view.querySelectorAll('[data-tgl]').forEach(b => b.onclick = async () => {
    await put(`/api/users/${b.dataset.tgl}`, { active: !!+b.dataset.act });
    toast('已更新'); renderAdmin(view);
  });
}

/* ---------------- 改密码 / 启动 ---------------- */
function bindTopbar() {
  document.getElementById('btnLogout').onclick = async () => { await post('/api/logout'); location.href = '/login.html'; };
  document.getElementById('btnPwd').onclick = () => {
    const { el, close } = openModal('修改密码', `
      <form id="f" class="form-grid">
        <label class="full">原密码<input name="old_password" type="password" required></label>
        <label class="full">新密码（至少6位）<input name="new_password" type="password" required minlength="6"></label>
        <div class="form-actions full"><button type="button" class="btn" id="cancel">取消</button>
        <button class="btn btn-primary">保存</button></div>
      </form>`);
    el.querySelector('#cancel').onclick = close;
    el.querySelector('#f').onsubmit = async e => {
      e.preventDefault();
      try { await post('/api/change-password', Object.fromEntries(new FormData(e.target))); toast('密码已修改'); close(); }
      catch (err) { toast(err.message, false); }
    };
  };
  document.getElementById('menuBtn').onclick = () => document.getElementById('sidebar').classList.toggle('open');
}

async function refreshBadge() {
  try {
    const d = await get('/api/reminders');
    const n = d.overdue.length + d.soon.length;
    const b = document.getElementById('remindBadge');
    b.style.display = n ? '' : 'none';
    b.textContent = n;
  } catch (e) { /* ignore */ }
}

(async function boot() {
  try { ME = await get('/api/me'); }
  catch (e) { location.href = '/login.html'; return; }
  try { DICTS = await get('/api/dicts'); } catch (e) { DICTS = {}; }
  document.getElementById('app').style.display = 'flex';
  document.getElementById('userInfo').textContent = `${ME.name}（${{ admin: '老板', sales: '业务', finance: '财务', manager: '工厂经理', engineer: '工艺工程师' }[ME.role]}）`;
  if (ME.role === 'admin') {
    document.getElementById('navAdmin').style.display = '';
    document.getElementById('navSettings').style.display = '';
    const modeWrap = document.getElementById('dataModeWrap');
    const modeSel = document.getElementById('dataMode');
    modeWrap.style.display = '';
    modeSel.value = ME.data_mode || 'real';
    modeSel.onchange = async () => {
      modeSel.disabled = true;
      try {
        await put('/api/data-mode', { mode: modeSel.value });
        route(); refreshBadge();
      } catch (e) { toast(e.message, false); }
      finally { modeSel.disabled = false; }
    };
  }
  if (ME.role === 'sales') document.getElementById('navAnalytics').style.display = 'none';
  applySettings();
  bindTopbar();
  window.addEventListener('hashchange', route);
  route();
  refreshBadge();
})();
