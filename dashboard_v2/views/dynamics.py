"""Динамика и выгрузка: тренд с сравнением периодов + Excel-выгрузка по периодам."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st

from core import charts
from core.config import CHECKS_COL
from core.context import AppContext
from core.events import lfl_caption
from core.excel import dl_btn, dl_btn_plain
from core.helpers import clean_checks, daily_series, money, num, pct
from core.periods import compare_kpis, prev_period
from core.ui import own_period_note


def render(ctx: AppContext) -> None:
    st.subheader("📈 Динамика и выгрузка")
    tab_trend, tab_export = st.tabs(["📈 Тренд и сравнение", "📤 Выгрузка по периодам"])
    with tab_trend:
        _trend_tab(ctx)
    with tab_export:
        _export_tab(ctx)


# ---------------------------------------------------------------------------
# Тренд и сравнение (глобальный период)
# ---------------------------------------------------------------------------
def _trend_tab(ctx: AppContext) -> None:
    if ctx.df_f.empty:
        st.info("Нет данных.")
        return

    metric_col = ctx.metric_col
    cur = (ctx.d_from, ctx.d_to)
    lfl_on = st.toggle("LFL — только сопоставимые филиалы", value=True, key="dyn_lfl")

    refs = {
        "Предыдущий": prev_period(*cur),
        "Неделю назад (−7 дн)": (ctx.d_from - timedelta(days=7), ctx.d_to - timedelta(days=7)),
        "4 недели назад (−28 дн)": (ctx.d_from - timedelta(days=28), ctx.d_to - timedelta(days=28)),
        "Год назад (−364 дн)": (ctx.d_from - timedelta(days=364), ctx.d_to - timedelta(days=364)),
    }

    st.markdown("#### Сводка сравнения (Δ% — по среднему/день)")
    comp_rows = []
    excluded_all: dict = {}
    cmp_cache = {}
    for label, ref in refs.items():
        cmp = compare_kpis(ctx.df_universe, cur, ref, ctx.ap["branches"], lfl_on)
        cmp_cache[label] = cmp
        excluded_all.update(cmp.lfl_excluded)
        comp_rows.append({
            "Период": label,
            "Даты": f"{ref[0]:%d.%m.%Y} — {ref[1]:%d.%m.%Y}",
            "Сумма": cmp.ref["Выручка"],
            "Сумма/день": cmp.ref_per_day["Выручка"],
            "Δ % (сумма)": cmp.delta_pct.get("Выручка"),
            "Количество": cmp.ref["Количество"],
            "Δ % (кол)": cmp.delta_pct.get("Количество"),
        })
    cdf = pd.DataFrame(comp_rows)
    disp = cdf.copy()
    disp["Сумма"] = disp["Сумма"].apply(money)
    disp["Сумма/день"] = disp["Сумма/день"].apply(money)
    disp["Количество"] = disp["Количество"].apply(lambda v: num(v))
    disp["Δ % (сумма)"] = cdf["Δ % (сумма)"].apply(pct)
    disp["Δ % (кол)"] = cdf["Δ % (кол)"].apply(pct)
    st.dataframe(disp, width="stretch", hide_index=True)
    if lfl_on and excluded_all:
        st.caption("⚖️ " + lfl_caption(excluded_all))

    st.divider()

    # ---- График с наложением линий сравнения ----
    freq = "D" if ctx.days_cnt <= 62 else ("W-MON" if ctx.days_cnt <= 370 else "MS")
    which = st.multiselect(
        "Линии сравнения",
        list(refs.keys()),
        default=["Предыдущий", "Год назад (−364 дн)"],
        key="dyn_lines",
    )
    any_cmp = cmp_cache[list(refs)[0]]
    br_set = any_cmp.lfl_included if lfl_on else list(ctx.ap["branches"])
    base = ctx.df_universe[ctx.df_universe["Филиал"].isin(br_set)]

    def _series(p):
        f = base[(base["Дата"] >= pd.Timestamp(p[0])) & (base["Дата"] <= pd.Timestamp(p[1]))]
        if f.empty:
            return pd.Series(dtype=float)
        return f.set_index("Дата")[metric_col].resample(freq).sum()

    cur_s = _series(cur)
    overlay = {}
    for label in which:
        ref = refs[label]
        s = _series(ref)
        if s.empty:
            continue
        s.index = s.index + (pd.Timestamp(cur[0]) - pd.Timestamp(ref[0]))
        overlay[label] = s
    if not cur_s.empty:
        st.plotly_chart(
            charts.compare_ts(cur_s, overlay,
                              cur_label=f"Текущий ({ctx.d_from:%d.%m} — {ctx.d_to:%d.%m})",
                              y_title=metric_col),
            width="stretch",
        )

    # ---- Топ-10 дней ----
    st.markdown("**Топ-10 лучших дней периода**")
    df_daily = daily_series(ctx.df_f, metric_col)
    top10 = df_daily.sort_values("Value", ascending=False).head(10).copy()
    top10["День"] = pd.to_datetime(top10["Day"]).dt.strftime("%A")
    top10["Day"] = pd.to_datetime(top10["Day"]).dt.strftime("%d.%m.%Y")
    top10 = top10[["Day", "День", "Value"]].rename(columns={"Day": "Дата", "Value": metric_col})
    top10[metric_col] = top10[metric_col].apply(money if metric_col == "Сумма" else (lambda x: num(x)))
    st.dataframe(top10, width="stretch", hide_index=True)

    dl_btn("Скачать тренд + сравнение",
           [("Сравнение периодов", cdf, "Сравнение (Δ% по /день)"),
            ("Топ-10 дней", df_daily.sort_values("Value", ascending=False).head(10), "Пики периода")],
           filename=f"trend_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_trend")


# ---------------------------------------------------------------------------
# Выгрузка по периодам (свой период)
# ---------------------------------------------------------------------------
def _export_tab(ctx: AppContext) -> None:
    own_period_note()

    cc1, cc2, cc3 = st.columns([2, 1, 1])
    with cc1:
        kf, kt = "dyn_from", "dyn_to"
        if kf not in st.session_state:
            st.session_state[kf] = ctx.d_from
        if kt not in st.session_state:
            st.session_state[kt] = ctx.d_to
        dc1, dc2 = st.columns(2)
        with dc1:
            dyn_from = pd.Timestamp(st.date_input("Период — с", key=kf))
        with dc2:
            dyn_to = pd.Timestamp(st.date_input("Период — по", key=kt))
        if dyn_from > dyn_to:
            dyn_from, dyn_to = dyn_to, dyn_from
    with cc2:
        gran = st.selectbox("Разбивка", ["Неделя", "Месяц", "Год"], index=1, key="dyn_gran")
    with cc3:
        dim = st.selectbox("Измерение", ["Нет (вся сеть)", "Филиал", "Группа", "Категория"],
                           key="dyn_dim")
    dim_col = None if dim.startswith("Нет") else dim

    if st.button("↩️ Сбросить период", key="dyn_reset"):
        st.session_state[kf] = ctx.d_from
        st.session_state[kt] = ctx.d_to
        st.rerun()

    df_dyn = ctx.df_universe[(ctx.df_universe["Дата"] >= dyn_from) &
                             (ctx.df_universe["Дата"] <= dyn_to)].copy()
    st.caption(f"📅 {dyn_from:%d.%m.%Y} – {dyn_to:%d.%m.%Y}  ·  {len(df_dyn):,} строк")

    if df_dyn.empty:
        st.info("Нет данных по выбранным фильтрам и периоду.")
        return

    per_freq = {"Неделя": "W", "Месяц": "M", "Год": "Y"}[gran]
    df_dyn["_period"] = df_dyn["Дата"].dt.to_period(per_freq).dt.start_time
    df_dyn["_check"] = clean_checks(df_dyn[CHECKS_COL])

    gcols = ["_period"] + ([dim_col] if dim_col else [])
    agg = (df_dyn.groupby(gcols, dropna=False)
           .agg(Выручка=("Сумма", "sum"), Количество=("Количество", "sum"))
           .reset_index())
    chk = (df_dyn.dropna(subset=["_check"])
           .groupby(gcols)["_check"].nunique().reset_index(name="Чеков"))
    agg = agg.merge(chk, on=gcols, how="left")
    agg["Чеков"] = agg["Чеков"].fillna(0).astype(int)
    agg["Средний чек"] = np.where(agg["Чеков"] > 0, agg["Выручка"] / agg["Чеков"], 0.0)

    agg = agg.sort_values(gcols).reset_index(drop=True)
    if dim_col:
        agg["Δ % (выручка)"] = (agg.groupby(dim_col)["Выручка"].pct_change() * 100).round(1)
    else:
        agg["Δ % (выручка)"] = (agg["Выручка"].pct_change() * 100).round(1)

    def _per_label(ts):
        ts = pd.Timestamp(ts)
        if gran == "Год":
            return f"{ts.year}"
        if gran == "Месяц":
            return f"{ts.year}-{ts.month:02d}"
        return ts.strftime("%d.%m.%Y")  # начало недели (пн)

    agg.insert(0, "Период", agg["_period"].map(_per_label))

    # ---- график ----
    plot_df = agg.rename(columns={"_period": "Дата"})
    if dim_col:
        totals = agg.groupby(dim_col)["Выручка"].sum().sort_values(ascending=False)
        top = list(totals.head(8).index)
        st.plotly_chart(
            charts.line_ts(plot_df[plot_df[dim_col].isin(top)], "Дата", "Выручка",
                           color=dim_col, y_title="Выручка, сом"),
            width="stretch",
        )
        if len(totals) > 8:
            st.caption(f"На графике топ-8 из {len(totals)} «{dim_col}» по выручке "
                       f"(в таблице и Excel — все).")
    else:
        st.plotly_chart(
            charts.line_ts(plot_df, "Дата", "Выручка", area=True, y_title="Выручка, сом"),
            width="stretch",
        )

    # ---- таблица ----
    out_cols = (["Период"] + ([dim_col] if dim_col else [])
                + ["Выручка", "Количество", "Чеков", "Средний чек", "Δ % (выручка)"])
    disp = agg[out_cols].copy()
    disp["Выручка"] = disp["Выручка"].apply(money)
    disp["Количество"] = disp["Количество"].apply(lambda v: num(v))
    disp["Чеков"] = disp["Чеков"].apply(lambda v: num(v))
    disp["Средний чек"] = disp["Средний чек"].apply(money)
    disp["Δ % (выручка)"] = disp["Δ % (выручка)"].apply(
        lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
    st.dataframe(disp, width="stretch", hide_index=True)

    # ---- Excel ----
    xls_main = agg[out_cols].copy()
    xls_main["Период"] = agg["_period"]  # дата для Excel
    sheets = [("Динамика", xls_main)]
    if dim_col:
        pivot = (agg.pivot_table(index="_period", columns=dim_col,
                                 values="Выручка", aggfunc="sum")
                 .reset_index().rename(columns={"_period": "Период"}))
        sheets.append((f"Выручка × {dim_col}", pivot))
    fn = f"dynamics_{gran.lower()}_{dyn_from:%Y%m%d}_{dyn_to:%Y%m%d}.xlsx"
    dl_btn_plain("Скачать Excel за период", sheets, filename=fn, key="dl_dyn")
