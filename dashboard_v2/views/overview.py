"""Обзор — лицо дашборда: KPI, честные сравнения (LFL, /день), инсайты."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from core import charts
from core.context import AppContext
from core.events import lfl_caption, lfl_split
from core.helpers import (count_checks, daily_series, detect_anomalies,
                          kpi_group, money, num, pct, safe_div)
from core.periods import compare_kpis, prev_period, yoy_period
from core.ui import insight_card


def _fmt_delta(v) -> str:
    return f"{v:+.1f}%" if v is not None and not pd.isna(v) else None


def render(ctx: AppContext) -> None:
    st.subheader("🏠 Обзор")
    if ctx.df_f.empty:
        st.info("Нет данных по выбранным фильтрам.")
        return

    cur = (ctx.d_from, ctx.d_to)
    prev = prev_period(*cur)
    yoy = yoy_period(*cur)

    lfl_on = st.toggle(
        "LFL — сравнивать только сопоставимые филиалы", value=True, key="ov_lfl",
        help="Исключает из сравнений филиалы, которые не работали полноценно в обоих "
             "периодах (новые точки, реконструкции). Иначе рост/падение искажается.",
    )

    cmp_prev = compare_kpis(ctx.df_universe, cur, prev, ctx.ap["branches"], lfl_on, ctx.cost_ref)
    cmp_yoy = compare_kpis(ctx.df_universe, cur, yoy, ctx.ap["branches"], lfl_on, ctx.cost_ref)

    # ---- KPI текущего периода (полные значения, Δ — per-day LFL vs пред. период) ----
    sales = float(ctx.df_f["Сумма"].sum())
    qty = float(ctx.df_f["Количество"].sum())
    checks = count_checks(ctx.df_f)
    has_margin = ctx.cost_ref is not None and not ctx.cost_ref.empty

    cols = st.columns(6 if has_margin else 5)
    cols[0].metric("Выручка", money(sales), _fmt_delta(cmp_prev.delta_pct.get("Выручка")))
    cols[1].metric("Выручка / день", money(safe_div(sales, ctx.days_cnt)))
    cols[2].metric("Чеков", num(checks), _fmt_delta(cmp_prev.delta_pct.get("Чеков")))
    cols[3].metric("Средний чек", money(safe_div(sales, checks)),
                   _fmt_delta(cmp_prev.delta_pct.get("Средний чек")))
    cols[4].metric("Количество", num(qty), _fmt_delta(cmp_prev.delta_pct.get("Количество")))
    if has_margin:
        cols[5].metric("Маржа", money(cmp_prev.cur.get("Маржа", float("nan"))),
                       _fmt_delta(cmp_prev.delta_pct.get("Маржа")),
                       help="Покрытие себесом ~84.5% выручки")
    st.caption(
        f"Δ — изменение **среднего/день** vs предыдущий период "
        f"({prev[0]:%d.%m.%Y} – {prev[1]:%d.%m.%Y})"
        + (", LFL" if lfl_on else ", все филиалы")
    )
    if lfl_on and (cmp_prev.lfl_excluded or cmp_yoy.lfl_excluded):
        merged = {**cmp_yoy.lfl_excluded, **cmp_prev.lfl_excluded}
        st.caption("⚖️ " + lfl_caption(merged))

    st.divider()

    # ---- Сравнительная таблица: текущий vs пред. период vs год назад ----
    st.markdown("#### ⚖️ Сравнение периодов (среднее/день)")
    rows = []
    for key, label, formatter in [("Выручка", "Выручка/день", money),
                                  ("Чеков", "Чеков/день", lambda v: num(v, 0)),
                                  ("Средний чек", "Средний чек", money),
                                  ("Количество", "Количество/день", lambda v: num(v, 0))]:
        rows.append({
            "Метрика": label,
            "Текущий": formatter(cmp_prev.cur_per_day.get(key, 0)),
            "Пред. период": formatter(cmp_prev.ref_per_day.get(key, 0)),
            "Δ%": pct(cmp_prev.delta_pct.get(key)),
            "Год назад": formatter(cmp_yoy.ref_per_day.get(key, 0)),
            "Δ% YoY": pct(cmp_yoy.delta_pct.get(key)),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(
        f"Пред. период: {prev[0]:%d.%m.%Y} – {prev[1]:%d.%m.%Y} · "
        f"Год назад: {yoy[0]:%d.%m.%Y} – {yoy[1]:%d.%m.%Y} "
        f"(сдвиг −364 дня — сохраняет день недели)"
    )

    # ---- График: текущий период + пунктиры пред. периода и года назад ----
    br_set = cmp_prev.lfl_included if lfl_on else list(ctx.ap["branches"])
    base = ctx.df_universe[ctx.df_universe["Филиал"].isin(br_set)]

    def _daily(p):
        f = base[(base["Дата"] >= pd.Timestamp(p[0])) & (base["Дата"] <= pd.Timestamp(p[1]))]
        if f.empty:
            return pd.Series(dtype=float)
        return f.set_index("Дата")["Сумма"].resample("D").sum()

    cur_s = _daily(cur)
    refs = {}
    prev_s = _daily(prev)
    if not prev_s.empty:
        prev_s.index = prev_s.index + pd.Timedelta(days=ctx.days_cnt)
        refs[f"Пред. период ({prev[0]:%d.%m}–{prev[1]:%d.%m})"] = prev_s
    yoy_s = _daily(yoy)
    if not yoy_s.empty:
        yoy_s.index = yoy_s.index + pd.Timedelta(days=364)
        refs[f"Год назад ({yoy[0]:%d.%m.%y}–{yoy[1]:%d.%m.%y})"] = yoy_s
    if not cur_s.empty:
        st.plotly_chart(
            charts.compare_ts(cur_s, refs, cur_label=f"Текущий ({ctx.d_from:%d.%m}–{ctx.d_to:%d.%m})",
                              y_title="Выручка"),
            width="stretch",
        )
        if lfl_on and cmp_prev.lfl_excluded:
            st.caption(f"График построен по сопоставимым филиалам: {', '.join(br_set)}")

    st.divider()

    # ---- Структура по группам ----
    st.markdown("#### 📦 Структура по группам")
    g_cur = (base[(base["Дата"] >= pd.Timestamp(cur[0])) & (base["Дата"] <= pd.Timestamp(cur[1]))]
             .groupby("Группа")["Сумма"].sum().sort_values(ascending=False))
    g_prev = (base[(base["Дата"] >= pd.Timestamp(prev[0])) & (base["Дата"] <= pd.Timestamp(prev[1]))]
              .groupby("Группа")["Сумма"].sum())
    if not g_cur.empty:
        col_chart, col_tbl = st.columns([1.3, 1])
        with col_chart:
            chart_df = g_cur.reset_index().rename(columns={"Сумма": "Выручка"})
            st.plotly_chart(charts.barh_top(chart_df, "Группа", "Выручка", n=len(chart_df)),
                            width="stretch")
        with col_tbl:
            tbl = pd.DataFrame({
                "Группа": g_cur.index,
                "Выручка": g_cur.values,
            })
            tbl["Доля"] = tbl["Выручка"] / tbl["Выручка"].sum()
            prev_per_day = tbl["Группа"].map(g_prev).fillna(0) / cmp_prev.ref_days
            cur_per_day = tbl["Выручка"] / cmp_prev.cur_days
            tbl["Δ% vs пред."] = np.where(prev_per_day > 0,
                                          (cur_per_day - prev_per_day) / prev_per_day * 100, np.nan)
            disp = tbl.copy()
            disp["Выручка"] = disp["Выручка"].apply(money)
            disp["Доля"] = (tbl["Доля"] * 100).round(1).astype(str) + "%"
            disp["Δ% vs пред."] = tbl["Δ% vs пред."].apply(lambda v: pct(v))
            st.dataframe(disp, width="stretch", hide_index=True,
                         height=min(38 * len(disp) + 40, 360))

    st.divider()

    # ---- Автоинсайты ----
    st.markdown("#### 🧠 Автоинсайты")
    col_left, col_right = st.columns(2)

    with col_left:
        df_prev = ctx.df_universe[
            (ctx.df_universe["Дата"] >= pd.Timestamp(prev[0])) &
            (ctx.df_universe["Дата"] <= pd.Timestamp(prev[1]))]
        cur_sku = ctx.df_f.groupby("Номенклатура")["Сумма"].sum()
        prev_sku = (df_prev.groupby("Номенклатура")["Сумма"].sum()
                    if not df_prev.empty else pd.Series(dtype=float))
        skus = pd.DataFrame({"cur": cur_sku, "prev": prev_sku}).fillna(0)
        skus = skus[skus["cur"] + skus["prev"] > 0]
        skus["delta_abs"] = skus["cur"] - skus["prev"]
        skus["delta_pct"] = np.where(skus["prev"] > 0,
                                     (skus["cur"] - skus["prev"]) / skus["prev"] * 100,
                                     np.where(skus["cur"] > 0, 999.0, 0.0))
        threshold = skus["cur"].quantile(0.75) if len(skus) > 4 else 0
        significant = skus[(skus["cur"] >= threshold) | (skus["prev"] >= threshold)]

        st.markdown("**📈 Топ-5 растущих SKU** (vs пред. период)")
        risers = significant.sort_values("delta_abs", ascending=False).head(5).reset_index()
        if not risers.empty:
            for _, r in risers.iterrows():
                p = f"+{r['delta_pct']:.0f}%" if r["delta_pct"] < 900 else "новый"
                insight_card(f"🟢 {r['Номенклатура']}",
                             f"+{money(r['delta_abs'])} сом <b>({p})</b> "
                             f"&nbsp; {money(r['prev'])} → {money(r['cur'])}", "ok")
        else:
            st.caption("— нет данных для сравнения")

        st.markdown("**📉 Топ-5 падающих SKU**")
        fallers = significant.sort_values("delta_abs").head(5).reset_index()
        fallers = fallers[fallers["delta_abs"] < 0]
        if not fallers.empty:
            for _, r in fallers.iterrows():
                insight_card(f"🔴 {r['Номенклатура']}",
                             f"{money(r['delta_abs'])} сом <b>({r['delta_pct']:.0f}%)</b> "
                             f"&nbsp; {money(r['prev'])} → {money(r['cur'])}", "danger")
        else:
            st.caption("— нет падающих SKU")

    with col_right:
        st.markdown("**⚠️ Аномальные дни** (|Z| > 2σ)")
        anom = detect_anomalies(daily_series(ctx.df_f, ctx.metric_col))
        if not anom.empty:
            for _, r in anom.head(5).iterrows():
                day_str = pd.Timestamp(r["Day"]).strftime("%d.%m.%Y") if not pd.isna(r["Day"]) else "—"
                kind = "warn" if r["Тип"].startswith("⬆") else "danger"
                insight_card(f"{r['Тип']} {day_str}",
                             f"{money(r['Value'])} (Z = {r['Z']:+.2f})", kind)
        else:
            st.caption("— аномалий не обнаружено")

        st.markdown(f"**💤 Мёртвые SKU** (нет продаж 14+ дней на {ctx.max_d:%d.%m.%Y})")
        active_skus = set(ctx.df_f["Номенклатура"].unique())
        all_active = ctx.df_universe[ctx.df_universe["Номенклатура"].isin(active_skus)]
        last_sale = all_active.groupby("Номенклатура")["Дата"].max()
        ref_ts = pd.Timestamp(ctx.max_d)  # от даты свежести данных, не от конца периода
        dead = last_sale[(ref_ts - last_sale).dt.days > 14]
        dead_df = pd.DataFrame({"Последняя продажа": dead}).sort_values("Последняя продажа")
        dead_df["Дней назад"] = (ref_ts - dead_df["Последняя продажа"]).dt.days
        if not dead_df.empty:
            for name, r in dead_df.head(5).iterrows():
                insight_card(f"💤 {name}",
                             f"Последняя продажа {r['Последняя продажа']:%d.%m.%Y} "
                             f"<b>({r['Дней назад']} дней назад)</b>", "warn")
            if len(dead_df) > 5:
                st.caption(f"… и ещё {len(dead_df) - 5} SKU без продаж")
        else:
            st.caption("— все SKU активны")

    st.divider()

    # ---- Филиалы: /день, vs пред. период и vs год назад ----
    st.markdown("#### 🏢 Филиалы (выручка/день)")
    base_all = ctx.df_universe

    def _by_branch(p):
        f = base_all[(base_all["Дата"] >= pd.Timestamp(p[0])) & (base_all["Дата"] <= pd.Timestamp(p[1]))]
        return f.groupby("Филиал")["Сумма"].sum()

    b_cur, b_prev, b_yoy = _by_branch(cur), _by_branch(prev), _by_branch(yoy)
    # пометки несопоставимости — независимо от toggle LFL
    _, exc_prev = lfl_split(ctx.ap["branches"], cur, prev)
    _, exc_yoy = lfl_split(ctx.ap["branches"], cur, yoy)
    days_cur = cmp_prev.cur_days
    rows = []
    for br in sorted(ctx.ap["branches"], key=lambda b: -float(b_cur.get(b, 0))):
        c = float(b_cur.get(br, 0)) / days_cur
        p = float(b_prev.get(br, 0)) / cmp_prev.ref_days
        y = float(b_yoy.get(br, 0)) / cmp_yoy.ref_days
        rows.append({
            "Филиал": br,
            "Текущий": money(c),
            "Пред. период": money(p) if p else "—",
            "Δ%": (f"⚠ {exc_prev[br]}" if br in exc_prev
                   else pct((c - p) / p * 100 if p else None)),
            "Год назад": money(y) if y else "—",
            "Δ% YoY": (f"⚠ {exc_yoy[br]}" if br in exc_yoy
                       else pct((c - y) / y * 100 if y else None)),
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("⚠ — филиал не сопоставим в этом сравнении (открытие/закрытие), Δ% не считается.")
