"""
YAHYA Sales Dashboard — entrypoint (Streamlit Cloud запускает этот файл).

Архитектура:
  core/   — загрузка данных (GitHub Pages), фильтры, KPI, LFL-сравнения,
            Plotly-графики, Excel-экспорт
  views/  — страницы (st.navigation): Обзор, Динамика, ABC, Товары,
            Корзина и прогноз, Филиалы, План/Факт, Склад

Принципы честных цифр:
  - период по умолчанию = последние 30 дней ДАННЫХ, не вся история;
  - сравнения like-for-like: филиалы, не работавшие полноценно в обоих
    периодах (открытия NGROUP/АЗБУКА, реконструкция АЗИЯ МОЛЛ), исключаются;
  - Δ% считаются по среднему/день — неравные периоды сопоставимы;
  - бейдж свежести данных в шапке.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="YAHYA — продажи",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core import data, filters, ui
from core.context import build_context
from views import abc, basket, branches, dynamics, overview, plan_fact, products, stock

ui.inject_css()

df = data.load_sales()
data.validate_minimum(df)
cost_ref = data.load_cost_reference()

# Pin: ключи виджетов с паттерном «инициализация по key» нужно переприсвоить
# на каждом ране, иначе Streamlit удаляет state виджетов, не отрисованных
# в текущем ране (т.е. при уходе на другую страницу периоды бы сбрасывались).
_PIN_PREFIXES = ("abc_single_", "abc_cmp_p")
_PIN_KEYS = {"dyn_from", "dyn_to", "pl_count"}
for _k in list(st.session_state.keys()):
    if _k.startswith(_PIN_PREFIXES) or _k in _PIN_KEYS:
        st.session_state[_k] = st.session_state[_k]

_CTX: dict = {}


def _page(render_fn, name: str):
    """Обёртка: st.Page требует callable с __name__, partial не подходит."""
    def fn():
        render_fn(_CTX["ctx"])
    fn.__name__ = name
    return fn


pg = st.navigation({
    "Главное": [
        st.Page(_page(overview.render, "overview"), title="Обзор", icon="🏠",
                url_path="overview", default=True),
        st.Page(_page(dynamics.render, "dynamics"), title="Динамика и выгрузка",
                icon="📈", url_path="dynamics"),
    ],
    "Ассортимент": [
        st.Page(_page(abc.render, "abc"), title="ABC / Pareto", icon="🔝",
                url_path="abc"),
        st.Page(_page(products.render, "products"), title="Товары", icon="🔍",
                url_path="products"),
        st.Page(_page(basket.render, "basket"), title="Корзина и прогноз", icon="🛒",
                url_path="basket"),
    ],
    "Сеть": [
        st.Page(_page(branches.render, "branches"), title="Филиалы и время", icon="🏢",
                url_path="branches"),
        st.Page(_page(plan_fact.render, "plan_fact"), title="План / Факт", icon="📋",
                url_path="plan-fact"),
    ],
    "Производство": [
        st.Page(_page(stock.render, "stock"), title="Склад и наборы", icon="🏭",
                url_path="stock"),
    ],
})

ap = filters.render_sidebar(df, pg.url_path)
ctx = build_context(df, ap, cost_ref)
_CTX["ctx"] = ctx

head_l, head_r = st.columns([3, 2])
with head_l:
    st.markdown("## 📊 YAHYA — продажи")
with head_r:
    ui.freshness_badge(ctx.max_d)
st.caption(
    f"🗓 {ctx.d_from:%d.%m.%Y} — {ctx.d_to:%d.%m.%Y} ({ctx.days_cnt} дн.)  "
    f"│ Филиалы: {len(ctx.ap['branches'])} из {df['Филиал'].nunique()}  "
    f"│ Метрика: {ctx.metric_col}"
)

pg.run()

st.divider()
st.caption("© YAHYA Sales Dashboard │ Данные: GitHub Pages (`/docs/*.parquet`) │ "
           "Маппинг категорий: `category_mapping.py`")
