# Phase 2B Allocations and Red Invoices Implementation Plan

**Goal:** 在不删除原始单据的情况下完成收款核销和发票红冲，并让所有统计使用核销/红冲后的净额。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Tasks

1. 新增 `payment_allocations`，迁移现有 `payments.plan_id` 为全额核销；统一计划已收和待核销计算。新增部分核销、取消核销 API，校验合同归属、付款未核销余额和期次余额。
2. 发票增加 `red_invoice_of` 与“红冲”状态；红冲记录为负数并关联原票，支持部分红冲，所有开票统计使用非作废净额。
3. 收款删除保留审计快照且仅 admin 可执行；核销、取消、红冲均写审计。合同详情和开票台账提供对应操作。
4. 使用临时数据库验证迁移、部分/多次核销、超额拒绝、取消核销、部分/全部红冲、超额红冲、越权、统计净额与演示隔离；备份后迁移现有库并跑全接口回归。

## Constraints

保留原 payments.plan_id 作为兼容字段，但业务统计以 payment_allocations 为准。红冲不修改原发票号码或金额。无新增依赖或测试脚手架。
