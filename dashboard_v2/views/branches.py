"""Филиалы и время: композитный рейтинг точек + пики по часам."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import charts
from core.context import AppContext
from core.excel import dl_btn
from core.helpers import add_time_cols, kpi_group, money
from core.config import COLORS


def render(ctx: AppContext) -> None:
    st.subheader("🏢 Филиалы и время")
    tab_rank, tab_hours = st.tabs(["🏆 Рейтинг точек", "⏰ Пики времени"])
    with tab_rank:
        _ranking_tab(ctx)
    with tab_hours:
        _hours_tab(ctx)


def _ranking_tab(ctx: AppContext) -> None:
    st.caption("Композитный скор: нормированная выручка (50%) + средний чек (30%) + позиции/чек (20%).")
    if ctx.df_f.empty:
        st.info("Нет данных.")
        return

    level = st.radio("Уровень", ["Филиалы", "Точки (внутри филиалов)"], horizontal=True, key="rk_lvl")
    group_cols = ["Филиал"] if level == "Филиалы" else ["Филиал", "Точки"]
    base_kpi = kpi_group(ctx.df_f, group_cols)

    if base_kpi.empty:
        st.info("Нет данных.")
        return

    def _normalize(s: pd.Series) -> pd.Series:
        mn, mx = s.min(), s.max()
        return (s - mn) / (mx - mn) if mx > mn else pd.Series([0.5] * len(s), index=s.index)

    base_kpi["n_выручка"] = _normalize(base_kpi["Выручка"])
    base_kpi["n_ср_чек"] = _normalize(base_kpi["Средний чек"])
    base_kpi["n_позиций"] = _normalize(base_kpi["Позиции/чек"])
    base_kpi["Скор"] = (base_kpi["n_выручка"] * 0.5 +
                        base_kpi["n_ср_чек"] * 0.3 +
                        base_kpi["n_позиций"] * 0.2)
    base_kpi = base_kpi.sort_values("Скор", ascending=False).reset_index(drop=True)
    base_kpi["Ранг"] = base_kpi.index + 1

    show_cols = (["Ранг"] + group_cols +
                 ["Выручка", "Чеков", "Средний чек", "Позиции/чек", "Товаров/чек", "Доля выручки", "Скор"])
    disp = base_kpi[show_cols].copy()
    disp["Выручка"] = disp["Выручка"].round(0)
    disp["Средний чек"] = disp["Средний чек"].round(0)
    disp["Позиции/чек"] = disp["Позиции/чек"].round(2)
    disp["Товаров/чек"] = disp["Товаров/чек"].round(2)
    disp["Доля выручки"] = (disp["Доля выручки"] * 100).round(1).astype(str) + "%"
    disp["Скор"] = disp["Скор"].round(3)
    st.dataframe(disp, width="stretch", hide_index=True, height=520)

    st.markdown("**Скор — топ 10**")
    top10 = base_kpi.head(10).copy()
    if level == "Филиалы":
        top10["_label"] = top10["Филиал"]
    else:
        top10["_label"] = top10["Филиал"] + " — " + top10["Точки"].astype(str)
    fig = charts.barh_top(top10, "_label", "Скор", n=10)
    fig.update_xaxes(range=[0, 1], title="Скор (0–1)")
    st.plotly_chart(fig, width="stretch")

    dl_btn("Скачать рейтинг",
           [("Рейтинг", base_kpi.drop(columns=["n_выручка", "n_ср_чек", "n_позиций", "_label"],
                                      errors="ignore"), "Композитный рейтинг")],
           filename=f"rating_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_rating")


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
    dow_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    pv.index = dow_names
    pv.columns = [f"{int(h):02d}" for h in pv.columns]
    st.plotly_chart(charts.heatmap(pv, colorscale="YlOrRd", height=320),
                    width="stretch")

    st.divider()
    c1, c2 = st.columns([1, 2])
    by_bh = (df_time.groupby(["Филиал", "Hour"], dropna=False)[metric_col]
             .sum().reset_index().rename(columns={metric_col: "Value"}))
    peak = (by_bh.sort_values(["Филиал", "Value"], ascending=[True, False])
            .groupby("Филиал", as_index=False).head(1)
            .rename(columns={"Hour": "PeakHour", "Value": "PeakValue"}))
    pv2 = by_bh.pivot_table(index="Филиал", columns="Hour", values="Value", fill_value=0).sort_index(axis=1)
    with c1:
        st.markdown("**Пиковый час / филиал**")
        pv_disp = peak.copy()
        pv_disp["PeakHour"] = pv_disp["PeakHour"].apply(lambda h: f"{int(h):02d}:00")
        st.dataframe(pv_disp, width="stretch", hide_index=True)
    with c2:
        st.markdown("**Филиалы × часы**")
        st.dataframe(pv2, width="stretch")

    sel = st.selectbox("График по филиалу", sorted(by_bh["Филиал"].unique()), key="hr_branch")
    d_bh = by_bh[by_bh["Филиал"] == sel].sort_values("Hour")
    st.plotly_chart(
        charts.line_ts(d_bh, "Hour", "Value", area=True, y_title=metric_col),
        width="stretch",
    )

    dl_btn("Скачать часы",
           [("Пиковые часы", peak, "Пик по филиалу"),
            ("Филиалы × часы", pv2.reset_index(), f"Матрица часов — {metric_col}"),
            ("По часам детально", by_bh, "Часы × филиалы")],
           filename=f"hours_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_hours")
