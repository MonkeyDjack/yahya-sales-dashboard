"""Товары: карточка SKU, календарь продаж, сезонность категорий."""
from __future__ import annotations

import calendar
from datetime import date

import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from core import charts
from core.config import CHECKS_COL
from core.context import AppContext
from core.excel import dl_btn
from core.helpers import build_abc, count_checks, money, num, safe_div
from core.ui import full_history_warning


def render(ctx: AppContext) -> None:
    st.subheader("🔍 Товары")
    tab_card, tab_cal, tab_seas = st.tabs(
        ["🔍 Карточка товара", "📅 Календарь SKU", "🗓 Сезонность"])
    with tab_card:
        _card_tab(ctx)
    with tab_cal:
        _calendar_tab(ctx)
    with tab_seas:
        _seasonality_tab(ctx)


# ---------------------------------------------------------------------------
# Карточка товара
# ---------------------------------------------------------------------------
def _card_tab(ctx: AppContext) -> None:
    st.caption("Каскадный фильтр Группа → Категория → Подкатегория, либо просто введи часть названия.")
    df, df_f = ctx.df, ctx.df_f

    sku_meta = (
        df.dropna(subset=["Номенклатура"])
        .groupby("Номенклатура", as_index=False)
        .agg(Группа=("Группа", "first"),
             Категория=("Категория", "first"),
             Подкатегория=("Подкатегория", "first"),
             _Выручка=("Сумма", "sum"),
             _Количество=("Количество", "sum"))
    )

    f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.2, 1.2, 1])
    with f_col1:
        groups_list = ["— все —"] + sorted(sku_meta["Группа"].dropna().unique().tolist())
        sel_group = st.selectbox("Группа", groups_list, key="card_group")
    pool = sku_meta if sel_group == "— все —" else sku_meta[sku_meta["Группа"] == sel_group]
    with f_col2:
        cats_list = ["— все —"] + sorted(pool["Категория"].dropna().unique().tolist())
        sel_cat = st.selectbox("Категория", cats_list, key="card_cat")
    if sel_cat != "— все —":
        pool = pool[pool["Категория"] == sel_cat]
    with f_col3:
        subs_list = ["— все —"] + sorted(pool["Подкатегория"].dropna().unique().tolist())
        sel_sub = st.selectbox("Подкатегория", subs_list, key="card_sub")
    if sel_sub != "— все —":
        pool = pool[pool["Подкатегория"] == sel_sub]
    with f_col4:
        sort_by = st.selectbox("Сортировка SKU", ["По выручке", "По количеству", "По алфавиту"],
                               key="card_sort")

    q = st.text_input("Поиск по названию", placeholder="например: финик, плитка pistachio, капучино",
                      key="card_q")
    if q:
        pool = pool[pool["Номенклатура"].str.contains(q, case=False, na=False)]

    if sort_by == "По выручке":
        pool = pool.sort_values("_Выручка", ascending=False)
    elif sort_by == "По количеству":
        pool = pool.sort_values("_Количество", ascending=False)
    else:
        pool = pool.sort_values("Номенклатура")

    st.caption(f"Найдено: **{len(pool)}** позиций")
    if pool.empty:
        st.info("Ничего не найдено по этим фильтрам.")
        return

    pool = pool.copy()
    pool["_label"] = pool.apply(
        lambda r: f"{r['Номенклатура']}  ·  {money(r['_Выручка'])} сом  ·  {num(r['_Количество'])} шт",
        axis=1)
    label_to_sku = dict(zip(pool["_label"], pool["Номенклатура"]))
    chosen_label = st.selectbox("Выбери позицию", pool["_label"].tolist(), key="sku_card_sel")
    chosen = label_to_sku[chosen_label]

    df_sku = df_f[df_f["Номенклатура"] == chosen].copy()
    df_sku_all = df[df["Номенклатура"] == chosen].copy()

    if df_sku.empty:
        st.warning("За выбранный период этот SKU не продавался. Показываю данные по всему диапазону.")
        df_sku = df_sku_all

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Выручка", money(float(df_sku["Сумма"].sum())))
    c2.metric("Количество", num(float(df_sku["Количество"].sum())))
    c3.metric("Чеков", num(count_checks(df_sku)))
    avg_price = safe_div(float(df_sku["Сумма"].sum()), float(df_sku["Количество"].sum()))
    c4.metric("Ср. цена", money(avg_price))
    c5.metric("Дней с продажами", num(df_sku["Дата"].dt.date.nunique()))

    meta_cols = [c for c in ["Группа", "Категория", "Подкатегория"] if c in df_sku.columns]
    if meta_cols:
        meta = df_sku[meta_cols].iloc[0]
        parts = " &nbsp;│&nbsp; ".join(f"<b>{k}:</b> {v}" for k, v in meta.items())
        if ctx.cost_ref is not None and not ctx.cost_ref.empty:
            row = ctx.cost_ref[ctx.cost_ref["Номенклатура"] == chosen]
            if not row.empty and pd.notna(row.iloc[0].get("Себес полн.")):
                cost = float(row.iloc[0]["Себес полн."])
                marg = avg_price - cost
                parts += (f" &nbsp;│&nbsp; <b>Себес:</b> {money(cost)} "
                          f"&nbsp;│&nbsp; <b>Маржа/шт:</b> {money(marg)}")
        st.markdown(f"<div class='insight-card'>{parts}</div>", unsafe_allow_html=True)

    st.divider()

    st.markdown("**Динамика продаж**")
    colA, colB = st.columns(2)
    daily_sku = (df_sku.groupby(df_sku["Дата"].dt.date)
                 .agg(Выручка=("Сумма", "sum"), Количество=("Количество", "sum"))
                 .reset_index().rename(columns={"Дата": "День"}))
    daily_sku["День"] = pd.to_datetime(daily_sku["День"])
    with colA:
        st.markdown("*По выручке*")
        st.bar_chart(daily_sku.set_index("День")["Выручка"], color="#1F4E79")
    with colB:
        st.markdown("*По количеству*")
        st.bar_chart(daily_sku.set_index("День")["Количество"], color="#E67E22")

    st.markdown("**Где продаётся**")
    by_br = df_sku.groupby(["Филиал", "Точки"]).agg(
        Выручка=("Сумма", "sum"), Количество=("Количество", "sum"),
        Чеков=(CHECKS_COL, "nunique")).reset_index().sort_values("Выручка", ascending=False)
    by_br["Выручка"] = by_br["Выручка"].apply(money)
    by_br["Количество"] = by_br["Количество"].apply(lambda v: num(v))
    st.dataframe(by_br, width="stretch", hide_index=True, height=300)

    abc_overall = build_abc(df_f, ["Номенклатура"], ctx.metric_col)
    if chosen in abc_overall["Номенклатура"].values:
        abc_row = abc_overall[abc_overall["Номенклатура"] == chosen].iloc[0]
        st.caption(f"🎯 ABC статус: **{abc_row['ABC']}**  "
                   f"│ Доля: {abc_row['Share']*100:.2f}%  "
                   f"│ Кум. доля: {abc_row['CumShare']*100:.2f}%")

    sub_of_sku = df_sku["Подкатегория"].iloc[0] if "Подкатегория" in df_sku.columns and not df_sku.empty else None
    if sub_of_sku and pd.notna(sub_of_sku):
        siblings = (df_f[(df_f["Подкатегория"] == sub_of_sku) & (df_f["Номенклатура"] != chosen)]
                    .groupby("Номенклатура")
                    .agg(Выручка=("Сумма", "sum"),
                         Количество=("Количество", "sum"),
                         Чеков=(CHECKS_COL, "nunique"))
                    .sort_values("Выручка", ascending=False).head(7).reset_index())
        if not siblings.empty:
            st.markdown(f"**Похожие в подкатегории «{sub_of_sku}»** (топ-7 по выручке)")
            sub_avg = float(siblings["Выручка"].mean())
            cur_rev = float(df_sku["Сумма"].sum())
            delta_vs_avg = (cur_rev - sub_avg) / sub_avg * 100 if sub_avg > 0 else 0
            arrow = "🟢" if delta_vs_avg >= 0 else "🔴"
            st.caption(f"{arrow} Выбранный SKU vs средний по подкатегории: "
                       f"**{delta_vs_avg:+.1f}%** ({money(cur_rev)} vs {money(sub_avg)})")
            siblings_show = siblings.copy()
            siblings_show["Выручка"] = siblings_show["Выручка"].apply(money)
            siblings_show["Количество"] = siblings_show["Количество"].apply(num)
            st.dataframe(siblings_show, width="stretch", hide_index=True, height=270)

    dl_btn("Скачать карточку",
           [("Динамика", daily_sku, f"Дневная динамика — {chosen[:30]}"),
            ("По точкам", df_sku.groupby(["Филиал", "Точки"]).agg(
                Выручка=("Сумма", "sum"), Количество=("Количество", "sum")).reset_index(),
             f"По точкам — {chosen[:30]}")],
           filename=f"sku_{chosen[:20].replace(' ', '_')}.xlsx", key="dl_sku")


# ---------------------------------------------------------------------------
# Календарь SKU (matplotlib — кастомный рендер месяца)
# ---------------------------------------------------------------------------
def _cal_heatmap(daily_series: pd.Series, year: int, month: int, vmax: float, cmap) -> plt.Figure:
    cal = calendar.monthcalendar(year, month)
    nw = len(cal)
    dow_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    mo_ru = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    fig, ax = plt.subplots(figsize=(7 * 1.0 + 1.2, (nw + 1.2) * 1.0))
    ax.set_xlim(0, 7)
    ax.set_ylim(0, nw + 1)
    ax.axis("off")
    ax.set_aspect("equal")
    fig.patch.set_facecolor("#F7F9FC")
    ax.text(3.5, nw + 0.65, f"{mo_ru[month]} {year}",
            ha="center", va="center", fontsize=13, fontweight="bold", color="#1F3864")
    for col, dn in enumerate(dow_ru):
        c = "#C0392B" if col >= 5 else "#1F3864"
        ax.text(col + 0.5, nw + 0.15, dn, ha="center", va="center",
                fontsize=9, fontweight="bold", color=c)
    norm = mcolors.Normalize(vmin=0, vmax=max(vmax, 1))
    for wi, week in enumerate(cal):
        row = nw - 1 - wi
        for dw, dn in enumerate(week):
            x, y = dw, row
            if dn == 0:
                r = mpatches.FancyBboxPatch(
                    (x + 0.06, y + 0.06), 0.88, 0.88,
                    boxstyle="round,pad=0.04", linewidth=0, facecolor="#ECEFF4")
                ax.add_patch(r)
                continue
            d = date(year, month, dn)
            val = float(daily_series.get(d, 0.0))
            is_we = dw >= 5
            if val > 0:
                rgba = cmap(norm(val))
                face = rgba
                tc = "white" if norm(val) > 0.55 else "#1F3864"
            else:
                face = "#ECEFF4" if not is_we else "#FAE5E5"
                tc = "#AABBCC"
            r = mpatches.FancyBboxPatch(
                (x + 0.06, y + 0.06), 0.88, 0.88,
                boxstyle="round,pad=0.05", linewidth=0.5,
                edgecolor="#CFD8E3", facecolor=face)
            ax.add_patch(r)
            ax.text(x + 0.12, y + 0.83, str(dn), ha="left", va="top",
                    fontsize=7, color=tc, alpha=0.7)
            if val > 0:
                s = f"{val:,.1f}".rstrip("0").rstrip(".") if val != int(val) else str(int(val))
                ax.text(x + 0.5, y + 0.42, s, ha="center", va="center",
                        fontsize=10.5, fontweight="bold", color=tc)
    fig.tight_layout(pad=0.3)
    return fig


def _months_in(d_from, d_to):
    out = []
    cur_d = date(d_from.year, d_from.month, 1)
    end_d = date(d_to.year, d_to.month, 1)
    while cur_d <= end_d:
        out.append((cur_d.year, cur_d.month))
        cur_d = date(cur_d.year + (1 if cur_d.month == 12 else 0),
                     1 if cur_d.month == 12 else cur_d.month + 1, 1)
    return out


def _calendar_tab(ctx: AppContext) -> None:
    df_f = ctx.df_f
    if df_f.empty:
        st.info("Нет данных.")
        return
    items = sorted(df_f["Номенклатура"].dropna().unique().tolist())
    if not items:
        st.info("Нет SKU.")
        return

    c1, c2 = st.columns(2)
    with c1:
        cal_metric = st.radio("Метрика", ["Количество", "Сумма"], horizontal=True, key="cal_m")
    with c2:
        show_all = st.checkbox("Все месяцы периода", value=False, key="cal_all")

    chosen_item = st.selectbox("Номенклатура", items, key="cal_sku")
    df_it = df_f[df_f["Номенклатура"] == chosen_item]
    if df_it.empty:
        st.info("Нет продаж.")
        return

    daily = df_it.groupby(df_it["Дата"].dt.date)[cal_metric].sum()
    daily.index = pd.to_datetime(daily.index).date
    total = float(daily.sum())
    days = int((daily > 0).sum())
    avg_d = total / days if days else 0.0
    label = "Продано" if cal_metric == "Количество" else "Выручка"
    st.caption(
        f"📦 {label}: **{money(total) if cal_metric == 'Сумма' else num(total, 2)}**  "
        f"│ 📅 Дней с продажами: **{days}**  │ ⌀/день: **"
        f"{money(avg_d) if cal_metric == 'Сумма' else num(avg_d, 2)}**"
    )
    cmap = plt.get_cmap("YlOrRd" if cal_metric == "Количество" else "Blues")
    vmax = float(daily.max()) if not daily.empty else 1.0
    months = _months_in(ctx.d_from, ctx.d_to)
    if not show_all and months:
        mo_ru = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                 "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        sel_ym = st.selectbox("Месяц", months,
                              format_func=lambda ym: f"{mo_ru[ym[1]]} {ym[0]}", key="cal_month")
        months = [sel_ym]
    for y, m in months:
        st.pyplot(_cal_heatmap(daily, y, m, vmax, cmap), clear_figure=True)


# ---------------------------------------------------------------------------
# Сезонность (вся история!)
# ---------------------------------------------------------------------------
def _seasonality_tab(ctx: AppContext) -> None:
    st.caption("Что продаётся в какой месяц лучше. По доле в месячной выручке.")
    full_history_warning(ctx.min_d, ctx.max_d)

    df = ctx.df
    if df.empty:
        st.info("Нет данных.")
        return

    level_s = st.radio("Группировать по", ["Группа", "Категория"], horizontal=True, key="seas_lvl")
    metric_s = st.radio("Метрика", ["Сумма", "Количество"], horizontal=True, key="seas_m")

    d = df.copy()
    d["Month"] = d["Дата"].dt.month
    pv = d.pivot_table(index=level_s, columns="Month", values=metric_s, aggfunc="sum", fill_value=0)
    if pv.empty:
        st.info("Нет данных.")
        return

    col_sums = pv.sum(axis=0).replace(0, 1)
    pv_norm = pv.div(col_sums, axis=1)
    pv_norm = pv_norm.loc[pv_norm.sum(axis=1).sort_values(ascending=False).index]
    pv = pv.loc[pv_norm.index]

    mo_short = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн", "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
    pv_disp = pv_norm.copy()
    pv_disp.columns = [mo_short[c - 1] for c in pv_disp.columns]

    st.markdown("**Матрица (доля в месячной выручке)**")
    st.plotly_chart(
        charts.heatmap(pv_disp, colorscale="YlGnBu", text_fmt="{:.0%}", text_min=0.05,
                       hover_fmt=".1%"),
        width="stretch",
    )

    st.markdown("**Абсолютные значения**")
    pv_abs = pv.copy()
    pv_abs.columns = [mo_short[c - 1] for c in pv_abs.columns]
    if metric_s == "Сумма":
        st.dataframe(pv_abs.apply(lambda s: s.apply(money)), width="stretch")
    else:
        st.dataframe(pv_abs.round(0).astype(int), width="stretch")

    dl_btn("Скачать матрицу сезонности",
           [("Сезонность (доли)", pv_norm.reset_index(), f"Доли по месяцам — {metric_s}"),
            ("Сезонность (abs)", pv.reset_index(), f"Абсолютные — {metric_s}")],
           filename=f"seasonality_{metric_s.lower()}.xlsx", key="dl_seas")
