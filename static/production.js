'use strict';

function productionModal(title, body, onsubmit) {
  const { el, close } = openModal(title, `<form id="productionForm" class="form-grid">${body}<div class="form-actions full"><button type="button" class="btn" id="productionCancel">取消</button><button class="btn btn-primary">保存</button></div></form>`, true);
  el.querySelector('#productionCancel').onclick = close;
  el.querySelector('#productionForm').onsubmit = async e => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    for (const key of ['contract_id', 'received_qty', 'quantity', 'inspected_qty', 'pass_qty', 'fail_qty', 'salt_spray_hours']) {
      if (data[key] !== undefined && data[key] !== '') data[key] = +data[key];
    }
    try { await onsubmit(data); close(); } catch (err) { toast(err.message, false); }
  };
}

function productionEmpty(text, cols) { return `<tr><td colspan="${cols}" class="empty">${esc(text)}</td></tr>`; }

async function productionMaterials(view) {
  const list = await get('/api/production/materials');
  const canAdd = ['admin', 'sales', 'manager'].includes(ME.role);
  const canFurnace = ['admin', 'manager'].includes(ME.role);
  view.innerHTML = `<div class="toolbar">${canAdd ? '<button class="btn btn-primary" id="addMaterial">+ 来料登记</button>' : ''}</div><div class="card table-wrap"><table><thead><tr><th>批次</th><th>来料日期</th><th>客户/合同</th><th>工件</th><th>图号版本</th><th class="num">来料</th><th class="num">已排</th><th class="num">未排</th><th>状态</th><th></th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.batch_no)}</td><td>${esc(x.received_date)}</td><td>${esc(x.customer_name)}<br>${esc(x.contract_no)}</td><td>${esc(x.item_name)}<br><small>${esc(x.material || '-')}</small></td><td>${esc(x.drawing_no || '-')} ${esc(x.drawing_revision || '')}</td><td class="num">${x.received_qty}${esc(x.unit)}</td><td class="num">${x.scheduled_qty}</td><td class="num">${x.remaining_qty}</td><td>${statusTag(x.status)}</td><td>${canFurnace && x.remaining_qty > 0 ? `<button class="btn btn-sm btn-primary" data-furnace="${x.id}">排炉</button>` : ''}</td></tr>`).join('') || productionEmpty('暂未来料批次', 10)}</tbody></table></div>`;
  if (canAdd) view.querySelector('#addMaterial').onclick = () => materialBatchForm(view);
  view.querySelectorAll('[data-furnace]').forEach(b => b.onclick = () => furnaceBatchForm(list.find(x => x.id === +b.dataset.furnace), view));
}

async function materialBatchForm(view) {
  const contracts = await get('/api/contracts');
  productionModal('来料登记', `
    <label>关联合同 *<select name="contract_id" required>${contracts.map(c => `<option value="${c.id}">${esc(c.contract_no)} ${esc(c.title)}（${esc(c.customer_name)}）</option>`).join('')}</select></label>
    <label>来料日期<input name="received_date" type="date" value="${today()}"></label>
    <label>工件名称 *<input name="item_name" required></label>
    <label>材质<input name="material" placeholder="如：HSS / 硬质合金 / 不锈钢"></label>
    <label>图号<input name="drawing_no"></label><label>图纸版本<input name="drawing_revision"></label>
    <label>来料数量 *<input name="received_qty" type="number" min="0.01" step="0.01" required></label><label>单位<input name="unit" value="件"></label>
    <label class="full">表面状态<input name="surface_condition" placeholder="锈蚀、油污、划伤、预处理要求"></label>
    <label class="full">备注<textarea name="remark"></textarea></label>`, async d => {
      await post('/api/production/materials', d); toast('来料批次已创建'); productionMaterials(view);
    });
}

async function furnaceBatchForm(batch, view) {
  const equipment = await get('/api/equipment');
  productionModal(`排炉 - ${batch.batch_no}`, `
    <p class="full">${esc(batch.item_name)}，未排 ${batch.remaining_qty}${esc(batch.unit)}</p>
    <label>装炉数量 *<input name="quantity" type="number" min="0.01" max="${batch.remaining_qty}" step="0.01" required value="${batch.remaining_qty}"></label>
    <label>镀膜工艺 *<input name="process" required list="processOptions"><datalist id="processOptions">${dictLabels('coating_process').map(x => `<option value="${esc(x)}">`).join('')}</datalist></label>
    <label>设备/炉号<input name="equipment" list="equipmentOptions" placeholder="如：PVD-01"><datalist id="equipmentOptions">${equipment.filter(x => x.active).map(x => `<option value="${esc(x.code)}">${esc(x.name)}</option>`).join('')}</datalist></label><label>操作人<input name="operator_name"></label>
    <label>工艺配方/参数<input name="recipe"></label><label>开始时间<input name="started_at" type="datetime-local"></label>
    <label class="full">备注<textarea name="remark"></textarea></label>`, async d => {
      await post('/api/production/furnaces', { ...d, batch_id: batch.id }); toast('炉次已创建'); productionMaterials(view);
    });
}

async function productionFurnaces(view) {
  const list = await get('/api/production/furnaces');
  const canQuality = ['admin', 'manager'].includes(ME.role);
  view.innerHTML = `<div class="card table-wrap"><table><thead><tr><th>炉次</th><th>来料批次</th><th>工件</th><th>工艺</th><th>设备</th><th class="num">装炉量</th><th>状态</th><th>开始时间</th><th></th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.furnace_no)}</td><td>${esc(x.batch_no)}</td><td>${esc(x.item_name)}</td><td>${esc(x.process)}</td><td>${esc(x.equipment || '-')}</td><td class="num">${x.quantity}${esc(x.unit)}</td><td>${statusTag(x.status)}</td><td>${esc(x.started_at)}</td><td>${canQuality && x.inspected_qty < x.quantity ? `<button class="btn btn-sm btn-primary" data-quality="${x.id}">质检</button>` : ''}</td></tr>`).join('') || productionEmpty('暂无炉次', 9)}</tbody></table></div>`;
  view.querySelectorAll('[data-quality]').forEach(b => b.onclick = () => qualityInspectionForm(list.find(x => x.id === +b.dataset.quality), view));
}

async function qualityInspectionForm(furnace, view) {
  productionModal(`质检登记 - ${furnace.furnace_no}`, `
    <p class="full">${esc(furnace.item_name)}，装炉 ${furnace.quantity}${esc(furnace.unit)}</p>
    <label>检验日期<input name="inspection_date" type="date" value="${today()}"></label><label>检验人<input name="inspector_name"></label>
    <label>检验数量 *<input name="inspected_qty" type="number" min="0.01" max="${furnace.quantity}" step="0.01" required value="${furnace.quantity}"></label>
    <label>合格数量 *<input name="pass_qty" type="number" min="0" step="0.01" required value="${furnace.quantity}"></label>
    <label>不合格数量 *<input name="fail_qty" type="number" min="0" step="0.01" required value="0"></label>
    <label>检验结论<select name="result"><option>自动判定</option><option>让步接收</option></select></label>
    <label>结合力<input name="adhesion" placeholder="如：5B"></label><label>膜厚<input name="film_thickness" placeholder="如：2.8μm"></label>
    <label>盐雾小时<input name="salt_spray_hours" type="number" min="0"></label><label>报告名称<input name="report_name"></label>
    <label class="full">备注<textarea name="remark"></textarea></label>`, async d => {
      const r = await post('/api/production/quality', { ...d, furnace_batch_id: furnace.id }); toast(`质检已登记：${r.result}`); productionFurnaces(view);
    });
}

async function productionQuality(view) {
  const list = await get('/api/production/quality');
  view.innerHTML = `<div class="card table-wrap"><table><thead><tr><th>检验日期</th><th>批次/炉次</th><th>工件</th><th class="num">检验</th><th class="num">合格</th><th class="num">不合格</th><th>结论</th><th>结合力/膜厚</th><th>检验人</th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.inspection_date)}</td><td>${esc(x.batch_no)}<br>${esc(x.furnace_no)}</td><td>${esc(x.item_name)}</td><td class="num">${x.inspected_qty}</td><td class="num money-green">${x.pass_qty}</td><td class="num ${x.fail_qty > 0 ? 'money-red' : ''}">${x.fail_qty}</td><td>${statusTag(x.result)}</td><td>${esc(x.adhesion || '-')} / ${esc(x.film_thickness || '-')}</td><td>${esc(x.inspector_name || '-')}</td></tr>`).join('') || productionEmpty('暂无质检记录', 9)}</tbody></table></div>`;
}

async function acceptanceForm(view) {
  const [batches, shipments] = await Promise.all([get('/api/production/materials'), get('/api/shipments')]);
  const { el, close } = openModal('签收 / 验收登记', `<form id="acceptanceForm" class="form-grid">
    <label>记录类型<select name="record_type" id="acceptType"><option>签收</option><option>验收</option></select></label>
    <label>记录日期<input name="record_date" type="date" value="${today()}"></label>
    <label>关联来料批次<select name="batch_id" id="acceptBatch"><option value="">不关联</option>${batches.map(x => `<option value="${x.id}">${esc(x.batch_no)} ${esc(x.item_name)}（可验收 ${x.acceptance_remaining}${esc(x.unit)}）</option>`).join('')}</select></label>
    <label>关联发货单<select name="shipment_id" id="acceptShipment"><option value="">不关联</option>${shipments.map(x => `<option value="${x.id}">${esc(x.shipment_no)} ${esc(x.customer_name)}（${x.total_qty}）</option>`).join('')}</select></label>
    <label>数量 *<input name="quantity" type="number" min="0.01" step="0.01" required></label>
    <label>结论<select name="result" id="acceptResult"></select></label>
    <label>签收人/验收人 *<input name="signed_by" required></label><label>凭证名称<input name="proof_name"></label>
    <label class="full">备注<textarea name="remark"></textarea></label>
    <div class="form-actions full"><button type="button" class="btn" id="acceptCancel">取消</button><button class="btn btn-primary">保存</button></div></form>`, true);
  const type = el.querySelector('#acceptType'), result = el.querySelector('#acceptResult');
  const update = () => {
    const values = type.value === '签收' ? ['已签收', '拒收'] : ['通过', '部分通过', '不通过'];
    result.innerHTML = values.map(x => `<option>${x}</option>`).join('');
  };
  type.onchange = update; update();
  el.querySelector('#acceptCancel').onclick = close;
  el.querySelector('#acceptanceForm').onsubmit = async e => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(e.target)); d.quantity = +d.quantity;
    try { await post('/api/production/acceptances', d); toast('签收/验收已登记'); close(); productionAcceptances(view); }
    catch (err) { toast(err.message, false); }
  };
}

async function productionAcceptances(view) {
  const list = await get('/api/production/acceptances');
  const canAdd = ['admin', 'sales', 'manager'].includes(ME.role);
  view.innerHTML = `<div class="toolbar">${canAdd ? '<button class="btn btn-primary" id="addAcceptance">+ 签收/验收</button>' : ''}</div><div class="card table-wrap"><table><thead><tr><th>单号</th><th>类型</th><th>日期</th><th>客户/合同</th><th>批次/发货单</th><th class="num">数量</th><th>结论</th><th>签收/验收人</th><th>凭证</th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.record_no)}</td><td>${esc(x.record_type)}</td><td>${esc(x.record_date)}</td><td>${esc(x.customer_name)}<br>${esc(x.contract_no)}</td><td>${esc(x.batch_no || x.shipment_no || '-')}</td><td class="num">${x.quantity}</td><td>${statusTag(x.result)}</td><td>${esc(x.signed_by)}</td><td>${esc(x.proof_name || '-')}</td></tr>`).join('') || productionEmpty('暂无签收或验收记录', 9)}</tbody></table></div>`;
  if (canAdd) view.querySelector('#addAcceptance').onclick = () => acceptanceForm(view);
}

async function reconciliationForm(view) {
  const contracts = await get('/api/contracts');
  productionModal('新建对账单', `
    <label class="full">关联合同<select name="contract_id" required>${contracts.map(c => `<option value="${c.id}">${esc(c.contract_no)} ${esc(c.customer_name)}</option>`).join('')}</select></label>
    <label>期间开始<input name="period_start" type="date" required></label><label>期间结束<input name="period_end" type="date" required></label>
    <label>对账金额(元) *<input name="amount" type="number" min="0.01" step="0.01" required></label>
    <label class="full">备注<textarea name="remark"></textarea></label>`, async d => {
      await post('/api/reconciliations', d); toast('对账单已创建'); productionReconciliations(view);
    });
}

async function productionReconciliations(view) {
  const list = await get('/api/reconciliations');
  const canWrite = ['admin', 'finance'].includes(ME.role);
  view.innerHTML = `<div class="toolbar">${canWrite ? '<button class="btn btn-primary" id="addReconciliation">+ 新建对账单</button>' : ''}</div><div class="card table-wrap"><table><thead><tr><th>对账单号</th><th>客户/合同</th><th>期间</th><th class="num">金额</th><th>状态</th><th>确认人</th><th>备注</th><th></th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.statement_no)}</td><td>${esc(x.customer_name)}<br>${esc(x.contract_no)}</td><td>${esc(x.period_start)} 至 ${esc(x.period_end)}</td><td class="num">${money(x.amount)}</td><td>${statusTag(x.status)}</td><td>${esc(x.confirmed_by || '-')}</td><td>${esc(x.remark || '-')}</td><td>${canWrite && x.status === '待确认' ? `<button class="btn btn-sm btn-primary" data-confirmrec="${x.id}">确认</button><button class="btn btn-sm" data-disputerec="${x.id}">异议</button>` : ''}</td></tr>`).join('') || productionEmpty('暂无对账单', 8)}</tbody></table></div>`;
  if (canWrite) view.querySelector('#addReconciliation').onclick = () => reconciliationForm(view);
  view.querySelectorAll('[data-confirmrec]').forEach(b => b.onclick = () => confirmDo('确认该对账单？', async () => {
    try { await put(`/api/reconciliations/${b.dataset.confirmrec}`, { status: '已确认' }); toast('对账已确认'); productionReconciliations(view); }
    catch (e) { toast(e.message, false); }
  }));
  view.querySelectorAll('[data-disputerec]').forEach(b => b.onclick = () => {
    const { el, close } = openModal('登记对账异议', `<form id="disputeForm"><label>异议原因 *<input name="remark" required></label><div class="form-actions"><button type="button" class="btn" id="disputeCancel">取消</button><button class="btn btn-danger">登记异议</button></div></form>`);
    el.querySelector('#disputeCancel').onclick = close;
    el.querySelector('#disputeForm').onsubmit = async e => {
      e.preventDefault(); const d = Object.fromEntries(new FormData(e.target));
      try { await put(`/api/reconciliations/${b.dataset.disputerec}`, { ...d, status: '异议' }); toast('异议已登记'); close(); productionReconciliations(view); }
      catch (err) { toast(err.message, false); }
    };
  });
}

async function costEntryForm(view) {
  const [contracts, batches, furnaces] = await Promise.all([get('/api/contracts'), get('/api/production/materials'), get('/api/production/furnaces')]);
  productionModal('成本登记', `
    <label>关联合同<select name="contract_id" required>${contracts.map(c => `<option value="${c.id}">${esc(c.contract_no)} ${esc(c.customer_name)}</option>`).join('')}</select></label>
    <label>成本日期<input name="cost_date" type="date" value="${today()}"></label>
    <label>成本类别<select name="category">${dictLabels('cost_category').map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
    <label>金额(元) *<input name="amount" type="number" min="0.01" step="0.01" required></label>
    <label>关联批次<select name="batch_id"><option value="">不关联</option>${batches.map(x => `<option value="${x.id}">${esc(x.batch_no)} ${esc(x.item_name)}</option>`).join('')}</select></label>
    <label>关联炉次<select name="furnace_batch_id"><option value="">不关联</option>${furnaces.map(x => `<option value="${x.id}">${esc(x.furnace_no)} ${esc(x.process)}</option>`).join('')}</select></label>
    <label>供应商/费用对象<input name="supplier"></label><label>说明<input name="remark"></label>`, async d => {
      await post('/api/costs', d); toast('成本已登记'); productionCosts(view);
    });
}

async function productionCosts(view) {
  const list = await get('/api/costs');
  const canAdd = ['admin', 'finance', 'manager'].includes(ME.role);
  view.innerHTML = `<div class="toolbar">${canAdd ? '<button class="btn btn-primary" id="addCost">+ 成本登记</button>' : ''}</div><div class="card table-wrap"><table><thead><tr><th>日期</th><th>合同/客户</th><th>类别</th><th class="num">金额</th><th>批次/炉次</th><th>供应商/对象</th><th>说明</th><th></th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.cost_date)}</td><td>${esc(x.contract_no)}<br>${esc(x.customer_name)}</td><td>${esc(x.category)}</td><td class="num">${money(x.amount)}</td><td>${esc(x.batch_no || x.furnace_no || '-')}</td><td>${esc(x.supplier || '-')}</td><td>${esc(x.remark || '-')}</td><td>${ME.role === 'admin' ? `<button class="btn btn-sm btn-danger" data-delcost="${x.id}">删</button>` : ''}</td></tr>`).join('') || productionEmpty('暂无成本记录', 8)}</tbody></table></div>`;
  if (canAdd) view.querySelector('#addCost').onclick = () => costEntryForm(view);
  view.querySelectorAll('[data-delcost]').forEach(b => b.onclick = () => confirmDo('删除该成本记录？操作会保留审计快照。', async () => {
    try { await del(`/api/costs/${b.dataset.delcost}`); toast('成本已删除'); productionCosts(view); }
    catch (e) { toast(e.message, false); }
  }));
}

async function equipmentForm(view) {
  productionModal('新增设备', `<label>设备编号 *<input name="code" required placeholder="PVD-01"></label><label>设备名称 *<input name="name" required></label><label>每日可用工时 *<input name="daily_available_hours" type="number" min="0.1" max="24" step="0.1" value="16" required></label><label class="full">备注<textarea name="remark"></textarea></label>`, async d => {
    await post('/api/equipment', d); toast('设备已新增'); productionEquipment(view);
  });
}

async function productionEquipment(view) {
  const list = await get('/api/equipment');
  const canWrite = ['admin', 'manager'].includes(ME.role);
  view.innerHTML = `<div class="toolbar">${canWrite ? '<button class="btn btn-primary" id="addEquipment">+ 新增设备</button>' : ''}</div><div class="card table-wrap"><table><thead><tr><th>编号</th><th>名称</th><th class="num">每日可用工时</th><th>状态</th><th>备注</th><th></th></tr></thead><tbody>${list.map(x => `<tr><td>${esc(x.code)}</td><td>${esc(x.name)}</td><td class="num">${x.daily_available_hours}</td><td>${x.active ? '启用' : '停用'}</td><td>${esc(x.remark || '-')}</td><td>${canWrite ? `<button class="btn btn-sm" data-tglequipment="${x.id}" data-active="${x.active ? 0 : 1}">${x.active ? '停用' : '启用'}</button>` : ''}</td></tr>`).join('') || productionEmpty('暂无设备，请先维护每日可用工时', 6)}</tbody></table></div>`;
  if (canWrite) view.querySelector('#addEquipment').onclick = () => equipmentForm(view);
  view.querySelectorAll('[data-tglequipment]').forEach(b => b.onclick = async () => {
    try { await put(`/api/equipment/${b.dataset.tglequipment}`, { active: !!+b.dataset.active }); toast('设备状态已更新'); productionEquipment(view); }
    catch (e) { toast(e.message, false); }
  });
}

async function renderProduction(view) {
  const tabs = [['materials', '来料批次', productionMaterials], ['furnaces', '炉次管理', productionFurnaces], ['quality', '质量检验', productionQuality], ['acceptances', '签收验收', productionAcceptances], ['reconciliations', '对账管理', productionReconciliations], ['costs', '成本登记', productionCosts], ['equipment', '设备管理', productionEquipment]];
  view.innerHTML = `<div class="tabs">${tabs.map((x, i) => `<button class="tab ${i === 0 ? 'active' : ''}" data-prodtab="${x[0]}">${x[1]}</button>`).join('')}</div><div id="productionPane"><div class="loading">加载中…</div></div>`;
  const pane = view.querySelector('#productionPane');
  const show = async key => {
    view.querySelectorAll('[data-prodtab]').forEach(x => x.classList.toggle('active', x.dataset.prodtab === key));
    const tab = tabs.find(x => x[0] === key);
    try { await tab[2](pane); } catch (e) { pane.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  };
  view.querySelectorAll('[data-prodtab]').forEach(x => x.onclick = () => show(x.dataset.prodtab));
  await show('materials');
}
