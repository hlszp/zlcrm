#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灌入等离子镀膜（PVD）加工行业演示数据。所有演示数据 is_demo=1 / remark='演示数据'，可用 delete_demo.py 一键清除。"""
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CRM_DB", os.path.join(BASE_DIR, "data", "crm.db"))
if os.environ.get("CRM_ENV", "").lower() == "production" and "--force" not in sys.argv:
    raise SystemExit("生产环境禁止灌入演示数据；如确认目标库，请显式使用 --force")

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
con.execute("PRAGMA foreign_keys=ON")

if con.execute("SELECT COUNT(*) FROM customers WHERE is_demo=1").fetchone()[0]:
    print("演示数据已存在，跳过。如需重灌请先运行 delete_demo.py")
    raise SystemExit(0)

admin = con.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()[0]


def cust(name, contact, phone, industry, address):
    cur = con.execute(
        "INSERT INTO customers(name,contact,phone,industry,level,address,owner_id,remark,is_demo,created_by) "
        "VALUES(?,?,?,?,'A',?,?,?,1,?)",
        (name, contact, phone, industry, address, admin, "演示数据", admin))
    return cur.lastrowid


c1 = cust("【演示】锋刃刀具制造有限公司", "林锋", "13905710001", "切削刀具制造", "温岭市泽国镇机电工业园 6 号")
c2 = cust("【演示】精恒模具有限公司", "陈恒", "13805710002", "精密模具", "宁波市北仑区模具园区 18 号")
c3 = cust("【演示】恒洁卫浴科技有限公司", "王洁", "13705710003", "卫浴五金", "台州市玉环县楚门镇卫浴产业园")
c4 = cust("【演示】瑞表精密饰品厂", "赵瑞", "13605710004", "钟表饰品", "深圳市宝安区钟表产业基地 B3 栋")


def svc(name, typ, content, unit, price):
    cur = con.execute(
        "INSERT INTO services(name,type,content,unit,price,remark,is_demo) VALUES(?,?,?,?,?,?,1)",
        (name, typ, content, unit, price, "演示数据"))
    return cur.lastrowid


s_tin = svc("TiN氮化钛涂层（金色）", "刀具涂层", "刀具/冲头 TiN 涂层，膜厚 2-4μm，硬度 HV2300+，按炉计费", "炉", 2600)
s_crn = svc("CrN氮化铬涂层（银灰）", "模具涂层", "模具/顶针 CrN 涂层，耐磨耐腐蚀，膜厚 3-5μm", "炉", 2800)
s_dlc = svc("DLC类金刚石涂层（黑色）", "功能涂层", "DLC 涂层，摩擦系数<0.1，适用于精密滑动件", "炉", 4500)
s_rg = svc("卫浴件离子镀玫瑰金", "装饰镀膜", "卫浴龙头/挂件 PVD 玫瑰金，颜色均匀、耐蚀 96h 盐雾", "件", 8.5)
s_ipb = svc("表壳离子镀膜（IP黑）", "装饰镀膜", "表壳/饰品 IP 黑色镀膜，膜层结合力 5B", "件", 12.0)


def prod(name, model, spec, unit, price, category):
    cur = con.execute(
        "INSERT INTO products(name,model,spec,unit,price,category,remark,is_demo) VALUES(?,?,?,?,?,?,?,1)",
        (name, model, spec, unit, price, category, "演示数据"))
    return cur.lastrowid


p1 = prod("定制镀膜挂具", "GJ-DZ", "按工件图纸定制", "套", 3500, "工装治具")
p2 = prod("涂层结合力检测试片", "SP-10", "10片/盒", "盒", 260, "检测耗材")


def contract(no, cid, title, ctype, sign, status, items, plans, pays=(), invoices=()):
    cur = con.execute(
        "INSERT INTO contracts(contract_no,customer_id,title,type,amount,sign_date,status,owner_id,remark,is_demo,created_by) "
        "VALUES(?,?,?,?,0,?,?,?,?,1,?)",
        (no, cid, title, ctype, sign, status, admin, "演示数据", admin))
    ctid = cur.lastrowid
    total = 0
    item_ids = []
    for it in items:
        ref, itype, name, spec, qty, unit, price = it
        amt = round(qty * price, 2)
        total += amt
        cur = con.execute(
            "INSERT INTO contract_items(contract_id,item_type,ref_id,name,spec,quantity,unit,unit_price,amount) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (ctid, itype, ref, name, spec, qty, unit, price, amt))
        item_ids.append(cur.lastrowid)
    con.execute("UPDATE contracts SET amount=? WHERE id=?", (round(total, 2), ctid))
    plan_ids = []
    for i, (pname, amt, due) in enumerate(plans, 1):
        cur = con.execute(
            "INSERT INTO payment_plans(contract_id,seq,name,ratio,amount,due_date) VALUES(?,?,?,?,?,?)",
            (ctid, i, pname, 0, amt, due))
        plan_ids.append(cur.lastrowid)
    for amt, pd, method, plan_idx in pays:
        con.execute(
            "INSERT INTO payments(plan_id,contract_id,customer_id,amount,pay_date,method,remark,created_by) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (plan_ids[plan_idx] if plan_idx is not None else None, ctid, cid, amt, pd, method, "演示数据", admin))
    for ino, itype, amt, idate in invoices:
        con.execute(
            "INSERT INTO invoices(contract_id,invoice_no,type,amount,invoice_date,remark,created_by) "
            "VALUES(?,?,?,?,?,?,?)",
            (ctid, ino, itype, amt, idate, "演示数据", admin))
    return ctid, item_ids


# 合同1：刀具 TiN 涂层年度框架（月结，部分回款）
ct1, _ = contract(
    "HT-2026-0901", c1, "刀具TiN涂层年度框架加工协议", "service", "2026-09-01", "加工中",
    [(s_tin, "service", "TiN氮化钛涂层（金色）", "铣刀/钻头，按炉装炉", 20, "炉", 2600)],
    [("9月涂层加工费（月结30天）", 52000, "2026-10-01")],
    pays=[(30000, "2026-10-10", "银行转账", 0)],
    invoices=[("NO-20261010-01", "增值税专用发票", 30000, "2026-10-10")])

# 合同2：模具 CrN + 精密件 DLC（已逾期 2 天，演示预警）
ct2, ct2_items = contract(
    "HT-2026-1002", c2, "模具CrN涂层及精密件DLC加工", "service", "2026-10-05", "部分交付",
    [(s_crn, "service", "CrN氮化铬涂层（银灰）", "注塑模具型腔/顶针", 3, "炉", 2800),
     (s_dlc, "service", "DLC类金刚石涂层（黑色）", "精密滑动轴", 2, "炉", 4500)],
    [("加工费（月结30天）", 17400, "2026-11-04")])

# 合同3：挂具销售（已收讫）
ct3, _ = contract(
    "HT-2026-1015", c3, "定制镀膜挂具采购合同", "product", "2026-10-15", "已完成",
    [(p1, "product", "定制镀膜挂具", "按图定制", 2, "套", 3500),
     (p2, "product", "涂层结合力检测试片", "10片/盒", 5, "盒", 260)],
    [("一次性付款", 8300, "2026-10-15")],
    pays=[(8300, "2026-10-18", "承兑汇票", 0)],
    invoices=[("NO-20261020-01", "增值税普通发票", 8300, "2026-10-20")])

# 合同4：卫浴件玫瑰金镀膜（未到期）
ct4, _ = contract(
    "HT-2026-1103", c3, "卫浴挂件玫瑰金PVD镀膜合同", "service", "2026-11-03", "已签",
    [(s_rg, "service", "卫浴件离子镀玫瑰金", "龙头把手/挂件", 8000, "件", 8.5)],
    [("加工费（月结30天）", 68000, "2026-12-03")])


def shipment(sno, stype, ctid, cid, ship_date, to_addr, method, fee, items):
    cur = con.execute(
        "INSERT INTO shipments(shipment_no,type,contract_id,customer_id,ship_date,from_address,"
        "to_address,transport_method,transport_fee,remark,is_demo,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
        (sno, stype, ctid, cid, ship_date, "本厂PVD镀膜车间", to_addr, method, fee, "演示数据", admin))
    sid = cur.lastrowid
    for ciid, name, spec, qty, unit, price in items:
        con.execute(
            "INSERT INTO shipment_items(shipment_id,contract_item_id,name,spec,unit,quantity,unit_price,amount) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (sid, ciid, name, spec, unit, qty, price, round(qty * price, 2)))


# 合同发货：模具 CrN 先交付 1 炉
shipment("FH-20261020-001", "contract", ct2, c2, "2026-10-20", "宁波市北仑区模具园区 18 号",
         "物流托运", 350, [(ct2_items[0], "CrN氮化铬涂层（银灰）", "注塑模具型腔/顶针", 1, "炉", 2800)])

# 临时发货：表壳打样急件（自动建临时合同的场景在此直接模拟）
cur = con.execute(
    "INSERT INTO contracts(contract_no,customer_id,title,type,amount,sign_date,status,owner_id,remark,is_demo,created_by) "
    "VALUES('LS-20261102-0001',?,'临时发货-【演示】瑞表精密饰品厂-2026-11-02','service',1200,'2026-11-02','已签',?,?,1,?)",
    (c4, admin, "临时发货自动创建（演示）", admin))
tmp_ct = cur.lastrowid
cur = con.execute(
    "INSERT INTO contract_items(contract_id,item_type,name,spec,quantity,unit,unit_price,amount) "
    "VALUES(?,'other','表壳离子镀膜（IP黑）','新款表壳打样急件',100,'件',12,1200)", (tmp_ct,))
tmp_item = cur.lastrowid
shipment("FH-20261102-002", "temp", tmp_ct, c4, "2026-11-02", "深圳市宝安区钟表产业基地 B3 栋",
         "快递", 0, [(tmp_item, "表壳离子镀膜（IP黑）", "新款表壳打样急件", 100, "件", 12.0)])

# 跟进记录
for cid, content, nd in [
    (c1, "9月涂层费还差 2.2 万，林总说 11 月中旬安排", "2026-11-15"),
    (c2, "CrN 第 2 炉已装炉，DLC 等真空炉排产，本周可交付", "2026-11-08"),
    (c4, "新客户打样已确认颜色，批量订单预计月底下达，强调结合力检测报告随货", "2026-11-20")]:
    con.execute("INSERT INTO followups(customer_id,content,next_date,created_by) VALUES(?,?,?,?)",
                (cid, "【演示】" + content, nd, admin))

# 生产、质量、验收、对账、设备、成本和信用风险演示
for code, hours in [("PVD-01", 16), ("PVD-02", 12)]:
    con.execute("INSERT INTO equipment(code,name,daily_available_hours,remark,is_demo) VALUES(?,?,?,'演示设备',1)",
                (code, code, hours))

cur = con.execute(
    """INSERT INTO material_batches(batch_no,contract_id,customer_id,received_date,item_name,drawing_no,
       drawing_revision,material,received_qty,unit,surface_condition,status,remark,is_demo,created_by)
       VALUES('LL-20261006-001',?,?,?,'注塑模具型腔/顶针','MJ-2026-018','B','Cr12MoV',120,'件','已脱脂，无锈蚀','待验收','演示数据',1,?)""",
    (ct2, c2, "2026-10-06", admin))
batch_quality = cur.lastrowid
cur = con.execute(
    """INSERT INTO furnace_batches(furnace_no,batch_id,contract_id,process,recipe,equipment,operator_name,
       quantity,started_at,finished_at,status,remark,created_by)
       VALUES('LH-20261008-001',?,?,'CrN氮化铬(银灰)','CrN-标准-03','PVD-01','老周',120,
       '2026-10-08 08:00','2026-10-08 16:30','已质检','演示数据',?)""", (batch_quality, ct2, admin))
furnace_quality = cur.lastrowid
con.execute(
    """INSERT INTO quality_inspections(furnace_batch_id,batch_id,contract_id,inspection_date,inspector_name,
       inspected_qty,pass_qty,fail_qty,adhesion,film_thickness,salt_spray_hours,result,remark,created_by)
       VALUES(?,?,?,'2026-10-08','小周',120,118,2,'5B','3.2μm',96,'不合格','2件色差待返工（演示）',?)""",
    (furnace_quality, batch_quality, ct2, admin))
con.execute("UPDATE shipments SET batch_id=? WHERE contract_id=?", (batch_quality, ct2))
con.execute(
    """INSERT INTO acceptance_records(record_no,record_type,contract_id,batch_id,record_date,quantity,result,
       signed_by,proof_name,remark,created_by) VALUES('YS-20261021-001','验收',?,?,'2026-10-21',60,
       '部分通过','陈恒','验收单-20261021.jpg','其余工件待返工复验（演示）',?)""",
    (ct2, batch_quality, admin))

cur = con.execute(
    """INSERT INTO material_batches(batch_no,contract_id,customer_id,received_date,item_name,material,
       received_qty,unit,status,remark,is_demo,created_by) VALUES('LL-20261104-001',?,?,?,'卫浴龙头把手',
       '锌合金',8000,'件','加工中','PVD-02 加工中（演示）',1,?)""", (ct4, c3, "2026-11-04", admin))
batch_active = cur.lastrowid
con.execute(
    """INSERT INTO furnace_batches(furnace_no,batch_id,contract_id,process,equipment,operator_name,
       quantity,started_at,status,remark,created_by) VALUES('LH-20261105-001',?,?,'离子镀玫瑰金','PVD-02',
       '老周',4000,'2026-11-05 08:00','加工中','演示数据',?)""", (batch_active, ct4, admin))
con.execute(
    """INSERT INTO material_batches(batch_no,contract_id,customer_id,received_date,item_name,material,
       received_qty,unit,status,remark,is_demo,created_by) VALUES('LL-20261106-001',?,?,?,'铣刀/钻头',
       '硬质合金',500,'件','待排产','等待 PVD-01 空炉（演示）',1,?)""", (ct1, c1, "2026-11-06", admin))
con.execute(
    """INSERT INTO reconciliations(statement_no,contract_id,period_start,period_end,amount,status,
       confirmed_by,confirmed_at,remark,created_by) VALUES('DJ-20261001-001',?,'2026-09-01','2026-09-30',
       52000,'已确认','管理员','2026-10-01 10:00:00','9月月结对账（演示）',?)""", (ct1, admin))

for ctid, category, amount, day, note in [
    (ct1, "电费", 6000, "2026-10-31", "9月炉能耗分摊"),
    (ct1, "人工", 8000, "2026-10-31", "装炉与检验人工"),
    (ct1, "靶材气体", 5000, "2026-10-31", "Ti 靶及气体"),
    (ct1, "返工", 1000, "2026-11-02", "色差返工"),
    (ct2, "外协", 18000, "2026-11-03", "前处理与返工外协"),
    (ct4, "靶材气体", 12000, "2026-11-05", "玫瑰金靶材气体")]:
    con.execute("INSERT INTO cost_entries(contract_id,cost_date,category,amount,remark,created_by) VALUES(?,?,?,?,?,?)",
                (ctid, day, category, amount, note + "（演示）", admin))
con.execute("UPDATE customers SET credit_limit=30000,credit_hold=0 WHERE id=?", (c1,))
con.execute("UPDATE customers SET credit_limit=10000,credit_hold=0 WHERE id=?", (c2,))
con.execute("UPDATE customers SET credit_limit=1000,credit_hold=0 WHERE id=?", (c4,))

con.commit()
print("PVD 演示数据灌入完成：4 客户 / 5 服务 / 2 产品 / 5 合同(含1临时) / 2 发货单 / 3 跟进 / 生产质量成本风险场景")
print("清除方法：python3 delete_demo.py")
con.close()
