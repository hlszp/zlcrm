# 工艺寻优模块实施计划

## 技术路线

沿用 Flask + SQLite + 原生 JavaScript。后端新增独立 `/api/process/*` 接口和 `process.py` 数据访问/校验模块；前端新增 `static/process.js`，通过现有路由与权限体系接入。

## M1：配方与版本

- 新表：process_recipes、process_recipe_versions、process_parameter_defs。
- 新角色：engineer；保留历史用户和审计关联。
- API：配方列表/创建、版本创建/编辑/提交/发布、参数定义列表/创建。
- 版本发布使用事务，停用旧发布版本并更新配方当前版本。
- 页面提供配方列表、版本差异、参数编辑和审核发布。
- 回归：engineer 权限、销售拒绝、发布不可改、版本切换、演示隔离和审计。

## M2：批次执行与监控

- 新表：process_runs、process_run_values、process_events、process_attachments。
- 创建执行批次时锁定配方版本快照；校验炉次、合同、批次归属。
- 支持参数实测、异常、事件、草稿提交和审核；审核后修改写审计。
- 页面提供按工序录入、过程状态、缺失/超限/久未更新提示。

## M3：分析与改进

- 新表：process_improvements。
- 批次/版本对比、参数趋势、异常汇总、标杆批次和改进专题。
- 移动端只读工艺异常、待审核和改进效果。
- 临时库全链路回归、现有库备份迁移、线上部署和手机验收。

## 验证约束

不新增测试脚手架；使用临时数据库与内联真实 API 断言。不得运行生产演示灌入或清理脚本。
