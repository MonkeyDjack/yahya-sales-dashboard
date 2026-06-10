"""Филиалы и время: динамика филиалов, точки по филиалам, пики по часам."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from core import charts
from core.context import AppContext
from core.events import lfl_split
from core.excel import dl_btn
from core.helpers import add_time_cols, kpi_group, money, num, pct, safe_div
from core.periods import prev_period, yoy_period


def render(ctx: AppContext) -> None:
    st.subheader("🏢 Филиалы и время")
    tab_br, tab_pts, tab_hours = st.tabs(
        ["🏆 Филиалы", "📍 Точки по филиалам", "⏰ Пики времени"])
    with tab_br:
        _branches_tab(ctx)
    with tab_pts:
        _points_tab(ctx)
    with tab_hours:
        _hours_tab(ctx)


def _slice(df: pd.DataFrame, p) -> pd.DataFrame:
    return df[(df["Дата"] >= pd.Timestamp(p[0])) & (df["Дата"] <= pd.Timestamp(p[1]))]


# ---------------------------------------------------------------------------
# Филиалы: рейтинг + динамика в одной таблице
# ---------------------------------------------------------------------------
def _branches_tab(ctx: AppContext) -> None:
    if ctx.df_f.empty:
        st.info("Нет данных.")
        return

    cur = (ctx.d_from, ctx.d_to)
    prev = prev_period(*cur)
    yoy = yoy_period(*cur)

    kpi = kpi_group(ctx.df_f, ["Филиал"])
    if kpi.empty:
        st.info("Нет данных.")
        return

    # Δ% vs пред. период / год назад (периоды равной длины → сравниваем тоталы)
    b_prev = _slice(ctx.df_universe, prev).groupby("Филиал")["Сумма"].sum()
    b_yoy = _slice(ctx.df_universe, yoy).groupby("Филиал")["Сумма"].sum()
    _, exc_prev = lfl_split(ctx.ap["branches"], cur, prev)
    _, exc_yoy = lfl_split(ctx.ap["branches"], cur, yoy)

    def _normalize(s: pd.Series) -> pd.Series:
        mn, mx = s.min(), s.max()
        return (s - mn) / (mx - mn) if mx > mn else pd.Series([0.5] * len(s), index=s.index)

    kpi["Скор"] = (_normalize(kpi["Выручка"]) * 0.5 +
                   _normalize(kpi["Средний чек"]) * 0.3 +
                   _normalize(kpi["Позиции/чек"]) * 0.2)
    kpi = kpi.sort_values("Выручка", ascending=False).reset_index(drop=True)

    def _delta(br, cur_v, ref_map, exc):
        if br in exc:
            return f"⚠ {exc[br]}"
        ref_v = float(ref_map.get(br, 0))
        return pct((cur_v - ref_v) / ref_v * 100 if ref_v else None)

    disp = pd.DataFrame({
        "Филиал": kpi["Филиал"],
        "Выручка": kpi["Выручка"].apply(money),
        "Доля": (kpi["Доля выручки"] * 100).round(1).astype(str) + "%",
        "⌀/день": (kpi["Выручка"] / ctx.days_cnt).apply(money),
        "Δ% vs пред.": [_delta(b, v, b_prev, exc_prev)
                        for b, v in zip(kpi["Филиал"], kpi["Выручка"])],
        "Δ% YoY": [_delta(b, v, b_yoy, exc_yoy)
                   for b, v in zip(kpi["Филиал"], kpi["Выручка"])],
        "Чеков": kpi["Чеков"].apply(lambda v: num(v)),
        "Ср. чек": kpi["Средний чек"].apply(money),
        "Позиции/чек": kpi["Позиции/чек"].round(2),
        "Скор": kpi["Скор"].round(3),
    })
    st.dataframe(disp, width="stretch", hide_index=True)
    st.caption(
        f"Δ% — к тоталам равных периодов: пред. {prev[0]:%d.%m}–{prev[1]:%d.%m.%Y}, "
        f"год назад {yoy[0]:%d.%m}–{yoy[1]:%d.%m.%Y} (−364 дн). "
        f"⚠ — филиал несопоставим (открытие/закрытие). "
        f"Скор: выручка 50% + ср. чек 30% + позиции/чек 20%."
    )

    # ---- Динамика по филиалам ----
    st.markdown("**Динамика выручки по филиалам**")
    freq = "D" if ctx.days_cnt <= 35 else ("W-MON" if ctx.days_cnt <= 370 else "MS")
    ts = (ctx.df_f.groupby([pd.Grouper(key="Дата", freq=freq), "Филиал"])["Сумма"]
          .sum().reset_index())
    order = kpi["Филиал"].tolist()
    ts["Филиал"] = pd.Categorical(ts["Филиал"], categories=order, ordered=True)
    ts = ts.sort_values(["Филиал", "Дата"])
    st.plotly_chart(
        charts.line_ts(ts, "Дата", "Сумма", color="Филиал", y_title="Выручка"),
        width="stretch",
    )
    if freq != "D":
        st.caption("Разбивка по неделям (период длиннее 35 дней) — крайние точки могут быть неполными неделями.")

    dl_btn("Скачать филиалы",
           [("Филиалы", kpi, "KPI по филиалам"),
            ("Динамика", ts.rename(columns={"Сумма": "Выручка"}), "Выручка по периодам")],
           filename=f"branches_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_br")


# ---------------------------------------------------------------------------
# Точки по филиалам (Магазин / Кухня / Бар)
# ---------------------------------------------------------------------------
def _points_tab(ctx: AppContext) -> None:
    if ctx.df_f.empty:
        st.info("Нет данных.")
        return

    cur = (ctx.d_from, ctx.d_to)
    prev = prev_period(*cur)

    kpi_pt = kpi_group(ctx.df_f, ["Филиал", "Точки"])
    if kpi_pt.empty:
        st.info("Нет данных.")
        return

    branch_order = (kpi_pt.groupby("Филиал")["Выручка"].sum()
                    .sort_values(ascending=False).index.tolist())

    # ---- Структура: stacked bar ----
    chart_df = kpi_pt.copy()
    chart_df["Филиал"] = pd.Categorical(chart_df["Филиал"], categories=branch_order, ordered=True)
    chart_df = chart_df.sort_values(["Точки", "Филиал"])
    st.plotly_chart(
        charts.stacked_bar(chart_df, "Филиал", "Выручка", "Точки",
                           title="Выручка филиалов в разрезе точек", y_title="Выручка"),
        width="stretch",
    )

    # ---- Матрица Филиал × Точки: выручка и доля внутри филиала ----
    st.markdown("**Матрица: выручка точки и её доля внутри филиала**")
    pv = kpi_pt.pivot_table(index="Филиал", columns="Точки", values="Выручка",
                            aggfunc="sum", fill_value=0).reindex(branch_order)
    pv_share = pv.div(pv.sum(axis=1).replace(0, 1), axis=0)
    pv_disp = pd.DataFrame(index=pv.index)
    for c in pv.columns:
        pv_disp[c] = [f"{money(v)} · {s*100:.0f}%" for v, s in zip(pv[c], pv_share[c])]
    pv_disp["Итого"] = pv.sum(axis=1).apply(money)
    st.dataframe(pv_disp, width="stretch")

    # ---- Детальная таблица, сгруппированная по филиалам ----
    st.markdown("**Детально по точкам** (сгруппировано по филиалам)")
    prev_pt = (_slice(ctx.df_universe, prev)
               .groupby(["Филиал", "Точки"])["Сумма"].sum())
    det = kpi_pt.copy()
    det["Филиал"] = pd.Categorical(det["Филиал"], categories=branch_order, ordered=True)
    det = det.sort_values(["Филиал", "Выручка"], ascending=[True, False]).reset_index(drop=True)
    br_total = det.groupby("Филиал", observed=True)["Выручка"].transform("sum")
    det["Доля в филиале"] = np.where(br_total > 0, det["Выручка"] / br_total, 0)
    prev_vals = [float(prev_pt.get((b, p), 0)) for b, p in zip(det["Филиал"], det["Точки"])]
    det["Δ% vs пред."] = [(c - pv_) / pv_ * 100 if pv_ else None
                          for c, pv_ in zip(det["Выручка"], prev_vals)]

    disp = pd.DataFrame({
        "Филиал": det["Филиал"].astype(str),
        "Точки": det["Точки"],
        "Выручка": det["Выручка"].apply(money),
        "Доля в филиале": (det["Доля в филиале"] * 100).round(1).astype(str) + "%",
        "⌀/день": (det["Выручка"] / ctx.days_cnt).apply(money),
        "Δ% vs пред.": det["Δ% vs пред."].apply(pct),
        "Чеков": det["Чеков"].apply(lambda v: num(v)),
        "Ср. чек": det["Средний чек"].apply(money),
        "Позиции/чек": det["Позиции/чек"].round(2),
    })
    # повторяющееся имя филиала показываем только в первой строке группы
    disp["Филиал"] = disp["Филиал"].mask(disp["Филиал"].eq(disp["Филиал"].shift()), "")
    st.dataframe(disp, width="stretch", hide_index=True,
                 height=min(38 * len(disp) + 40, 640))
    st.caption(f"Δ% vs пред. период ({prev[0]:%d.%m}–{prev[1]:%d.%m.%Y}, равная длина).")

    exp = det.copy()
    exp["Филиал"] = exp["Филиал"].astype(str)
    dl_btn("Скачать точки",
           [("Точки по филиалам", exp, "Точки в разрезе филиалов")],
           filename=f"points_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_pts")


# ---------------------------------------------------------------------------
# Пики времени
# ---------------------------------------------------------------------------
def _hours_tab(ctx: AppContext) -> None:
    metric_col = ctx.metric_col
    df_time = add_time_cols(ctx.df_f)
    if df_time.empty:
        st.info("Нет данных в колонке «Время».")
        return

    st.markdown(f"**Heatmap: день недели × час — {metric_col}**")
    hm = df_time.groupby(["DOW", "Hour"])[metric_col].sum().reset_index()
    pv = hm.pivot(index="DOW", columns="Hour", values=metric_col).fillna(0)
    pv = pv.reindex(range(7)).fillna(0)
    pv.index = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    pv.columns = [f"{int(h):02d}" for h in pv.columns]
    st.plotly_chart(charts.heatmap(pv, colorscale="YlOrRd", height=320),
                    width="stretch")

    st.divider()

    by_bh = (df_time.groupby(["Филиал", "Hour"], dropna=False)[metric_col]
             .sum().reset_index().rename(columns={metric_col: "Value"}))

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Пиковый час / филиал**")
        totals = by_bh.groupby("Филиал")["Value"].sum()
        peak = (by_bh.sort_values(["Филиал", "Value"], ascending=[True, False])
                .groupby("Филиал", as_index=False).head(1)
                .rename(columns={"Hour": "PeakHour", "Value": "PeakValue"}))
        peak["Доля дня"] = [safe_div(v, float(totals.get(b, 0))) for b, v
                            in zip(peak["Филиал"], peak["PeakValue"])]
        pk = peak.copy()
        pk["PeakHour"] = pk["PeakHour"].apply(lambda h: f"{int(h):02d}:00")
        pk["PeakValue"] = pk["PeakValue"].apply(money)
        pk["Доля дня"] = (pk["Доля дня"] * 100).round(1).astype(str) + "%"
        st.dataframe(pk, width="stretch", hide_index=True)
    with c2:
        st.markdown("**Почасовые профили филиалов**")
        as_share = st.toggle("в % от дня филиала", value=True, key="hr_share",
                             help="Нормирует профиль каждого филиала на его дневной объём — "
                                  "сравниваются формы трафика, а не размеры филиалов.")
        prof = by_bh.copy()
        if as_share:
            prof["Value"] = prof.apply(
                lambda r: safe_div(r["Value"], float(totals.get(r["Филиал"], 0))) * 100, axis=1)
        sel_br = st.multiselect("Филиалы", sorted(by_bh["Филиал"].unique()),
                                default=sorted(by_bh["Филиал"].unique()), key="hr_brs")
        prof = prof[prof["Филиал"].isin(sel_br)].sort_values(["Филиал", "Hour"])
        if not prof.empty:
            fig = charts.line_ts(prof, "Hour", "Value", color="Филиал",
                                 y_title="% от дня" if as_share else metric_col)
            fig.update_xaxes(dtick=1, title="Час")
            st.plotly_chart(fig, width="stretch")

    pv2 = by_bh.pivot_table(index="Филиал", columns="Hour", values="Value",
                            fill_value=0).sort_index(axis=1)
    dl_btn("Скачать часы",
           [("Пиковые часы", peak, "Пик по филиалу"),
            ("Филиалы × часы", pv2.reset_index(), f"Матрица часов — {metric_col}"),
            ("По часам детально", by_bh, "Часы × филиалы")],
           filename=f"hours_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_hours")
