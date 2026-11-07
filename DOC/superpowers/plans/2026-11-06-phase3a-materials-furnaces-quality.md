# Phase 3A Materials, Furnaces and Quality Implementation Plan

**Goal:** 建立 PVD 来料批次、炉次和质检的可追溯闭环，并约束数量与权限。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Tasks

1. 新增 material_batches、furnace_batches、quality_inspections；记录合同、客户、图号版本、材质、数量、工艺、设备、炉次和检验结果。
2. 新增列表与创建 API；合同归属、演示范围、admin/manager/sales/finance 权限由后端执行。炉次数量不得超过来料未排量，质检合格+不合格必须等于检验数量且不得超过炉次数量。
3. 新增“生产协同”页面及来料、炉次、质检录入；每条写操作记录审计，编号使用数据库计数器。
4. 工厂和移动看板增加待排产、加工中炉次、质量异常指标。
5. 临时库验证正常流程、超量、质量数量、越权和演示隔离；备份现有库后验证迁移和关键接口。

## Next slice

签收、验收、月度对账和发货批次关联在 Phase 3B 实现。
