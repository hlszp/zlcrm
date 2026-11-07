# Phase 3B Acceptance and Reconciliation Implementation Plan

**Goal:** 完成发货批次关联、签收、验收和合同对账闭环。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Tasks

1. shipments 增加 batch_id；创建发货时校验来料批次与合同一致，列表/详情/表单展示批次。
2. 新增 acceptance_records，支持签收和验收、部分数量、签收人、结论和凭证名称；累计数量不得超过发货或来料数量，验收结果回写批次状态。
3. 新增 reconciliations，支持期间、金额、待确认、已确认和异议；财务确认/异议写审计。
4. 生产协同新增“签收验收”和“对账”页面；全部操作执行合同归属、角色和演示范围控制。
5. 验证部分签收、超量、跨合同批次、验收状态回写、对账确认/异议和权限；备份并迁移现有库。
