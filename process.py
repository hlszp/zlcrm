import math
import re


def validate_parameters(items):
    if not isinstance(items, list) or not items:
        raise ValueError("工艺至少需要一个参数")
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("参数格式无效")
        code = (item.get("code") or "").strip().upper()
        name = (item.get("name") or "").strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", code) or not name:
            raise ValueError("参数编码需以字母开头且只含字母数字下划线，参数名称必填")
        if code in seen:
            raise ValueError(f"参数编码 {code} 重复")
        seen.add(code)
        value_type = item.get("value_type") or "number"
        if value_type not in ("number", "text"):
            raise ValueError(f"参数 {code} 类型无效")
        result = {
            "code": code, "name": name, "stage": (item.get("stage") or "").strip(),
            "value_type": value_type, "unit": (item.get("unit") or "").strip(),
            "required": bool(item.get("required", False)),
            "target": item.get("target"), "min": item.get("min"), "max": item.get("max"),
        }
        if value_type == "number":
            for key in ("target", "min", "max"):
                value = result[key]
                if value in (None, ""):
                    result[key] = None
                    continue
                if isinstance(value, bool):
                    raise ValueError(f"参数 {code} 的{key}必须是数字")
                try:
                    result[key] = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"参数 {code} 的{key}必须是数字")
                if not math.isfinite(result[key]):
                    raise ValueError(f"参数 {code} 的{key}必须是有限数字")
            if result["min"] is not None and result["max"] is not None and result["min"] > result["max"]:
                raise ValueError(f"参数 {code} 下限不能大于上限")
            target = result["target"]
            if target is not None and ((result["min"] is not None and target < result["min"]) or
                                       (result["max"] is not None and target > result["max"])):
                raise ValueError(f"参数 {code} 标准值不能超出上下限")
        normalized.append(result)
    return normalized


def validate_steps(items):
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        raise ValueError("工序必须是数组")
    result = []
    for index, item in enumerate(items, 1):
        if isinstance(item, str):
            name = item.strip()
            item = {"name": name}
        if not isinstance(item, dict) or not (item.get("name") or "").strip():
            raise ValueError("工序名称必填")
        result.append({"seq": index, "name": item["name"].strip(),
                       "instruction": (item.get("instruction") or "").strip()})
    return result
