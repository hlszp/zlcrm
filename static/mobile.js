'use strict';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = value => '¥' + Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const modeNames = { real: '正式数据', demo: '演示数据', all: '全部数据' };

async function api(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (response.status === 401) { location.href = '/login.html'; throw new Error('登录已失效'); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `读取失败 (${response.status})`);
  return data;
}

function metric(label, value, cls = '', note = '') {
  return `<div class="metric${cls === 'lead' ? ' metric--lead' : ''}"><dt>${esc(label)}</dt><dd class="${cls === 'lead' ? '' : cls}">${esc(value)}</dd>${note ? `<small>${esc(note)}</small>` : ''}</div>`;
}

function records(target, items, empty, render) {
  $(target).innerHTML = items.length ? items.map(render).join('') : `<li class="state">${esc(empty)}</li>`;
}

function render(data) {
  $('status').hidden = true;
  $('dashboard').hidden = false;
  $('month').textContent = `${data.month} · 实时经营台账`;
  $('dataMode').textContent = modeNames[data.data_mode] || '正式数据';
  const k = data.kpis;
  $('kpis').innerHTML = [
    metric('合同未收余额', money(k.outstanding), 'lead', `在手合同 ${k.active_contracts} 份`),
    metric('本月回款', money(k.received_month), 'good', `本年 ${money(k.received_year)}`),
    metric('本月签约', money(k.signed_month)),
    metric('逾期应收', money(k.overdue_amount), k.overdue_count ? 'danger' : '', `${k.overdue_count} 笔`),
    metric('未开票', money(k.uninvoiced)),
    metric('未排期应收', money(k.unscheduled), k.unscheduled > 0 ? 'danger' : ''),
    metric('待核销收款', money(k.unallocated)),
    metric('未来 90 天计划回款', money(k.future90), 'instrument'),
    metric('交付逾期', `${k.delivery_overdue} 份`, k.delivery_overdue ? 'danger' : ''),
    metric('加工中炉次', `${k.furnaces_active} 炉`, 'instrument', `待排产批次 ${k.materials_pending}`),
    metric('质量异常', `${k.quality_exceptions} 次`, k.quality_exceptions ? 'danger' : ''),
    metric('本月归集成本', money(k.cost_month)),
    metric('预估毛利', money(k.gross_profit), k.gross_profit < 0 ? 'danger' : 'good', k.margin_rate === null ? '暂无合同' : `毛利率 ${k.margin_rate}%`),
    metric('产能利用率', k.capacity_utilization === null ? '未配置工时' : `${k.capacity_utilization}%`, 'instrument'),
    metric('一次合格率', k.first_pass_rate === null ? '暂无质检' : `${k.first_pass_rate}%`),
    metric('工艺异常 / 待审核', `${data.process.abnormal_runs} / ${data.process.pending_review}`, data.process.abnormal_runs ? 'danger' : '', `${data.process.stale_runs} 批超过 24 小时未更新`),
    metric('改进验证 / 已结案', `${data.process.improvements_active} / ${data.process.improvements_closed}`, 'instrument'),
    metric('停接 / 关注客户', `${k.risk_counts['停接']} / ${k.risk_counts['关注']} 家`, k.risk_counts['停接'] ? 'danger' : '', `TOP5 集中度 ${k.top5_concentration}%`),
  ].join('');
  $('overdueCount').textContent = `${k.overdue_count} 笔`;
  records('overdue', data.overdue, '当前没有逾期应收。', item => `<li class="record"><div><div class="record-title">${esc(item.customer)}</div><div class="record-meta">${esc(item.contract_no)} · ${esc(item.plan)} · 逾期 ${item.days} 天</div></div><div class="record-value danger">${money(item.remain)}</div></li>`);
  records('debtors', data.top_debtors, '当前没有合同欠款客户。', item => `<li class="record"><div><div class="record-title">${esc(item.name)}</div><div class="record-meta">合同 ${money(item.contracted)} · 已收 ${money(item.received)}</div></div><div class="record-value">${money(item.outstanding)}</div></li>`);
  $('deliveryCount').textContent = `${k.delivery_overdue} 份`;
  records('delivery', data.overdue_delivery, '当前没有交付逾期合同。', item => `<li class="record"><div><div class="record-title">${esc(item.customer)}</div><div class="record-meta">${esc(item.contract_no)} · ${esc(item.delivery_date)}</div></div><div class="record-value danger">${esc(item.status)}</div></li>`);
  $('customerRiskCount').textContent = `${data.customer_risks.length} 家`;
  records('customerRisks', data.customer_risks, '当前没有停接或关注客户。', item => `<li class="record"><div><div class="record-title">${esc(item.customer)}</div><div class="record-meta">${esc(item.risk)} · ${esc(item.reasons.join('；') || '无')}</div></div><div class="record-value danger">${money(item.outstanding)}</div></li>`);
  records('processAlerts', data.process_alerts, '当前没有工艺参数异常。', item => `<li class="record"><div><div class="record-title">${esc(item.recipe_name)} · ${esc(item.version_no)}</div><div class="record-meta">${esc(item.run_no)} · ${esc(item.furnace_no)}<br>${esc(item.abnormal_parameters || '存在异常参数')}</div></div><div class="record-value danger">${item.abnormal_values} 项</div></li>`);
  records('processImprovements', data.process_improvements, '暂无已结案的工艺改进。', item => `<li class="record"><div><div class="record-title">${esc(item.title)}</div><div class="record-meta">${esc(item.baseline_run_no || '-')} → ${esc(item.candidate_run_no || '-')}<br>${esc(item.conclusion)}</div></div><div class="record-value ${item.quality_delta < 0 ? 'danger' : 'good'}">${item.quality_delta === null ? '待对照' : `质量 ${item.quality_delta > 0 ? '+' : ''}${item.quality_delta}pp`}</div></li>`);
}

async function load() {
  $('refresh').disabled = true;
  $('status').hidden = false;
  $('status').className = 'state';
  $('status').textContent = '正在读取经营数据…';
  $('dashboard').hidden = true;
  try {
    const me = await api('/api/me');
    if (me.role !== 'admin') throw new Error('移动经营驾驶舱仅向老板/管理员开放');
    const [settings, data] = await Promise.all([api('/api/settings'), api('/api/mobile/boss')]);
    $('factoryName').textContent = settings.factory_name || '工厂经营';
    document.title = `经营驾驶舱 | ${settings.factory_name || '工厂经营'}`;
    render(data);
  } catch (error) {
    $('status').className = 'state state--error';
    $('status').textContent = `${error.message}。请检查权限或网络后点击刷新。`;
  } finally { $('refresh').disabled = false; }
}

$('refresh').addEventListener('click', load);
$('logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST' }); location.href = '/login.html'; });
load();
