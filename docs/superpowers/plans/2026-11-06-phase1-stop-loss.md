# Phase 1 Stop-loss Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在不破坏既有数据的前提下，修复权限、默认秘密、收款/开票/发货约束和演示数据隔离。

**Architecture:** 保留单体 Flask 应用，在 `app.py` 增加统一输入校验、数据模式、角色装饰器和数据库计数器；`schema.sql` 同步新库结构。前端复用现有 `api()` 和页面，仅增加数据模式切换及权限一致的按钮显隐。

**Tech Stack:** Python 3、Flask、SQLite、原生 JavaScript；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-11-06-pvd-crm-upgrade-design.md`

## Global Constraints

- 默认仅显示正式数据；演示切换仅影响管理员当前会话。
- 不删除或重灌现有数据库，不修改云端资源。
- 项目原无测试目录，本轮使用临时数据库和内联 Python 回归，不新增测试脚手架。
- 不执行 Git commit。

## Review Focus

- NaN、Infinity、字符串和非法日期必须返回 400，不得写成异常金额或导致统计 500。
- 直接访问详情与列表过滤必须采用同一数据模式和归属规则。
- 超收校验必须同时考虑合同余额和期次余额，不指定期次的预收不得超过合同余额。
- 临时发货任何校验失败都不得留下合同、明细或计划。
- 已删除单号不得因计数器重置而重复使用。

### Task 1: 安全配置与权限边界

**Files:** `app.py`, `static/app.js`

- [ ] 用随机开发秘密替换固定密钥；生产模式强制 `CRM_SECRET` 和 Secure Cookie；新库管理员不再使用固定密码。
- [ ] 将角色装饰器前置并应用于用户、客户、合同、计划、收款、发票、明细、发货接口；发货详情校验合同归属。
- [ ] 前端按钮与后端角色矩阵一致，manager 不再看到无权限的产品/服务维护或财务写操作。
- [ ] 使用临时数据库验证 manager 不能登记/作废发票，finance 不能创建发货，sales 不能读取他人发货详情。

### Task 2: 金额、期次、发票与明细约束

**Files:** `app.py`, `schema.sql`

- [ ] 增加有限浮点数、正数、日期解析助手，相关接口返回明确 400。
- [ ] 收款时验证期次归属、期次余额和合同余额；发票验证号码唯一及有效开票余额；明细验证数量、单价。
- [ ] 新库增加发票号码唯一索引及必要的正数 CHECK；迁移对已有库先检查冲突，不静默删除冲突数据。
- [ ] 用真实 Flask API 验证跨合同期次、超收、重复发票、超开、负数量均被拒绝且数据库无新增记录。

### Task 3: 发货事务与可靠单号

**Files:** `app.py`, `schema.sql`

- [ ] 新增数据库计数器表和统一编号函数，保留 `FH-YYYYMMDD-NNN`、`LS-YYYYMMDD-NNNN` 格式。
- [ ] 合同发货必须引用本合同明细，累计数量不得超过合同量；临时发货在任何写入前完成全部校验。
- [ ] 新临时合同按发货日 +30 天创建全额回款计划，整个创建流程使用单事务。
- [ ] 验证超发、失败回滚、删除后新建和连续新建编号。

### Task 4: 演示数据隔离

**Files:** `app.py`, `schema.sql`, `static/app.js`, `static/index.html`, `static/style.css`

- [ ] 为 products/services 增加 is_demo；迁移现有 `remark='演示数据'` 记录。
- [ ] 增加会话级 real/demo/all 数据模式及管理员切换接口；所有列表、详情、看板、报表、提醒和导出应用相同范围。
- [ ] 顶栏仅向 admin 显示数据模式选择，非管理员始终使用正式数据；当前模式清晰可见。
- [ ] 验证默认统计不包含演示合同，demo 仅含演示数据，all 为两者合计，直接详情不能绕过范围。

### Task 5: 云端持久化与回归

**Files:** `backup.sh`, 必要时新增部署说明（仅在有实际配置需要时）

- [ ] 备份脚本跟随 `CRM_DB`，数据库与附件使用一致基础路径，避免环境变量生效后备份错文件。
- [ ] 查询 CloudBase 登录与环境；未登录则保留明确阻塞，不伪造核查结果。
- [ ] 在临时数据库运行完整 API 回归和 Python/JavaScript 语法检查，再对现有库做只读完整性及统计对照。
- [ ] 检查工作区新增产物，清理回归产生的临时文件，报告云端未核验项。
