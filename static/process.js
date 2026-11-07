'use strict';

function processParameterRows(parameters = []) {
  return parameters.map((p, i) => `<tr><td><input data-p="code" data-i="${i}" value="${esc(p.code || '')}" required></td><td><input data-p="name" data-i="${i}" value="${esc(p.name || '')}" required></td><td><input data-p="stage" data-i="${i}" value="${esc(p.stage || '')}"></td><td><input data-p="unit" data-i="${i}" value="${esc(p.unit || '')}"></td><td><input data-p="target" data-i="${i}" type="number" step="any" value="${p.target ?? ''}"></td><td><input data-p="min" data-i="${i}" type="number" step="any" value="${p.min ?? ''}"></td><td><input data-p="max" data-i="${i}" type="number" step="any" value="${p.max ?? ''}"></td><td><input data-p="required" data-i="${i}" type="checkbox" ${p.required ? 'checked' : ''}></td><td><button type="button" class="btn btn-sm btn-danger" data-rmparam="${i}">删</button></td></tr>`).join('');
}

function bindProcessParameters(root, parameters) {
  const render = () => {
    root.querySelector('#parameterBody').innerHTML = processParameterRows(parameters);
    root.querySelectorAll('[data-p]').forEach(input => input.oninput = () => {
      const p = parameters[+input.dataset.i];
      p[input.dataset.p] = input.type === 'checkbox' ? input.checked : input.value;
    });
    root.querySelectorAll('[data-rmparam]').forEach(b => b.onclick = () => { parameters.splice(+b.dataset.rmparam, 1); render(); });
  };
  root.querySelector('#addParameter').onclick = () => {
    parameters.push({ code: '', name: '', stage: '', unit: '', target: '', min: '', max: '', required: false });
    render();
  };
  render();
  return () => parameters.map(p => ({
    ...p, target: p.target === '' ? null : +p.target,
    min: p.min === '' ? null : +p.min, max: p.max === '' ? null : +p.max,
  }));
}

function processParameterEditor(parameters) {
  return `<div class="full"><div class="section-title">工艺参数 <button type="button" class="btn btn-sm" id="addParameter">+ 添加参数</button></div><div class="table-wrap"><table><thead><tr><th>编码</th><th>名称</th><th>工序</th><th>单位</th><th>标准值</th><th>下限</th><th>上限</th><th>必填</th><th></th></tr></thead><tbody id="parameterBody"></tbody></table></div></div>`;
}

async function processRecipeForm(reload) {
  const { el, close } = openModal('新建工艺配方', `<form id="processRecipeForm" class="form-grid">
    <label>配方编码 *<input name="code" required placeholder="TIN-01"></label><label>配方名称 *<input name="name" required></label>
    <label>镀膜工艺 *<input name="coating_process" required></label><label>适用材料<input name="applicable_material"></label>
    <label>工件类别<input name="part_category"></label><label>设备编号<input name="equipment_code"></label>
    <label class="full">备注<textarea name="remark"></textarea></label>${processParameterEditor([])}
    <div class="form-actions full"><button type="button" class="btn" id="processCancel">取消</button><button class="btn btn-primary">创建 V1.0 草稿</button></div></form>`, true);
  const getParameters = bindProcessParameters(el, []);
  el.querySelector('#processCancel').onclick = close;
  el.querySelector('#processRecipeForm').onsubmit = async e => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(e.target)); d.parameters = getParameters();
    try { await post('/api/process/recipes', d); toast('工艺配方已创建'); close(); reload(); }
    catch (err) { toast(err.message, false); }
  };
}

async function processVersionForm(recipe, version, reload) {
  const parameters = (version?.parameters || []).map(x => ({ ...x }));
  const { el, close } = openModal(version ? `编辑 ${version.version_no}` : '创建工艺版本', `<form id="processVersionForm" class="form-grid">
    <label>版本号 *<input name="version_no" required value="${esc(version?.version_no || '')}" ${version ? 'readonly' : ''}></label>
    <label>变更原因 *<input name="change_reason" required value="${esc(version?.change_reason || '')}"></label>
    ${processParameterEditor(parameters)}<div class="form-actions full"><button type="button" class="btn" id="versionCancel">取消</button><button class="btn btn-primary">保存草稿</button></div></form>`, true);
  const getParameters = bindProcessParameters(el, parameters);
  el.querySelector('#versionCancel').onclick = close;
  el.querySelector('#processVersionForm').onsubmit = async e => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(e.target)); d.parameters = getParameters();
    try {
      if (version) await put(`/api/process/recipe-versions/${version.id}`, d);
      else await post(`/api/process/recipes/${recipe.id}/versions`, d);
      toast('工艺版本已保存'); close(); reload();
    } catch (err) { toast(err.message, false); }
  };
}

async function processRecipeDetail(id, reload) {
  const [recipes, versions] = await Promise.all([get('/api/process/recipes'), get(`/api/process/recipes/${id}/versions`)]);
  const recipe = recipes.find(x => x.id === id);
  const canWrite = ['admin', 'engineer'].includes(ME.role);
  const { el, close } = openModal(`${recipe.code} ${recipe.name}`, `
    <div class="form-grid"><div>工艺：${esc(recipe.coating_process)}</div><div>材料：${esc(recipe.applicable_material || '-')}</div><div>工件：${esc(recipe.part_category || '-')}</div><div>设备：${esc(recipe.equipment_code || '-')}</div><div class="full">当前发布版本：${esc(recipe.current_version?.version_no || '尚未发布')}</div></div>
    <div class="toolbar">${canWrite ? '<button class="btn btn-primary" id="newVersion">+ 创建新版本</button>' : ''}</div>
    <div class="table-wrap"><table><thead><tr><th>版本</th><th>状态</th><th>变更原因</th><th>参数数</th><th>创建人</th><th>审核人</th><th>操作</th></tr></thead><tbody>${versions.map(v => `<tr><td>${esc(v.version_no)}</td><td>${statusTag(v.status)}</td><td>${esc(v.change_reason)}</td><td>${v.parameters.length}</td><td>${esc(v.created_by_name || '')}</td><td>${esc(v.reviewed_by_name || '')}</td><td>${canWrite && v.status === '草稿' ? `<button class="btn btn-sm" data-editversion="${v.id}">编辑</button><button class="btn btn-sm btn-primary" data-submitversion="${v.id}">提交</button>` : ''}${ME.role === 'admin' && v.status === '待审核' ? `<button class="btn btn-sm btn-primary" data-publishversion="${v.id}">发布</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`, true);
  if (canWrite) el.querySelector('#newVersion').onclick = () => { close(); processVersionForm(recipe, null, () => processRecipeDetail(id, reload)); };
  el.querySelectorAll('[data-editversion]').forEach(b => b.onclick = () => { close(); processVersionForm(recipe, versions.find(v => v.id === +b.dataset.editversion), () => processRecipeDetail(id, reload)); });
  el.querySelectorAll('[data-submitversion]').forEach(b => b.onclick = async () => {
    try { await post(`/api/process/recipe-versions/${b.dataset.submitversion}/submit`, {}); toast('已提交审核'); close(); processRecipeDetail(id, reload); }
    catch (e) { toast(e.message, false); }
  });
  el.querySelectorAll('[data-publishversion]').forEach(b => b.onclick = () => confirmDo('发布该工艺版本？当前已发布版本将自动停用。', async () => {
    try { await post(`/api/process/recipe-versions/${b.dataset.publishversion}/publish`, {}); toast('版本已发布'); close(); processRecipeDetail(id, reload); }
    catch (e) { toast(e.message, false); }
  }));
}

function processTabs(active) {
  return `<div class="tabs">${[['recipes', '配方版本'], ['runs', '批次记录'], ['monitor', '过程监控'], ['analysis', '对比分析'], ['improvements', '改进专题']].map(([key, label]) =>
    `<button type="button" class="tab ${active === key ? 'active' : ''}" data-processtab="${key}">${label}</button>`).join('')}</div>`;
}

async function renderProcessRecipes(view) {
  const list = await get('/api/process/recipes');
  const canWrite = ['admin', 'engineer'].includes(ME.role);
  view.innerHTML = `<div class="toolbar"><input id="processSearch" placeholder="搜索配方编码 / 名称 / 工艺" style="flex:1;min-width:200px"><button class="btn" id="processSearchBtn">搜索</button>${canWrite ? '<button class="btn btn-primary" id="addRecipe">+ 新建工艺配方</button>' : ''}</div>
    <div class="card table-wrap"><table><thead><tr><th>配方编码</th><th>名称</th><th>工艺</th><th>材料</th><th>工件类别</th><th>设备</th><th>当前版本</th><th>状态</th></tr></thead><tbody id="processRows"></tbody></table></div>`;
  const draw = data => {
    view.querySelector('#processRows').innerHTML = data.map(x => `<tr class="clickable" data-recipe="${x.id}"><td>${esc(x.code)}</td><td>${esc(x.name)}</td><td>${esc(x.coating_process)}</td><td>${esc(x.applicable_material || '-')}</td><td>${esc(x.part_category || '-')}</td><td>${esc(x.equipment_code || '-')}</td><td>${esc(x.current_version?.version_no || '未发布')}</td><td>${statusTag(x.status)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">暂无工艺配方</td></tr>';
    view.querySelectorAll('[data-recipe]').forEach(tr => tr.onclick = () => processRecipeDetail(+tr.dataset.recipe, () => renderProcessRecipes(view)));
  };
  const search = () => {
    const q = view.querySelector('#processSearch').value.trim().toLowerCase();
    draw(list.filter(x => [x.code, x.name, x.coating_process].some(v => (v || '').toLowerCase().includes(q))));
  };
  view.querySelector('#processSearchBtn').onclick = search;
  view.querySelector('#processSearch').onkeydown = e => { if (e.key === 'Enter') search(); };
  if (canWrite) view.querySelector('#addRecipe').onclick = () => processRecipeForm(() => renderProcessRecipes(view));
  draw(list);
}

async function processRunForm(reload) {
  const [recipes, furnaces, runs] = await Promise.all([
    get('/api/process/recipes'), get('/api/production/furnaces'), get('/api/process/runs'),
  ]);
  const available = furnaces.filter(f => !runs.some(r => r.furnace_batch_id === f.id && r.status !== '已作废'));
  const published = recipes.filter(r => r.current_version);
  if (!available.length || !published.length) {
    toast(!available.length ? '暂无可创建工艺记录的炉次' : '请先在配方版本中发布工艺', false);
    return;
  }
  const { el, close } = openModal('创建工艺执行批次', `<form id="processRunForm" class="form-grid">
    <label class="full">生产炉次 *<select name="furnace_batch_id" required>${available.map(f => `<option value="${f.id}">${esc(f.furnace_no)} · ${esc(f.batch_no)} · ${esc(f.item_name)} · ${esc(f.customer_name)}</option>`).join('')}</select></label>
    <label class="full">当前发布配方 *<select name="recipe_version_id" required>${published.map(r => `<option value="${r.current_version.id}">${esc(r.code)} · ${esc(r.name)} · ${esc(r.current_version.version_no)}</option>`).join('')}</select></label>
    <label class="full">执行备注<textarea name="remark" rows="3"></textarea></label>
    <p class="full kpi-note">创建后锁定当前版本快照；后续配方变更不会影响本批次。</p>
    <div class="form-actions full"><button type="button" class="btn" id="runCancel">取消</button><button class="btn btn-primary">创建执行批次</button></div></form>`);
  el.querySelector('#runCancel').onclick = close;
  el.querySelector('#processRunForm').onsubmit = async e => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.furnace_batch_id = +d.furnace_batch_id; d.recipe_version_id = +d.recipe_version_id;
    try { await post('/api/process/runs', d); toast('工艺执行批次已创建'); close(); reload(); }
    catch (err) { toast(err.message, false); }
  };
}

function processValueStatus(value) {
  const labels = { '正常': 'green', '异常': 'red', '缺失': 'orange', '估读': 'blue' };
  return `<span class="tag tag-${labels[value] || 'gray'}">${esc(value)}</span>`;
}

function processEventForm(run, reload) {
  const localNow = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const { el, close } = openModal('记录工艺事件', `<form id="processEventForm" class="form-grid">
    <label>事件类型 *<select name="event_type">${['工序开始', '工序结束', '参数调整', '停机', '返工', '异常处理', '其他'].map(x => `<option>${x}</option>`).join('')}</select></label>
    <label>事件时间 *<input name="event_time" type="datetime-local" required value="${localNow}"></label>
    <label class="full">事件说明 *<textarea name="description" required rows="3" placeholder="记录调整内容、停机情况或处理结果"></textarea></label>
    <label class="full">原因 / 依据<textarea name="reason" rows="2"></textarea></label>
    <div class="form-actions full"><button type="button" class="btn" id="eventCancel">取消</button><button class="btn btn-primary">保存事件</button></div></form>`);
  el.querySelector('#eventCancel').onclick = close;
  el.querySelector('#processEventForm').onsubmit = async e => {
    e.preventDefault();
    try { await post(`/api/process/runs/${run.id}/events`, Object.fromEntries(new FormData(e.target))); toast('工艺事件已记录'); close(); reload(); }
    catch (err) { toast(err.message, false); }
  };
}

function processVoidForm(run, reload) {
  const { el, close } = openModal('作废工艺执行批次', `<form id="processVoidForm" class="form-grid">
    <p class="full">作废只改变记录状态，不删除实测参数、事件、附件和审计记录。</p>
    <label class="full">作废原因 *<textarea name="reason" required rows="3"></textarea></label>
    <div class="form-actions full"><button type="button" class="btn" id="voidCancel">取消</button><button class="btn btn-danger">确认作废</button></div></form>`);
  el.querySelector('#voidCancel').onclick = close;
  el.querySelector('#processVoidForm').onsubmit = async e => {
    e.preventDefault();
    try { await post(`/api/process/runs/${run.id}/void`, Object.fromEntries(new FormData(e.target))); toast('执行批次已作废'); close(); reload(); }
    catch (err) { toast(err.message, false); }
  };
}

async function processRunDetail(id, context, reload) {
  const run = await get(`/api/process/runs/${id}`);
  const canRecord = ['admin', 'manager', 'engineer'].includes(ME.role) && run.status !== '已作废';
  const canEditValues = canRecord && ['草稿', '已审核'].includes(run.status) && !(ME.role === 'manager' && run.status === '已审核');
  const canReview = ['admin', 'engineer'].includes(ME.role);
  const actions = `${run.status === '草稿' && canRecord ? '<button class="btn btn-primary" id="submitRun">提交审核</button>' : ''}
    ${run.status === '待审核' && canReview ? '<button class="btn btn-primary" id="reviewRun">审核通过</button>' : ''}
    ${canReview && run.status !== '已作废' ? '<button class="btn btn-danger" id="voidRun">作废</button>' : ''}`;
  const { el, close } = openModal(`${run.run_no} · ${context?.furnace_no || '工艺执行'}`, `
    <div class="form-grid"><div>配方：${esc(context?.recipe_name || run.recipe_id)} ${esc(context?.version_no || '')}</div><div>状态：${statusTag(run.status)}</div>
      <div>生产炉次：${esc(context?.furnace_no || run.furnace_batch_id)}</div><div>来料批次：${esc(context?.batch_no || run.batch_id)}</div>
      <div>合同：${esc(context?.contract_no || run.contract_id)}</div><div>最近更新：${esc(run.updated_at)}</div>
      <div class="full">备注：${esc(run.remark || '-')}</div></div>
    <div class="toolbar">${actions}</div>
    <form id="runValuesForm"><div class="section-title">参数实测 <span class="kpi-note">空值即为缺失；数值超限自动标记异常</span></div>
      <div class="table-wrap"><table><thead><tr><th>工序</th><th>参数</th><th>目标 / 上下限</th><th>实测值</th><th>数据状态</th><th>记录时间</th></tr></thead><tbody>
      ${run.values.map(v => `<tr><td>${esc(v.stage || '-')}</td><td>${esc(v.parameter_name)}<br><small>${esc(v.parameter_code)} · ${esc(v.unit)}</small></td>
        <td>${esc(v.target_value || '-')} / ${esc(v.min_value ?? '-')} ~ ${esc(v.max_value ?? '-')}</td>
        <td><input aria-label="${esc(v.parameter_name)}实测值" data-runvalue="${v.id}" type="${v.value_type === 'number' ? 'number' : 'text'}" ${v.value_type === 'number' ? 'step="any"' : ''} value="${esc(v.actual_numeric ?? v.actual_text)}" ${canEditValues ? '' : 'disabled'}></td>
        <td>${processValueStatus(v.status)}${canEditValues ? `<select data-runstatus="${v.id}" aria-label="${esc(v.parameter_name)}数据状态"><option ${v.status === '正常' ? 'selected' : ''}>正常</option><option ${v.status === '估读' ? 'selected' : ''}>估读</option><option ${v.status === '异常' ? 'selected' : ''}>异常</option></select>` : ''}</td><td>${esc(v.recorded_at || '-')}</td></tr>`).join('')}</tbody></table></div>
      ${canEditValues ? `<label>修订原因${run.status === '已审核' ? '（已审核记录，建议填写）' : ''}<input name="reason" placeholder="复核、补录或修订原因"></label><div class="form-actions"><button class="btn btn-primary">保存实测参数</button></div>` : ''}</form>
    <div class="section-title">工艺事件 ${canRecord ? '<button type="button" class="btn btn-sm" id="addRunEvent">+ 记录事件</button>' : ''}</div>
    <div class="table-wrap"><table><thead><tr><th>时间</th><th>类型</th><th>说明</th><th>原因</th><th>记录人</th></tr></thead><tbody>${run.events.map(e => `<tr><td>${esc(e.event_time)}</td><td>${esc(e.event_type)}</td><td>${esc(e.description)}</td><td>${esc(e.reason || '-')}</td><td>${esc(e.created_by_name || '-')}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">暂无工艺事件</td></tr>'}</tbody></table></div>
    <div class="section-title">证据附件</div>
    ${canRecord ? '<form id="runAttachmentForm" class="toolbar"><input type="file" name="file" required accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.csv,.xls,.xlsx"><button class="btn">上传附件</button><span class="kpi-note">单个请求不超过 20MB，不支持 SVG/HTML</span></form>' : ''}
    <div class="table-wrap"><table><thead><tr><th>文件</th><th>大小</th><th>上传人</th><th>时间</th></tr></thead><tbody>${run.attachments.map(a => `<tr><td><a href="/api/process/attachments/${a.id}" target="_blank" rel="noopener">${esc(a.orig_name)}</a></td><td>${(a.size / 1024).toFixed(1)} KB</td><td>${esc(a.uploaded_by_name || '-')}</td><td>${esc(a.created_at)}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">暂无附件</td></tr>'}</tbody></table></div>`, true);
  const reopen = () => { close(); processRunDetail(id, context, reload); };
  if (canEditValues) el.querySelector('#runValuesForm').onsubmit = async e => {
    e.preventDefault();
    const values = run.values.map(v => ({
      id: v.id,
      actual: el.querySelector(`[data-runvalue="${v.id}"]`).value,
      status: el.querySelector(`[data-runstatus="${v.id}"]`).value,
    }));
    try { await put(`/api/process/runs/${id}/values`, { values, reason: new FormData(e.target).get('reason') }); toast('实测参数已保存'); reopen(); }
    catch (err) { toast(err.message, false); }
  };
  if (el.querySelector('#submitRun')) el.querySelector('#submitRun').onclick = async () => {
    try { await post(`/api/process/runs/${id}/submit`, {}); toast('已提交审核'); reopen(); } catch (err) { toast(err.message, false); }
  };
  if (el.querySelector('#reviewRun')) el.querySelector('#reviewRun').onclick = () => confirmDo('确认审核通过？审核后的参数修订将保留审计记录。', async () => {
    try { await post(`/api/process/runs/${id}/review`, {}); toast('审核已完成'); reopen(); } catch (err) { toast(err.message, false); }
  });
  if (el.querySelector('#voidRun')) el.querySelector('#voidRun').onclick = () => { close(); processVoidForm(run, reload); };
  if (el.querySelector('#addRunEvent')) el.querySelector('#addRunEvent').onclick = () => { close(); processEventForm(run, () => processRunDetail(id, context, reload)); };
  if (el.querySelector('#runAttachmentForm')) el.querySelector('#runAttachmentForm').onsubmit = async e => {
    e.preventDefault();
    try { await post(`/api/process/runs/${id}/attachments`, new FormData(e.target)); toast('附件已上传'); reopen(); }
    catch (err) { toast(err.message, false); }
  };
}

async function renderProcessRuns(view) {
  const runs = await get('/api/process/runs');
  const canCreate = ['admin', 'manager', 'engineer'].includes(ME.role);
  view.innerHTML = `<div class="toolbar"><span class="kpi-note">每个炉次绑定一个有效工艺记录；版本快照、实测值与质量证据可追溯。</span>${canCreate ? '<button class="btn btn-primary" id="addProcessRun">+ 从炉次创建</button>' : ''}</div>
    <div class="card table-wrap"><table><thead><tr><th>执行编号</th><th>炉次 / 来料</th><th>客户 / 合同</th><th>配方版本</th><th>状态</th><th>异常参数</th><th>缺失参数</th><th>最近更新</th></tr></thead><tbody>
    ${runs.map(r => `<tr class="clickable" data-run="${r.id}"><td>${esc(r.run_no)}</td><td>${esc(r.furnace_no)}<br><small>${esc(r.batch_no)} · ${esc(r.item_name)}</small></td><td>${esc(r.customer_name)}<br><small>${esc(r.contract_no)}</small></td><td>${esc(r.recipe_name)}<br><small>${esc(r.version_no)}</small></td><td>${statusTag(r.status)}</td><td class="${r.abnormal_values ? 'money-red' : ''}">${r.abnormal_values}</td><td>${r.missing_values}</td><td>${esc(r.updated_at)}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">暂无工艺执行批次</td></tr>'}</tbody></table></div>`;
  if (canCreate) view.querySelector('#addProcessRun').onclick = () => processRunForm(() => renderProcessRuns(view));
  view.querySelectorAll('[data-run]').forEach(tr => tr.onclick = () => {
    const context = runs.find(r => r.id === +tr.dataset.run);
    processRunDetail(context.id, context, () => renderProcessRuns(view));
  });
}

function processMonitorSection(title, items, kind) {
  return `<div class="card"><h3>${title}</h3><div class="table-wrap"><table><thead><tr><th>执行编号 / 炉次</th><th>配方版本</th><th>客户 / 合同</th><th>状态</th><th>${kind === 'stale' ? '未更新时长' : '参数明细'}</th></tr></thead><tbody>
    ${items.map(r => `<tr class="clickable" data-monitorrun="${r.id}"><td>${esc(r.run_no)}<br><small>${esc(r.furnace_no)}</small></td><td>${esc(r.recipe_name)} ${esc(r.version_no)}</td><td>${esc(r.customer_name)}<br><small>${esc(r.contract_no)}</small></td><td>${statusTag(r.status)}</td><td>${kind === 'stale' ? `${esc(r.idle_hours)} 小时` : esc(kind === 'abnormal' ? r.abnormal_parameters : r.missing_parameters)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">当前没有需要处理的记录</td></tr>'}</tbody></table></div>`;
}

async function renderProcessMonitor(view) {
  const data = await get('/api/process/monitor');
  const cards = [['进行中 / 待审核', data.summary.active_runs], ['异常批次', data.summary.abnormal_runs], ['缺失批次', data.summary.missing_runs], ['待审核', data.summary.pending_review], ['超过 24 小时未更新', data.summary.stale_runs]];
  view.innerHTML = `<div class="toolbar"><span class="kpi-note">${esc(data.note)}</span><button class="btn" id="refreshMonitor">刷新</button></div>
    <div class="stat-grid">${cards.map(([label, value], i) => `<div class="stat-card"><div class="label">${label}</div><div class="value ${i > 0 && value ? 'red' : ''}">${value}</div></div>`).join('')}</div>
    ${processMonitorSection('超限与异常参数', data.abnormal, 'abnormal')}${processMonitorSection('缺失参数', data.missing, 'missing')}${processMonitorSection('久未更新记录', data.stale, 'stale')}`;
  view.querySelector('#refreshMonitor').onclick = () => renderProcessMonitor(view);
  const all = [...data.abnormal, ...data.missing, ...data.stale];
  view.querySelectorAll('[data-monitorrun]').forEach(tr => tr.onclick = () => {
    const context = all.find(r => r.id === +tr.dataset.monitorrun);
    processRunDetail(context.id, context, () => renderProcessMonitor(view));
  });
}

async function renderProcess(view) {
  const active = new URLSearchParams(location.hash.split('?')[1] || '').get('tab') || 'recipes';
  const tabs = ['recipes', 'runs', 'monitor', 'analysis', 'improvements'];
  const selected = tabs.includes(active) ? active : 'recipes';
  view.innerHTML = processTabs(selected) + '<div id="processContent"><div class="loading">加载中…</div></div>';
  view.querySelectorAll('[data-processtab]').forEach(b => b.onclick = () => { location.hash = `#/process?tab=${b.dataset.processtab}`; });
  const content = view.querySelector('#processContent');
  if (selected === 'runs') await renderProcessRuns(content);
  else if (selected === 'monitor') await renderProcessMonitor(content);
  else if (selected === 'analysis') await renderProcessAnalysis(content);
  else if (selected === 'improvements') await renderProcessImprovements(content);
  else await renderProcessRecipes(content);
}


function processDelta(value, unit = '') {
  if (value === null || value === undefined) return '-';
  return `${value > 0 ? '+' : ''}${value}${unit}`;
}

function processActual(value) {
  if (!value) return '-';
  const actual = value.actual_numeric ?? value.actual_text;
  return `${actual === '' || actual === null || actual === undefined ? '缺失' : actual} ${value.unit || ''}`;
}

async function processComparison(runIds) {
  const data = await get(`/api/process/compare?run_ids=${runIds.join(',')}`);
  const [left, right] = data.runs;
  openModal(`${left.run_no} ↔ ${right.run_no}`, `
    <div class="stat-grid"><div class="stat-card"><div class="label">质量合格率变化</div><div class="value">${processDelta(data.quality_delta, ' 个百分点')}</div></div>
      <div class="stat-card"><div class="label">炉次成本变化</div><div class="value">${data.cost_delta === null ? '-' : money(data.cost_delta)}</div></div>
      <div class="stat-card"><div class="label">生产周期变化</div><div class="value">${processDelta(data.duration_delta, ' 小时')}</div></div></div>
    <div class="table-wrap"><table><thead><tr><th>参数</th><th>${esc(left.run_no)}</th><th>${esc(right.run_no)}</th><th>差值（右-左）</th></tr></thead><tbody>
    ${data.parameters.map(p => `<tr><td>${esc(p.name)}<br><small>${esc(p.code)}</small></td><td>${esc(processActual(p.left))}<br>${p.left ? processValueStatus(p.left.status) : ''}</td><td>${esc(processActual(p.right))}<br>${p.right ? processValueStatus(p.right.status) : ''}</td><td>${p.difference === null ? '-' : `${processDelta(p.difference)} ${esc(p.unit)}`}</td></tr>`).join('')}</tbody></table></div>
    <p class="kpi-note">差值只用于两个批次的直接对照，不构成因果证明或自动参数推荐。</p>`, true);
}

async function renderProcessAnalysis(view) {
  const recipes = await get('/api/process/recipes');
  if (!recipes.length) {
    view.innerHTML = '<div class="card empty">请先建立并发布工艺配方，再记录执行批次。</div>';
    return;
  }
  let recipeId = recipes[0].id;
  let versions = await get(`/api/process/recipes/${recipeId}/versions`);
  view.innerHTML = `<div class="toolbar"><select id="analysisRecipe" aria-label="分析配方">${recipes.map(r => `<option value="${r.id}">${esc(r.code)} · ${esc(r.name)}</option>`).join('')}</select>
    <select id="analysisVersion" aria-label="分析版本"><option value="">全部版本</option></select><button class="btn" id="analysisRefresh">刷新分析</button></div><div id="analysisContent"></div>`;
  const versionSelect = view.querySelector('#analysisVersion');
  const syncVersions = () => {
    versionSelect.innerHTML = '<option value="">全部版本</option>' + versions.map(v => `<option value="${v.id}">${esc(v.version_no)} · ${esc(v.status)}</option>`).join('');
  };
  const draw = data => {
    const content = view.querySelector('#analysisContent');
    const s = data.summary;
    content.innerHTML = `<div class="stat-grid"><div class="stat-card"><div class="label">执行批次</div><div class="value">${s.runs}</div></div>
      <div class="stat-card"><div class="label">已审核批次</div><div class="value">${s.reviewed_runs}</div></div>
      <div class="stat-card"><div class="label">异常批次</div><div class="value ${s.abnormal_runs ? 'red' : ''}">${s.abnormal_runs}</div></div>
      <div class="stat-card"><div class="label">质量合格率</div><div class="value">${s.quality_rate === null ? '暂无质检' : `${s.quality_rate}%`}</div></div></div>
      <div class="grid-2"><div class="card"><div class="section-title">参数实测趋势 <select id="trendParameter" aria-label="趋势参数">${data.parameters.filter(p => p.count).map(p => `<option value="${esc(p.code)}">${esc(p.name)} (${esc(p.unit)})</option>`).join('')}</select></div><div class="chart-box"><canvas id="processTrend"></canvas></div></div>
      <div class="card"><h3>异常参数排序</h3><div class="table-wrap"><table><thead><tr><th>参数</th><th>异常记录数</th></tr></thead><tbody>${data.abnormal_pareto.map(p => `<tr><td>${esc(p.name)}<br><small>${esc(p.code)}</small></td><td>${p.count}</td></tr>`).join('') || '<tr><td colspan="2" class="empty">暂无异常参数</td></tr>'}</tbody></table></div></div></div>
      <div class="card"><h3>版本对比</h3><div class="table-wrap"><table><thead><tr><th>版本</th><th>批次 / 已审核</th><th>异常批次</th><th>质量合格率</th><th>平均炉次成本</th><th>平均周期</th></tr></thead><tbody>${data.versions.map(v => `<tr><td>${esc(v.version_no)}</td><td>${v.run_count} / ${v.reviewed_runs}</td><td>${v.abnormal_runs}</td><td>${v.quality_rate === null ? '-' : `${v.quality_rate}%`}</td><td>${v.avg_cost === null ? '-' : money(v.avg_cost)}</td><td>${v.avg_duration_hours === null ? '-' : `${v.avg_duration_hours} 小时`}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">暂无版本执行数据</td></tr>'}</tbody></table></div></div>
      <div class="card"><h3>参数描述性统计</h3><div class="table-wrap"><table><thead><tr><th>参数 / 工序</th><th>有效数值</th><th>均值</th><th>最小 ~ 最大</th><th>标准差</th><th>异常 / 缺失 / 估读</th><th>样本说明</th></tr></thead><tbody>${data.parameters.map(p => `<tr><td>${esc(p.name)} (${esc(p.unit)})<br><small>${esc(p.stage || '未分工序')}</small></td><td>${p.count}</td><td>${p.avg ?? '-'}</td><td>${p.min ?? '-'} ~ ${p.max ?? '-'}</td><td>${p.stddev ?? '-'}</td><td>${p.abnormal} / ${p.missing} / ${p.estimated}</td><td>${esc(p.sample_note)}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">暂无参数记录</td></tr>'}</tbody></table></div></div>
      <div class="card"><div class="section-title">批次证据与双批次对比 <button class="btn btn-primary" id="compareRuns" disabled>对比所选两个批次</button></div><div class="table-wrap"><table><thead><tr><th>选择</th><th>执行编号 / 炉次</th><th>版本</th><th>状态</th><th>质量合格率</th><th>成本</th><th>周期</th><th>异常 / 缺失</th></tr></thead><tbody>${data.runs.map(r => `<tr><td><input type="checkbox" data-compare="${r.id}" aria-label="选择 ${esc(r.run_no)}"></td><td>${esc(r.run_no)}<br><small>${esc(r.furnace_no)} · ${esc(r.batch_no)}</small></td><td>${esc(r.version_no)}</td><td>${statusTag(r.status)}</td><td>${r.quality_rate === null ? '暂无质检' : `${r.quality_rate}%`}</td><td>${r.cost === null ? '-' : money(r.cost)}</td><td>${r.duration_hours === null ? '-' : `${r.duration_hours} 小时`}</td><td>${r.abnormal_values} / ${r.missing_values}</td></tr>`).join('') || '<tr><td colspan="8" class="empty">暂无执行批次</td></tr>'}</tbody></table></div></div>
      <div class="card"><h3>标杆批次候选</h3><p class="kpi-note">${esc(data.benchmark_note)}</p><div class="table-wrap"><table><thead><tr><th>执行编号</th><th>版本</th><th>质量</th><th>成本</th><th>周期</th></tr></thead><tbody>${data.benchmark_candidates.map(r => `<tr><td>${esc(r.run_no)}</td><td>${esc(r.version_no)}</td><td>${r.quality_rate}%</td><td>${r.cost === null ? '未归集' : money(r.cost)}</td><td>${r.duration_hours === null ? '未记录' : `${r.duration_hours} 小时`}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">暂无满足条件的候选批次</td></tr>'}</tbody></table></div></div>`;
    const trendSelect = content.querySelector('#trendParameter');
    const drawTrend = () => {
      const parameter = data.parameters.find(p => p.code === trendSelect?.value);
      if (!parameter) return;
      makeChart('processTrend', { type: 'line', data: { labels: parameter.trend.map(x => x.run_no), datasets: [{ label: `${parameter.name} ${parameter.unit}`, data: parameter.trend.map(x => x.actual), borderColor: '#1a56db', backgroundColor: '#1a56db' }] }, options: { maintainAspectRatio: false } });
    };
    if (trendSelect) { trendSelect.onchange = drawTrend; drawTrend(); }
    const selected = new Set();
    const compareButton = content.querySelector('#compareRuns');
    content.querySelectorAll('[data-compare]').forEach(box => box.onchange = () => {
      if (box.checked && selected.size >= 2) { box.checked = false; toast('一次只能对比两个批次', false); return; }
      if (box.checked) selected.add(+box.dataset.compare); else selected.delete(+box.dataset.compare);
      compareButton.disabled = selected.size !== 2;
    });
    compareButton.onclick = () => processComparison([...selected]).catch(e => toast(e.message, false));
  };
  const load = async () => draw(await get(`/api/process/analysis?recipe_id=${recipeId}${versionSelect.value ? `&version_id=${versionSelect.value}` : ''}`));
  view.querySelector('#analysisRecipe').onchange = async e => {
    recipeId = +e.target.value; versions = await get(`/api/process/recipes/${recipeId}/versions`); syncVersions(); await load();
  };
  versionSelect.onchange = load; view.querySelector('#analysisRefresh').onclick = load;
  syncVersions(); await load();
}

function processImprovementDetail(item, reload) {
  const { el, close } = openModal(`${item.code} · ${item.title}`, `<div class="form-grid">
    <div>配方：${esc(item.recipe_code)} · ${esc(item.recipe_name)}</div><div>状态：${statusTag(item.status)}</div>
    <div class="full">问题：${esc(item.problem)}</div><div class="full">假设：${esc(item.hypothesis || '-')}</div>
    <div>基准批次：${esc(item.baseline_run_no || '未关联')}</div><div>候选批次：${esc(item.candidate_run_no || '未关联')}</div>
    <div>质量变化：${processDelta(item.quality_delta, ' 个百分点')}</div><div>成本变化：${item.cost_delta === null ? '-' : money(item.cost_delta)}</div>
    <div>形成版本：${esc(item.result_version_no || '未关联')}</div><div>改进变量：${esc(item.variables.join('、') || '-')}</div>
    <div class="full">结论：${esc(item.conclusion || '尚未结案')}</div></div>
    ${['admin', 'engineer'].includes(ME.role) && !['已结案', '已取消'].includes(item.status) ? '<div class="form-actions"><button class="btn btn-primary" id="editImprovement">编辑专题</button></div>' : ''}`, true);
  if (el.querySelector('#editImprovement')) el.querySelector('#editImprovement').onclick = () => { close(); processImprovementForm(item, reload); };
}

async function processImprovementForm(item, reload) {
  const [recipes, runs] = await Promise.all([get('/api/process/recipes'), get('/api/process/runs')]);
  if (!recipes.length) { toast('请先建立工艺配方', false); return; }
  const editingId = item?.id || null;
  let recipeId = item?.recipe_id || recipes[0].id;
  let versions = await get(`/api/process/recipes/${recipeId}/versions`);
  const { el, close } = openModal(item ? `编辑 ${item.code}` : '新建工艺改进专题', `<form id="improvementForm" class="form-grid">
    <label class="full">改进主题 *<input name="title" required value="${esc(item?.title || '')}"></label>
    <label class="full">关联配方 *<select name="recipe_id" id="improvementRecipe">${recipes.map(r => `<option value="${r.id}" ${r.id === recipeId ? 'selected' : ''}>${esc(r.code)} · ${esc(r.name)}</option>`).join('')}</select></label>
    <label class="full">问题描述 *<textarea name="problem" required rows="3">${esc(item?.problem || '')}</textarea></label>
    <label class="full">改进假设<textarea name="hypothesis" rows="2">${esc(item?.hypothesis || '')}</textarea></label>
    <label>基准批次<select name="baseline_run_id" id="baselineRun"></select></label><label>候选批次<select name="candidate_run_id" id="candidateRun"></select></label>
    <label>形成配方版本<select name="result_version_id" id="resultVersion"></select></label>
    <label>状态<select name="status">${['草稿', '验证中', '已结案', '已取消'].map(s => `<option ${item?.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
    <label class="full">改进变量（每行一个参数编码或说明）<textarea name="variables" rows="2">${esc(item?.variables.join('\n') || '')}</textarea></label>
    <label class="full">结论（结案时必填）<textarea name="conclusion" rows="3">${esc(item?.conclusion || '')}</textarea></label>
    <div class="form-actions full"><button type="button" class="btn" id="improvementCancel">取消</button><button class="btn btn-primary">保存专题</button></div></form>`, true);
  const syncRuns = () => {
    const eligible = runs.filter(r => r.recipe_id === recipeId && r.status !== '已作废');
    for (const [selector, current] of [['#baselineRun', item?.baseline_run_id], ['#candidateRun', item?.candidate_run_id]]) {
      el.querySelector(selector).innerHTML = '<option value="">不关联</option>' + eligible.map(r => `<option value="${r.id}" ${r.id === current ? 'selected' : ''}>${esc(r.run_no)} · ${esc(r.furnace_no)} · ${esc(r.version_no)}</option>`).join('');
    }
    el.querySelector('#resultVersion').innerHTML = '<option value="">不关联</option>' + versions.map(v => `<option value="${v.id}" ${v.id === item?.result_version_id ? 'selected' : ''}>${esc(v.version_no)} · ${esc(v.status)}</option>`).join('');
  };
  el.querySelector('#improvementRecipe').onchange = async e => {
    recipeId = +e.target.value; item = null; versions = await get(`/api/process/recipes/${recipeId}/versions`); syncRuns();
  };
  el.querySelector('#improvementCancel').onclick = close;
  el.querySelector('#improvementForm').onsubmit = async e => {
    e.preventDefault(); const raw = Object.fromEntries(new FormData(e.target));
    const d = { ...raw, recipe_id: +raw.recipe_id, variables: raw.variables.split('\n').map(x => x.trim()).filter(Boolean) };
    for (const key of ['baseline_run_id', 'candidate_run_id', 'result_version_id']) d[key] = raw[key] ? +raw[key] : null;
    try { if (editingId) await put(`/api/process/improvements/${editingId}`, d); else await post('/api/process/improvements', d); toast('改进专题已保存'); close(); reload(); }
    catch (err) { toast(err.message, false); }
  };
  syncRuns();
}

async function renderProcessImprovements(view) {
  const items = await get('/api/process/improvements');
  const canWrite = ['admin', 'engineer'].includes(ME.role);
  view.innerHTML = `<div class="toolbar"><span class="kpi-note">专题关联基准与候选批次；结案保留结论，已结案内容不可直接修改。</span>${canWrite ? '<button class="btn btn-primary" id="addImprovement">+ 新建改进专题</button>' : ''}</div>
    <div class="card table-wrap"><table><thead><tr><th>编号 / 主题</th><th>配方</th><th>基准 → 候选</th><th>质量变化</th><th>成本变化</th><th>形成版本</th><th>状态</th></tr></thead><tbody>${items.map(x => `<tr class="clickable" data-improvement="${x.id}"><td>${esc(x.code)}<br><small>${esc(x.title)}</small></td><td>${esc(x.recipe_name)}</td><td>${esc(x.baseline_run_no || '-')} → ${esc(x.candidate_run_no || '-')}</td><td>${processDelta(x.quality_delta, ' 个百分点')}</td><td>${x.cost_delta === null ? '-' : money(x.cost_delta)}</td><td>${esc(x.result_version_no || '-')}</td><td>${statusTag(x.status)}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">暂无改进专题</td></tr>'}</tbody></table></div>`;
  if (canWrite) view.querySelector('#addImprovement').onclick = () => processImprovementForm(null, () => renderProcessImprovements(view));
  view.querySelectorAll('[data-improvement]').forEach(tr => tr.onclick = () => {
    const item = items.find(x => x.id === +tr.dataset.improvement);
    processImprovementDetail(item, () => renderProcessImprovements(view));
  });
}
