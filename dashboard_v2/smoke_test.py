"""Smoke-тест: рендерит каждую страницу дашборда через AppTest и ловит исключения.

Запуск: python dashboard_v2/smoke_test.py (venv с streamlit/plotly).
Гонять после правок в core/ или views/ перед коммитом.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from streamlit.testing.v1 import AppTest

DRIVER = '''
import sys
sys.path.insert(0, r"{root}")
import streamlit as st
from core import data
from core.context import build_context
from core.periods import default_period

df = data.load_sales()
cost_ref = data.load_cost_reference()
max_d = df["Дата"].max().date()
branches_all = sorted(df["Филиал"].dropna().astype(str).unique().tolist())
ap = {{
    "date_range": default_period(max_d, 30),
    "branches": branches_all, "points": [], "groups": [],
    "categories": [], "subcategories": [], "items": [],
    "abc_metric": "Сумма",
}}
ctx = build_context(df, ap, cost_ref)
from views import {module}
{module}.render(ctx)
'''

ROOT = str(Path(__file__).parent)
modules = ["overview", "dynamics", "abc", "branches", "products", "basket", "stock", "plan_fact"]
failed = []
for mod in modules:
    at = AppTest.from_string(DRIVER.format(root=ROOT, module=mod))
    try:
        at.run(timeout=120)
        if at.exception:
            failed.append(mod)
            print(f"FAIL {mod}:")
            for e in at.exception:
                print("   ", e.message)
                print("   ", (e.stack_trace or [""])[-1] if isinstance(e.stack_trace, list) else e.stack_trace)
        else:
            print(f"OK   {mod}")
    except Exception as e:
        failed.append(mod)
        print(f"CRASH {mod}: {e}")

print()
print("RESULT:", "ALL OK" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
