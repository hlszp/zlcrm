# Phase 4A Cost and Estimated Margin Implementation Plan

**Goal:** 按合同归集 PVD 成本并向老板/财务提供可追溯的预估毛利。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Tasks

1. 新增 cost_entries，关联合同及可选批次/炉次，记录日期、类别、金额、供应商、说明和审计。
2. 新增成本列表/登记/管理员删除 API，校验正数、类别、合同归属和批次/炉次一致性；财务与生产经理可登记，业务员只读。
3. 新增 profitability 统计：合同额、成本、预估毛利、毛利率、成本类别和亏损合同；使用统一演示/负责人/日期范围。
4. 生产协同增加成本登记；老板/财务分析和移动端增加成本与预估毛利，提供 Excel 导出。
5. 验证成本归集、亏损、越权、非法关联、演示隔离、红冲不影响成本、迁移和导出。

## Next slice

设备产能、一次合格率和客户信用/集中度风险在 Phase 4B 实现。
