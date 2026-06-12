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
    tab_br, tab_pts, tab_prod, tab_hours = st.tabs(
        ["🏆 Филиалы", "📍 Точки по филиалам", "🔎 Товар по филиалам", "⏰ Пики времени"])
    with tab_br:
        _branches_tab(ctx)
    with tab_pts:
        _points_tab(ctx)
    with tab_prod:
        _product_by_branch_tab(ctx)
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
# Товар по филиалам: продажи выбранной номенклатуры/категории в разрезе филиалов
# ---------------------------------------------------------------------------
def _product_by_branch_tab(ctx: AppContext) -> None:
    st.caption("Каскад Группа → Категория → Подкатегория: матрица показывает ВСЮ номенклатуру "
               f"выбранного за глобальный период ({ctx.d_from:%d.%m.%Y} – {ctx.d_to:%d.%m.%Y}). "
               "Конкретные SKU выбирать не обязательно.")
    df_f = ctx.df_f
    if df_f.empty:
        st.info("Нет данных.")
        return

    filters: dict[str, str] = {}
    pool = df_f
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        opts = ["— все —"] + sorted(pool["Группа"].dropna().astype(str).unique().tolist())
        sel_g = st.selectbox("Группа", opts, key="nb_g")
    if sel_g != "— все —":
        pool = pool[pool["Группа"] == sel_g]
        filters["Группа"] = sel_g
    with fc2:
        opts = ["— все —"] + sorted(pool["Категория"].dropna().astype(str).unique().tolist())
        sel_c = st.selectbox("Категория", opts, key="nb_c")
    if sel_c != "— все —":
        pool = pool[pool["Категория"] == sel_c]
        filters["Категория"] = sel_c
    with fc3:
        opts = ["— все —"] + sorted(pool["Подкатегория"].dropna().astype(str).unique().tolist())
        sel_s = st.selectbox("Подкатегория", opts, key="nb_s")
    if sel_s != "— все —":
        pool = pool[pool["Подкатегория"] == sel_s]
        filters["Подкатегория"] = sel_s

    sku_order = (pool.groupby("Номенклатура")["Сумма"].sum()
                 .sort_values(ascending=False).index.astype(str).tolist())
    sel_skus = st.multiselect(
        f"Номенклатура — опционально (пусто = все {len(sku_order)} SKU выбранного)",
        sku_order, key="nb_sku", placeholder="пусто — вся номенклатура выбранного")

    part = pool[pool["Номенклатура"].astype(str).isin(sel_skus)] if sel_skus else pool
    if part.empty:
        st.info("По выбору нет продаж за период.")
        return
    if not filters and not sel_skus:
        st.info(f"ℹ️ Фильтры не выбраны — показываю все {len(sku_order)} SKU выборки. "
                "Выбери группу/категорию, чтобы сузить.")

    label = " / ".join(filters.values()) if filters else "вся выборка"
    if sel_skus:
        label += f" · {len(sel_skus)} SKU"

    # ---- KPI выбора ----
    rev = float(part["Сумма"].sum())
    qty = float(part["Количество"].sum())
    total_rev = float(df_f["Сумма"].sum())
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Выручка", money(rev))
    k2.metric("Доля от выборки", f"{rev / total_rev * 100:.1f}%" if total_rev else "—")
    k3.metric("Количество", num(qty))
    k4.metric("Выручка / день", money(rev / ctx.days_cnt))
    k5.metric("Ср. цена", money(rev / qty) if qty else "—")

    branches_sel = [b for b in sorted(ctx.ap["branches"])]

    # ---- Матрица Номенклатура × Филиал ----
    def _matrix(value_col: str) -> pd.DataFrame:
        pv = part.pivot_table(index="Номенклатура", columns="Филиал",
                              values=value_col, aggfunc="sum", fill_value=0)
        pv = pv.reindex(columns=branches_sel, fill_value=0)
        pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index]
        pv["Итого"] = pv.sum(axis=1)
        pv.loc["Итого"] = pv.sum()
        return pv.round(0).astype("int64")

    mx_qty = _matrix("Количество")
    mx_rev = _matrix("Сумма")

    st.markdown("**Матрица: Номенклатура × Филиал**")
    mx_metric = st.radio("Метрика", ["Кол-во (шт)", "Выручка (сом)"],
                         horizontal=True, key="nb_mx", label_visibility="collapsed")
    mx = mx_qty if mx_metric == "Кол-во (шт)" else mx_rev
    st.dataframe(mx, width="stretch",
                 height=min(38 * (len(mx) + 1) + 40, 560))
    zero_br = [b for b in branches_sel if mx_qty.loc["Итого", b] == 0]
    if zero_br:
        st.caption(f"⚪ Нет продаж выбранного: {', '.join(zero_br)}")

    # ---- Сводка по филиалам ----
    st.markdown("**Сводка по филиалам**")
    cur = (ctx.d_from, ctx.d_to)
    prev = prev_period(*cur)
    part_prev = _slice(ctx.df_universe, prev)
    for col, v in filters.items():
        part_prev = part_prev[part_prev[col] == v]
    if sel_skus:
        part_prev = part_prev[part_prev["Номенклатура"].astype(str).isin(sel_skus)]
    prev_rev = part_prev.groupby("Филиал")["Сумма"].sum()
    _, exc_prev = lfl_split(ctx.ap["branches"], cur, prev)

    g = (part.groupby("Филиал")
         .agg(SKU=("Номенклатура", "nunique"), Шт=("Количество", "sum"),
              Выручка=("Сумма", "sum"), Первая=("Дата", "min"), Последняя=("Дата", "max"))
         .sort_values("Выручка", ascending=False).reset_index())
    g["Доля выручки"] = g["Выручка"] / (g["Выручка"].sum() or 1)
    g["Ср. цена"] = g["Выручка"] / g["Шт"].replace(0, pd.NA)
    disp = pd.DataFrame({
        "Филиал": g["Филиал"],
        "SKU": g["SKU"],
        "Шт": g["Шт"].apply(lambda v: num(v)),
        "Выручка": g["Выручка"].apply(money),
        "Доля": (g["Доля выручки"] * 100).round(1).astype(str) + "%",
        "Ср. цена": g["Ср. цена"].apply(money),
        "Δ% vs пред.": [(f"⚠ {exc_prev[b]}" if b in exc_prev
                         else pct((v - float(prev_rev.get(b, 0))) / float(prev_rev.get(b, 0)) * 100
                                  if float(prev_rev.get(b, 0)) else None))
                        for b, v in zip(g["Филиал"], g["Выручка"])],
        "Первая": g["Первая"].dt.strftime("%d.%m.%Y"),
        "Последняя": g["Последняя"].dt.strftime("%d.%m.%Y"),
    })
    st.dataframe(disp, width="stretch", hide_index=True)
    st.caption(f"Δ% — vs {prev[0]:%d.%m}–{prev[1]:%d.%m.%Y} (равная длина). "
               f"⚠ — филиал несопоставим (открытие/закрытие).")

    # ---- Динамика по SKU ----
    st.markdown("**Динамика по номенклатуре** (топ-8 по выручке)")
    freq = "D" if ctx.days_cnt <= 35 else ("W-MON" if ctx.days_cnt <= 370 else "MS")
    dyn_metric = "Количество" if mx_metric == "Кол-во (шт)" else "Сумма"
    top_skus = [s for s in mx_qty.index if s != "Итого"][:8]
    ts = (part[part["Номенклатура"].isin(top_skus)]
          .groupby([pd.Grouper(key="Дата", freq=freq), "Номенклатура"])[dyn_metric]
          .sum().reset_index())
    ts["Номенклатура"] = pd.Categorical(ts["Номенклатура"], categories=top_skus, ordered=True)
    ts = ts.sort_values(["Номенклатура", "Дата"])
    st.plotly_chart(
        charts.line_ts(ts, "Дата", dyn_metric, color="Номенклатура",
                       y_title="шт" if dyn_metric == "Количество" else "Выручка, сом"),
        width="stretch",
    )

    # ---- Excel (структура как в reports/*_по_филиалам.xlsx) ----
    daily = part.pivot_table(index="Дата", columns="Номенклатура",
                             values="Количество", aggfunc="sum", fill_value=0).sort_index()
    daily["Итого шт"] = daily.sum(axis=1)
    daily = daily.reset_index()
    daily["Дата"] = pd.to_datetime(daily["Дата"]).dt.strftime("%d.%m.%Y")

    title = f"{label} · {ctx.d_from:%d.%m.%Y} – {ctx.d_to:%d.%m.%Y}"
    g_x = g.copy()
    g_x["Первая"] = g_x["Первая"].dt.strftime("%d.%m.%Y")
    g_x["Последняя"] = g_x["Последняя"].dt.strftime("%d.%m.%Y")
    dl_btn("Скачать отчёт по филиалам",
           [("Сводка по филиалам", g_x, title),
            ("Кол-во (шт)", mx_qty.reset_index(), f"{title} — продано штук"),
            ("Выручка (сом)", mx_rev.reset_index(), f"{title} — выручка"),
            ("По дням (шт)", daily, f"{title} — штук по дням")],
           filename=f"product_by_branch_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx",
           key="dl_nb")


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
