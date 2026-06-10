"""Склад и наборы: неснижаемые остатки (safety stock) + разбивка BOM."""
from __future__ import annotations

import streamlit as st

from core.context import AppContext
from core.data import load_bom
from core.excel import dl_btn
from core.helpers import build_abc, build_components, build_safety_stock, money, num


def render(ctx: AppContext) -> None:
    st.subheader("🏭 Неснижаемые остатки — план производства")
    df_f = ctx.df_f
    if df_f.empty:
        st.info("Нет данных.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        cover = st.number_input("Норма остатка (дней)", 1, 30, 9, 1, key="ss_cover",
                                help="7 дн. до следующего понедельника + 2 дн. буфер = 9.")
    with c2:
        ss_m = st.radio("Метрика", ["Количество", "Сумма", "Оба"], horizontal=True, key="ss_m")
    with c3:
        abc_f = st.multiselect("ABC", ["A", "B", "C"], default=["A", "B", "C"], key="ss_abc")

    st.caption(
        f"📅 {ctx.d_from:%d.%m.%Y}–{ctx.d_to:%d.%m.%Y} ({ctx.days_cnt} дн.)  "
        f"│ Норма: **{cover} дн.**  │ Формула: `⌀/день × {cover}`"
    )

    abc_overall = build_abc(df_f, ["Номенклатура"], ctx.metric_col)
    ss = build_safety_stock(df_f, ctx.days_cnt, cover, abc_overall)
    if ss.empty:
        st.info("Нет данных.")
        return

    if abc_f and "ABC" in ss.columns:
        ss = ss[ss["ABC"].isin(abc_f + ["—"])]
    base_cols = ["Номенклатура"] + [c for c in ["Группа", "Категория", "Подкатегория"] if c in ss.columns]
    if ss_m == "Количество":
        show = base_cols + ["Итого (кол)", "Среднее/день (кол)", "Остаток (шт)", "ABC"]
    elif ss_m == "Сумма":
        show = base_cols + ["Итого (сом)", "Среднее/день (сом)", "Остаток (сом)", "ABC"]
    else:
        show = base_cols + ["Итого (кол)", "Итого (сом)", "Среднее/день (кол)", "Среднее/день (сом)",
                            "Остаток (шт)", "Остаток (сом)", "ABC"]
    show = [c for c in show if c in ss.columns]
    disp = ss[show].copy()
    for col in ["Среднее/день (кол)", "Среднее/день (сом)"]:
        if col in disp.columns:
            disp[col] = disp[col].round(2)
    for col in ["Итого (сом)", "Остаток (сом)"]:
        if col in disp.columns:
            disp[col] = disp[col].round(0)

    m1, m2, m3 = st.columns(3)
    m1.metric("Позиций", len(disp))
    if "Остаток (шт)" in disp.columns:
        m2.metric("Остаток итого (шт)", num(int(disp["Остаток (шт)"].sum())))
    if "Остаток (сом)" in disp.columns:
        m3.metric("Остаток итого (сом)", money(disp["Остаток (сом)"].sum()))

    st.dataframe(disp, width="stretch", hide_index=True, height=520)
    dl_btn("Скачать нормы остатков",
           [("Нормы остатков", ss, f"Неснижаемые {ctx.d_from:%d.%m}-{ctx.d_to:%d.%m} норма {cover}д")],
           filename=f"norms_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}_{cover}d.xlsx", key="dl_ss")

    # BOM
    st.divider()
    st.markdown("#### 📦 Разбивка наборов")
    bom = load_bom()
    if bom.empty:
        st.info("Файл разбивка_наборов.xlsx не найден.")
        return
    dfc, dfs = build_components(df_f, bom, ctx.days_cnt, cover)
    b1, b2 = st.columns(2)
    with b1:
        st.markdown("**Компоненты (производство)**")
        if dfc.empty:
            st.info("—")
        else:
            st.dataframe(dfc, width="stretch", hide_index=True, height=400)
    with b2:
        st.markdown("**Наборы (сборка)**")
        if dfs.empty:
            st.info("—")
        else:
            st.dataframe(dfs, width="stretch", hide_index=True, height=400)
    if not (dfc.empty and dfs.empty):
        dl_btn("Скачать разбивку",
               [("Компоненты", dfc, f"Производство {ctx.d_from:%d.%m}-{ctx.d_to:%d.%m}"),
                ("Наборы", dfs, f"Сборка наборов {cover}д")],
               filename=f"breakdown_{ctx.d_from:%Y%m%d}_{cover}d.xlsx", key="dl_bom")
