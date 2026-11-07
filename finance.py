def contract_balances(db, scope="", params=()):
    query = f"""
      SELECT ct.id, ct.customer_id, ct.contract_no, ct.amount, ct.status,
        COALESCE((SELECT SUM(pp.amount) FROM payment_plans pp WHERE pp.contract_id=ct.id),0) AS planned,
        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                  JOIN payments p ON p.id=pa.payment_id WHERE p.contract_id=ct.id),0) AS plan_received,
        COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.contract_id=ct.id),0) AS received,
        COALESCE((SELECT SUM(pa.amount) FROM payment_allocations pa
                  JOIN payments p ON p.id=pa.payment_id WHERE p.contract_id=ct.id),0) AS allocated,
        COALESCE((SELECT SUM(i.amount) FROM invoices i WHERE i.contract_id=ct.id AND i.status!='作废'),0) AS invoiced
      FROM contracts ct WHERE 1=1 {scope}
    """
    result = []
    for row in db.execute(query, params).fetchall():
        item = dict(row)
        for key in ("amount", "planned", "plan_received", "received", "allocated", "invoiced"):
            item[key] = round(item[key], 2)
        item["unallocated"] = round(item["received"] - item["allocated"], 2)
        item["outstanding"] = round(item["amount"] - item["received"], 2)
        item["uninvoiced"] = round(item["amount"] - item["invoiced"], 2)
        item["planned_remaining"] = round(max(item["planned"] - item["plan_received"], 0), 2)
        item["reported_planned_remaining"] = round(max(item["planned_remaining"] - item["unallocated"], 0), 2)
        item["unscheduled"] = round(max(item["amount"] - item["planned"], 0), 2)
        excess_unallocated = max(item["unallocated"] - item["planned_remaining"], 0)
        item["unscheduled_outstanding"] = round(max(item["unscheduled"] - excess_unallocated, 0), 2)
        item["tracked_outstanding"] = round(item["reported_planned_remaining"] + item["unscheduled_outstanding"], 2)
        item["reconciliation_difference"] = round(item["outstanding"] - item["tracked_outstanding"], 2)
        result.append(item)
    return result


def balance_totals(db, scope="", params=()):
    rows = contract_balances(db, scope, params)
    keys = ("amount", "planned", "plan_received", "received", "unallocated", "invoiced",
            "outstanding", "uninvoiced", "planned_remaining", "reported_planned_remaining", "unscheduled",
            "unscheduled_outstanding", "tracked_outstanding", "reconciliation_difference")
    return {key: round(sum(item[key] for item in rows), 2) for key in keys}
