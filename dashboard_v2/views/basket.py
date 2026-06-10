"""Корзина и прогноз: cross-sell ассоциации + прогноз спроса."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from core import charts
from core.config import CHECKS_COL, COLORS
from core.context import AppContext
from core.events import closures_in
from core.excel import dl_btn
from core.helpers import build_crosssell, forecast_demand, money, num


def render(ctx: AppContext) -> None:
    st.subheader("🛒 Корзина и прогноз")
    tab_cs, tab_fc = st.tabs(["🛒 Cross-sell", "🎯 Прогноз спроса"])
    with tab_cs:
        _crosssell_tab(ctx)
    with tab_fc:
        _forecast_tab(ctx)


# ---------------------------------------------------------------------------
# Cross-sell
# ---------------------------------------------------------------------------
def _crosssell_tab(ctx: AppContext) -> None:
    st.caption("Пары товаров из одного чека. Lift > 1 означает «покупают вместе чаще случайного».")
    df_f = ctx.df_f
    if df_f.empty or CHECKS_COL not in df_f.columns:
        st.info("Нет данных о чеках.")
        return

    col1, col2, col3 = st.columns([1, 1, 1.4])
    with col1:
        min_support = st.slider(
            "Минимум пар в чеке", min_value=3, max_value=200, value=10, step=1,
            key="cs_minsup",
            help="Отсекаем пары, встретившиеся меньше N раз вместе. Выше = надёжнее, но меньше пар.",
        )
    with col2:
        show_top = st.slider("Показывать пар", 10, 200, 40, 10, key="cs_top")

    all_tochki = sorted(df_f["Точки"].dropna().unique().tolist()) if "Точки" in df_f.columns else []
    combo_options = []
    for i, a in enumerate(all_tochki):
        for b in all_tochki[i:]:
            combo_options.append(f"{a} — {b}")
    with col3:
        sel_combos = st.multiselect(
            "Связка точек", options=combo_options, default=[], key="cs_combos",
            placeholder="любые (по умолчанию все)",
            help="Например, 'Магазин — Бар' = пары, где один товар из Магазина, второй — из Бара.",
        )
    only_cross = st.checkbox(
        "Только межцеховые пары (Магазин↔Бар, Магазин↔Кухня, Бар↔Кухня)",
        value=False, key="cs_cross",
        help="Скрыть пары, где оба товара из одной точки.",
    )

    with st.spinner("Считаем ассоциации..."):
        cs = build_crosssell(df_f[[CHECKS_COL, "Номенклатура"]].copy(), min_support=min_support)

    if cs.empty:
        st.info(f"Нет пар с частотой ≥ {min_support}. Уменьши порог.")
        return

    sku_to_tochki = (df_f.dropna(subset=["Номенклатура", "Точки"])
                     .drop_duplicates("Номенклатура")
                     .set_index("Номенклатура")["Точки"].to_dict())
    cs["Точки_A"] = cs["A"].map(sku_to_tochki)
    cs["Точки_B"] = cs["B"].map(sku_to_tochki)

    def _combo_key(a, b):
        if pd.isna(a) or pd.isna(b):
            return None
        return " — ".join(sorted([a, b]))

    cs["_combo"] = [_combo_key(a, b) for a, b in zip(cs["Точки_A"], cs["Точки_B"])]

    if sel_combos:
        cs = cs[cs["_combo"].isin(sel_combos)]
    if only_cross:
        cs = cs[cs["Точки_A"] != cs["Точки_B"]]

    if cs.empty:
        st.warning("По выбранным связкам пар не нашлось. Сними фильтры или уменьши min_support.")
        return

    cols_order = ["A", "Точки_A", "B", "Точки_B", "Pair_count",
                  "Support_A", "Support_B", "Confidence_A→B", "Confidence_B→A", "Lift"]
    cols_order = [c for c in cols_order if c in cs.columns]
    cs = cs[cols_order + [c for c in cs.columns if c not in cols_order and c != "_combo"]]

    disp = cs.head(show_top).copy()
    for c in ["Support_A", "Support_B"]:
        if c in disp:
            disp[c] = (disp[c] * 100).round(2).astype(str) + "%"
    for c in ["Confidence_A→B", "Confidence_B→A"]:
        if c in disp:
            disp[c] = (disp[c] * 100).round(1).astype(str) + "%"
    st.dataframe(disp, width="stretch", hide_index=True, height=540)

    summary = (cs.assign(combo=cs["Точки_A"].fillna("?") + " — " + cs["Точки_B"].fillna("?"))
               .groupby("combo")["Pair_count"].agg(["sum", "count"])
               .rename(columns={"sum": "Σ покупок вместе", "count": "Уникальных пар"})
               .sort_values("Σ покупок вместе", ascending=False))
    st.markdown("**Сводка по связкам**")
    st.dataframe(summary, width="stretch", height=180)

    st.caption(
        "💡 **Как читать:** Если *Confidence A→B = 60%*, значит когда покупают A, "
        "в 60% случаев также берут B. **Lift = 2.5** → пара встречается в 2.5× чаще, "
        "чем ожидаемо при случайности."
    )
    dl_btn("Скачать пары",
           [("Cross-sell", cs, f"Ассоциации — min_support={min_support}")],
           filename=f"crosssell_{ctx.d_from:%Y%m%d}_{ctx.d_to:%Y%m%d}.xlsx", key="dl_cs")


# ---------------------------------------------------------------------------
# Прогноз спроса
# ---------------------------------------------------------------------------
def _forecast_tab(ctx: AppContext) -> None:
    st.caption("Алгоритм: среднее по дню недели за последние 4 недели + линейный тренд за 30 дней.")
    df_f = ctx.df_f
    if df_f.empty:
        st.info("Нет данных.")
        return

    # предупреждение, если в окно обучения попали открытия/простои филиалов
    train_from = ctx.d_to - timedelta(days=29)
    issues = closures_in(list(ctx.ap["branches"]), max(train_from, ctx.d_from), ctx.d_to)
    if issues:
        st.warning("⚠️ В окно обучения прогноза попали филиалы с неполной работой: "
                   + ", ".join(f"{br} ({r})" for br, r in issues.items())
                   + ". Прогноз может занижать/завышать спрос.")

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        horizon = st.selectbox("Горизонт", [7, 14, 30], key="fc_h")
    with c2:
        fc_metric = st.radio("Метрика", ["Количество", "Сумма"], horizontal=True, key="fc_m")
    with c3:
        level_fc = st.selectbox("Срез", ["Вся выборка", "По номенклатуре", "По категории", "По группе"],
                                key="fc_lvl")

    if level_fc == "Вся выборка":
        df_lvl = df_f
        title = "Вся выборка"
    else:
        col_map = {"По номенклатуре": "Номенклатура", "По категории": "Категория", "По группе": "Группа"}
        dim = col_map[level_fc]
        top = df_f.groupby(dim)["Сумма"].sum().sort_values(ascending=False).head(20).index.tolist()
        sel = st.selectbox(f"Выбери {dim.lower()}", top, key="fc_sel")
        df_lvl = df_f[df_f[dim] == sel]
        title = str(sel)

    fc = forecast_demand(df_lvl, horizon, metric=fc_metric)
    hist = df_lvl.groupby(df_lvl["Дата"].dt.date)[fc_metric].sum().reset_index()
    hist.columns = ["Дата", "Факт"]
    hist["Дата"] = pd.to_datetime(hist["Дата"])

    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["Дата"], y=hist["Факт"], name="Факт",
                             mode="lines+markers", marker=dict(size=4),
                             line=dict(width=1.8, color=COLORS["primary"])))
    if not fc.empty:
        fig.add_trace(go.Scatter(x=fc["Дата"], y=fc["Прогноз"], name="Прогноз",
                                 mode="lines+markers", marker=dict(size=5, symbol="square"),
                                 line=dict(width=2, dash="dash", color=COLORS["accent"])))
        fig.add_vrect(x0=fc["Дата"].min(), x1=fc["Дата"].max(),
                      fillcolor=COLORS["accent"], opacity=0.07, line_width=0)
    fig.update_yaxes(title=fc_metric, rangemode="tozero")
    st.plotly_chart(charts.apply_theme(fig, f"{title} — прогноз на {horizon} дней"),
                    width="stretch")

    if not fc.empty:
        st.markdown(f"**Прогноз на {horizon} дней**")
        fc_disp = fc.copy()
        fc_disp["Дата"] = fc_disp["Дата"].dt.strftime("%d.%m.%Y (%a)")
        fc_disp["Прогноз"] = fc_disp["Прогноз"].apply(
            money if fc_metric == "Сумма" else (lambda x: num(x, 1)))
        st.dataframe(fc_disp, width="stretch", hide_index=True)
        total_fc = fc["Прогноз"].sum()
        st.metric(f"Итого за {horizon} дн. ({fc_metric})",
                  money(total_fc) if fc_metric == "Сумма" else num(total_fc, 0))

        dl_btn("Скачать прогноз",
               [("Прогноз", fc, f"Прогноз — {horizon}д — {fc_metric}"),
                ("Факт", hist, "Исторический факт")],
               filename=f"forecast_{horizon}d.xlsx", key="dl_fc")
