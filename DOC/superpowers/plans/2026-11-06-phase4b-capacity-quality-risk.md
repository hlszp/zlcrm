# Phase 4B Capacity, Quality and Customer Risk Implementation Plan

**Goal:** 利用真实炉次、质检和应收数据形成设备产能、一次合格率及客户风险看板。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Tasks

1. 新增 equipment（设备编号、名称、每日可用工时、启停）；customers 增加 credit_limit、credit_hold，并提供编辑入口。
2. 新增 operations 统计：按期间和设备汇总炉次、装炉量、实际工时、平均时长和利用率；仅每台炉次第一次质检计入一次合格率。
3. 客户风险综合未收、逾期金额/天数、信用额度、停接标记和合同集中度，输出正常/关注/停接，不伪造评分。
4. 新增产能与风险分析页、设备维护、移动端风险清单及 Excel 导出。
5. 验证工时、利用率、首次质检、信用超限、停接、集中度、角色和演示隔离；迁移与全量回归。

## Constraints

未配置每日可用工时的设备利用率返回 null；没有质检时一次合格率返回 null。不把加权评分包装成精确信用模型。
