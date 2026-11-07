#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键清除演示客户、合同、生产、财务、成本与设备及其关联记录。"""
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB", os.path.join(BASE_DIR, "data", "crm.db"))
if os.environ.get("CRM_ENV", "").lower() == "production" and "--force" not in sys.argv:
    raise SystemExit("生产环境禁止清除演示数据；如确认目标库，请显式使用 --force")

con = sqlite3.connect(DB_PATH)
con.execute("PRAGMA foreign_keys=ON")

ship_ids = [r[0] for r in con.execute("SELECT id FROM shipments WHERE is_demo=1")]
ct_ids = [r[0] for r in con.execute("SELECT id FROM contracts WHERE is_demo=1")]
cust_ids = [r[0] for r in con.execute("SELECT id FROM customers WHERE is_demo=1")]
equipment_ids = [r[0] for r in con.execute("SELECT id FROM equipment WHERE is_demo=1")]

if not (ship_ids or ct_ids or cust_ids or equipment_ids):
    print("没有演示数据")
    raise SystemExit(0)

q = lambda ids: ",".join("?" * len(ids))
if ct_ids:
    for tbl in ("acceptance_records", "quality_inspections", "cost_entries", "reconciliations", "contract_changes"):
        con.execute(f"DELETE FROM {tbl} WHERE contract_id IN ({q(ct_ids)})", ct_ids)
    con.execute(f"DELETE FROM furnace_batches WHERE contract_id IN ({q(ct_ids)})", ct_ids)
    extra_ships = [r[0] for r in con.execute(
        f"SELECT id FROM shipments WHERE contract_id IN ({q(ct_ids)})", ct_ids)]
    if extra_ships:
        con.execute(f"DELETE FROM acceptance_records WHERE shipment_id IN ({q(extra_ships)})", extra_ships)
        con.execute(f"DELETE FROM shipment_items WHERE shipment_id IN ({q(extra_ships)})", extra_ships)
        con.execute(f"DELETE FROM shipments WHERE id IN ({q(extra_ships)})", extra_ships)
    con.execute(f"DELETE FROM material_batches WHERE contract_id IN ({q(ct_ids)})", ct_ids)
    con.execute(f"DELETE FROM invoices WHERE red_invoice_of IN (SELECT id FROM invoices WHERE contract_id IN ({q(ct_ids)}))", ct_ids)
    for tbl in ("payments", "invoices", "payment_plans", "contract_items", "contract_files"):
        con.execute(f"DELETE FROM {tbl} WHERE contract_id IN ({q(ct_ids)})", ct_ids)
    con.execute(f"DELETE FROM contracts WHERE id IN ({q(ct_ids)})", ct_ids)
if cust_ids:
    con.execute("DELETE FROM followups WHERE customer_id IN ({})".format(q(cust_ids)), cust_ids)
    con.execute("DELETE FROM customers WHERE id IN ({})".format(q(cust_ids)), cust_ids)
if equipment_ids:
    con.execute(f"DELETE FROM equipment WHERE id IN ({q(equipment_ids)})", equipment_ids)

# 演示服务/产品（remark 标记，且无残留引用才删）
svc_demo = [r[0] for r in con.execute(
    "SELECT id FROM services WHERE remark='演示数据' AND NOT EXISTS "
    "(SELECT 1 FROM contract_items ci WHERE ci.item_type='service' AND ci.ref_id=services.id)")]
if svc_demo:
    con.execute(f"DELETE FROM services WHERE id IN ({q(svc_demo)})", svc_demo)
prod_demo = [r[0] for r in con.execute(
    "SELECT id FROM products WHERE remark='演示数据' AND NOT EXISTS "
    "(SELECT 1 FROM contract_items ci WHERE ci.item_type='product' AND ci.ref_id=products.id)")]
if prod_demo:
    con.execute(f"DELETE FROM products WHERE id IN ({q(prod_demo)})", prod_demo)

con.commit()
print(f"已清除：客户 {len(cust_ids)}，合同 {len(ct_ids)}，发货单 {len(ship_ids)}，"
      f"服务 {len(svc_demo)}，产品 {len(prod_demo)}，设备 {len(equipment_ids)}")
con.close()
