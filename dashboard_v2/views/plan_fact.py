"""План / Факт — сравнение нескольких периодов по филиалам и точкам."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.context import AppContext
from core.excel import dl_btn
from core.helpers import money, num
from core.ui import own_period_note


def _plan_block(ctx: AppContext, df_base: pd.DataFrame, idx: int) -> pd.DataFrame | None:
    key = f"pl_{idx}"
    col_d, col_m = st.columns([3, 1])
    with col_d:
        period = st.date_input("Период", value=(ctx.d_from, ctx.d_to),
                               min_value=ctx.min_d, max_value=ctx.max_d,
                               format="DD.MM.YYYY", key=f"{key}_d",
                               label_visibility="collapsed")
    with col_m:
        m = st.radio("Метрика", ["Сумма", "Количество"],
                     index=0 if ctx.metric_col == "Сумма" else 1,
                     horizontal=True, key=f"{key}_m", label_visibility="collapsed")
    if not isinstance(period, tuple) or len(period) != 2:
        st.warning("Выбери период.")
        return None
    pf, pt = period
    if pf > pt:
        pf, pt = pt, pf
    dfp = df_base[(df_base["Дата"] >= pd.Timestamp(pf)) & (df_base["Дата"] <= pd.Timestamp(pt))]
    if dfp.empty:
        st.info("Нет данных.")
        return None
    col = "Сумма" if m == "Сумма" else "Количество"
    days_p = max((pt - pf).days + 1, 1)
    lbl = "Выручка" if col == "Сумма" else "Кол-во"
    g = (dfp.groupby(["Филиал", "Точки"], dropna=False)[col]
         .sum().reset_index().rename(columns={col: lbl}))
    g["⌀/день"] = (g[lbl] / days_p).round(1)
    bt = g.groupby("Филиал")[lbl].sum().reset_index().rename(columns={lbl: "BT"})
    g = g.merge(bt, on="Филиал", how="left")
    g["Доля"] = (g[lbl] / g["BT"] * 100).round(1).astype(str) + "%"
    g = g.drop(columns=["BT"]).sort_values(["Филиал", lbl], ascending=[True, False]).reset_index(drop=True)
    tr = pd.DataFrame([{
        "Филиал": "ИТОГО", "Точки": "—", lbl: g[lbl].sum(),
        "⌀/день": round(g[lbl].sum() / days_p, 1), "Доля": "100%"
    }])
    gd = pd.concat([g, tr], ignore_index=True)
    if col == "Сумма":
        gd[lbl] = gd[lbl].apply(money)
        gd["⌀/день"] = gd["⌀/день"].apply(money)
    else:
        gd[lbl] = gd[lbl].apply(lambda v: num(v))
        gd["⌀/день"] = gd["⌀/день"].apply(lambda v: f"{v:.1f}")
    st.caption(f"📅 {pf:%d.%m.%Y} — {pt:%d.%m.%Y} | {days_p} дн. | {lbl}")
    st.dataframe(gd, width="stretch", hide_index=True,
                 height=min(35 * len(gd) + 38, 520))
    exp = g.copy()
    exp.insert(0, "Период", f"{pf:%d.%m.%Y}–{pt:%d.%m.%Y}")
    return exp


def render(ctx: AppContext) -> None:
    st.subheader("📋 План / Факт — сравнение периодов по точкам")
    own_period_note()
    if ctx.df_universe.empty:
        st.info("Нет данных.")
        return

    dfb = ctx.df_universe  # все не-датовые фильтры уже применены

    if "pl_count" not in st.session_state:
        st.session_state["pl_count"] = 2
    n = st.session_state["pl_count"]

    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("＋ Период", width="stretch", key="pl_add"):
            st.session_state["pl_count"] += 1
            st.rerun()
    with b2:
        if n > 1 and st.button("－ Убрать", width="stretch", key="pl_rem"):
            st.session_state["pl_count"] -= 1
            st.rerun()

    st.divider()
    frames = []
    pairs = [(i, i + 1) for i in range(0, n, 2)]
    for pair in pairs:
        cs = st.columns(len([p for p in pair if p < n]), gap="large")
        for ci, bi in enumerate(pair):
            if bi >= n:
                break
            with cs[ci]:
                st.markdown(
                    f"<div style='background:#1F4E79;border-radius:6px;"
                    f"padding:4px 12px;margin-bottom:8px;'>"
                    f"<span style='color:white;font-weight:700;font-size:13px;'>"
                    f"Период {bi+1}</span></div>", unsafe_allow_html=True)
                r = _plan_block(ctx, dfb, bi)
                if r is not None:
                    frames.append((f"Период {bi+1}", r))
        if pair != pairs[-1]:
            st.divider()

    if frames:
        st.divider()
        sheets = [(name, f, f"Факт — {name}") for name, f in frames]
        sheets.append(("Все периоды", pd.concat([f for _, f in frames], ignore_index=True),
                       "Сводная"))
        dl_btn("Скачать план/факт", sheets,
               filename=f"plan_fact_{ctx.d_from:%Y%m%d}.xlsx", key="dl_pl")
