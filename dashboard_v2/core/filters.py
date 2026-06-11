"""Sidebar: кнопка обновления данных, пресеты периода, каскадная форма фильтров."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from category_mapping import GROUP_ORDER
from core.config import OWN_PERIOD_PAGES
from core.data import clear_caches
from core.periods import PRESETS, default_period, preset_range

_PRESET_LABELS = {
    "7 дней": "7 дн", "30 дней": "30 дн", "Тек. месяц": "Тек. мес",
    "Прош. месяц": "Прош. мес", "Квартал": "Квартал", "YTD": "YTD",
    "12 мес": "12 мес", "Вся история": "Всё",
}


def _default_ap(min_d, max_d, branches_all) -> dict:
    return {
        "date_range":    default_period(max_d, 30),
        "branches":      branches_all,
        "points":        [],
        "groups":        [],
        "categories":    [],
        "subcategories": [],
        "items":         [],
        "abc_metric":    "Сумма",
    }


def _cascade_options(df_src: pd.DataFrame, drafts: dict) -> dict:
    out = {}
    base = df_src
    if drafts.get("branches"):
        base = base[base["Филиал"].isin(drafts["branches"])]
    out["points"] = sorted(base["Точки"].dropna().astype(str).unique().tolist())
    if drafts.get("points"):
        base = base[base["Точки"].isin(drafts["points"])]
    out["groups"] = [g for g in GROUP_ORDER if g in base["Группа"].dropna().unique()]
    if drafts.get("groups"):
        base = base[base["Группа"].isin(drafts["groups"])]
    out["categories"] = sorted(base["Категория"].dropna().astype(str).unique().tolist())
    if drafts.get("categories"):
        base = base[base["Категория"].isin(drafts["categories"])]
    out["subcategories"] = sorted(base["Подкатегория"].dropna().astype(str).unique().tolist())
    if drafts.get("subcategories"):
        base = base[base["Подкатегория"].isin(drafts["subcategories"])]
    out["items"] = sorted(base["Номенклатура"].dropna().astype(str).unique().tolist())
    return out


def render_sidebar(df: pd.DataFrame, current_path: str) -> dict:
    min_d = df["Дата"].min().date()
    max_d = df["Дата"].max().date()
    branches_all = sorted(df["Филиал"].dropna().astype(str).unique().tolist())

    if "ap" not in st.session_state:
        st.session_state.ap = _default_ap(min_d, max_d, branches_all)
    if "fv" not in st.session_state:
        st.session_state.fv = 0   # filters version — чтобы форсить reset виджетов

    ap = st.session_state.ap
    # Санация: если границы дат / филиалы изменились — чиним
    if (ap["date_range"][0] < min_d) or (ap["date_range"][1] > max_d) \
            or not set(ap["branches"]).issubset(set(branches_all)):
        st.session_state.ap = _default_ap(min_d, max_d, branches_all)
        ap = st.session_state.ap
        st.session_state.fv += 1

    with st.sidebar:
        st.header("Фильтры")
        if current_path in OWN_PERIOD_PAGES:
            st.info("📌 Открытая страница использует **свой период** — "
                    "глобальный период ниже на неё не влияет.")

        def _apply_preset():
            p = st.session_state.get("ps_pick")
            if p:
                st.session_state.ap["date_range"] = preset_range(p, min_d, max_d)
                st.session_state.fv += 1
                st.session_state.ps_pick = None  # сброс выделения, чтобы чип не «залипал»

        st.pills(f"Быстрый период · от даты данных {max_d:%d.%m.%Y}",
                 PRESETS, format_func=lambda p: _PRESET_LABELS[p],
                 key="ps_pick", on_change=_apply_preset)

        with st.form("filters_form", clear_on_submit=False):
            fv = st.session_state.fv
            draft_dates = st.date_input(
                "Период",
                value=ap["date_range"], min_value=min_d, max_value=max_d,
                format="DD.MM.YYYY", key=f"dt_{fv}",
            )
            draft_branches = st.multiselect(
                "Филиал", branches_all, default=ap["branches"], key=f"br_{fv}",
            )

            _opts = _cascade_options(df, {"branches": draft_branches})
            draft_points = st.multiselect(
                "Точки", _opts["points"],
                default=[p for p in ap["points"] if p in _opts["points"]],
                key=f"pt_{fv}",
            )

            _opts = _cascade_options(df, {"branches": draft_branches, "points": draft_points})
            draft_groups = st.multiselect(
                "Группа (верхний уровень)", _opts["groups"],
                default=[g for g in ap["groups"] if g in _opts["groups"]],
                key=f"gp_{fv}",
            )

            _opts = _cascade_options(df, {
                "branches": draft_branches, "points": draft_points,
                "groups": draft_groups,
            })
            draft_cats = st.multiselect(
                "Категория", _opts["categories"],
                default=[c for c in ap["categories"] if c in _opts["categories"]],
                key=f"cat_{fv}",
            )

            _opts = _cascade_options(df, {
                "branches": draft_branches, "points": draft_points,
                "groups": draft_groups, "categories": draft_cats,
            })
            draft_subs = st.multiselect(
                "Подкатегория", _opts["subcategories"],
                default=[s for s in ap["subcategories"] if s in _opts["subcategories"]],
                key=f"sub_{fv}",
            )

            _opts = _cascade_options(df, {
                "branches": draft_branches, "points": draft_points,
                "groups": draft_groups, "categories": draft_cats,
                "subcategories": draft_subs,
            })
            draft_items = st.multiselect(
                "Номенклатура", _opts["items"],
                default=[i for i in ap["items"] if i in _opts["items"]],
                key=f"it_{fv}", help="Пусто — все SKU.",
            )

            draft_metric = st.radio(
                "Метрика (графики/ABC)", ["Сумма", "Количество"],
                index=0 if ap["abc_metric"] == "Сумма" else 1,
                horizontal=True, key=f"mt_{fv}",
            )

            if st.form_submit_button("Применить", width="stretch", type="primary"):
                if isinstance(draft_dates, tuple) and len(draft_dates) == 2:
                    d_from, d_to = draft_dates
                else:
                    d_from = d_to = draft_dates
                if d_from > d_to:
                    d_from, d_to = d_to, d_from
                if not draft_branches:
                    draft_branches = branches_all
                st.session_state.ap = {
                    "date_range": (d_from, d_to),
                    "branches": draft_branches, "points": draft_points,
                    "groups": draft_groups, "categories": draft_cats,
                    "subcategories": draft_subs, "items": draft_items,
                    "abc_metric": draft_metric,
                }
                st.rerun()

        if st.button("↩️ Сбросить фильтры", width="stretch",
                     help="Вернуть фильтры по умолчанию: последние 30 дней, все филиалы"):
            st.session_state.ap = _default_ap(min_d, max_d, branches_all)
            st.session_state.fv += 1
            st.rerun()

        st.divider()
        if st.button("🔄 Обновить данные", width="stretch",
                     help="Сбросить кеш и перечитать parquet с GitHub Pages"):
            clear_caches()
            st.rerun()

    return st.session_state.ap
