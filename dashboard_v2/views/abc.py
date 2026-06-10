"""ABC / Pareto — анализ ассортимента: один период или сравнение двух.

Перенос вкладки 3 из старого app2.py с минимальными изменениями
(источники данных из ctx, Pareto-график на Plotly). Ключи виджетов
abc_* сохранены, чтобы не сбрасывать состояние пользователей.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from core import charts
from core.config import A_THR, B_THR
from core.context import AppContext
from core.excel import dl_btn
from core.helpers import margin_by_sku, money, num
from core.ui import own_period_note


def _agg_period(df_p: pd.DataFrame, level_col: str, cost_ref: pd.DataFrame | None) -> pd.DataFrame:
    """Агрегат по уровню с обогащением себестоимостью на SKU-уровне."""
    if df_p.empty:
        return pd.DataFrame(columns=[level_col, "Сумма", "Количество", "Маржа"])
    sku = margin_by_sku(df_p, cost_ref)
    if level_col == "Номенклатура":
        sku["% маржи"] = np.where(sku["Сумма"] > 0, sku["Маржа"] / sku["Сумма"], np.nan)
        return sku
    meta = df_p[["Номенклатура", level_col]].drop_duplicates("Номенклатура")
    sku = sku.merge(meta, on="Номенклатура", how="left")
    agg = (sku.groupby(level_col, dropna=False)
           .agg(Сумма=("Сумма", "sum"),
                Количество=("Количество", "sum"),
                Маржа=("Маржа", "sum"))
           .reset_index())
    agg["% маржи"] = np.where(agg["Сумма"] > 0, agg["Маржа"] / agg["Сумма"], np.nan)
    return agg


def _compute_abc(df_agg: pd.DataFrame, value_col: str) -> pd.DataFrame:
    if df_agg.empty:
        return df_agg
    x = df_agg.sort_values(value_col, ascending=False).reset_index(drop=True)
    tot = float(x[value_col].sum())
    if tot > 0:
        x["Доля"] = x[value_col] / tot
        x["Кум. доля"] = x["Доля"].cumsum()
        x["ABC"] = x["Кум. доля"].apply(
            lambda v: "A" if v <= A_THR else ("B" if v <= B_THR else "C"))
    else:
        x["Доля"] = 0.0
        x["Кум. доля"] = 0.0
        x["ABC"] = "—"
    return x


def _period_picker(label: str, default: tuple, key_prefix: str) -> tuple:
    """Дата-пикер, ПОЛНОСТЬЮ независимый от глобального date-фильтра.

    Один раз кладём default в session_state, дальше виджет читает ТОЛЬКО
    через key= (без value=), чтобы Streamlit не перезаписывал значение
    дефолтом при смене глобальных фильтров.
    """
    kf, kt = f"{key_prefix}_from", f"{key_prefix}_to"
    if kf not in st.session_state:
        st.session_state[kf] = pd.Timestamp(default[0]).date()
    if kt not in st.session_state:
        st.session_state[kt] = pd.Timestamp(default[1]).date()
    c1, c2 = st.columns(2)
    with c1:
        f = st.date_input(f"{label} — с", key=kf)
    with c2:
        t = st.date_input(f"{label} — по", key=kt)
    return pd.Timestamp(f), pd.Timestamp(t)


def _auto_clip(p1f, p1t, p2f, p2t):
    """Обрезаем длинный период с конца, чтобы длины совпали."""
    l1 = (p1t - p1f).days
    l2 = (p2t - p2f).days
    if l1 == l2:
        return p1f, p1t, p2f, p2t, False, ""
    if l1 > l2:
        return p1f, p1f + pd.Timedelta(days=l2), p2f, p2t, True, \
               f"Период 1 обрезан до {l2+1} дн., чтобы совпасть с Периодом 2"
    return p1f, p1t, p2f, p2f + pd.Timedelta(days=l1), True, \
           f"Период 2 обрезан до {l1+1} дн., чтобы совпасть с Периодом 1"


def render(ctx: AppContext) -> None:
    st.subheader("🔝 ABC / Pareto — анализ ассортимента")
    own_period_note()
    st.caption("Можно сравнивать два окна — длинный авто-обрезается до короткого.")

    df_universe = ctx.df_universe
    cost_ref = ctx.cost_ref
    d_from, d_to = ctx.d_from, ctx.d_to

    abc_mode = st.radio("Режим", ["Один период", "Сравнение двух периодов"],
                        horizontal=True, key="abc_mode_v2")

    cc1, cc2 = st.columns(2)
    with cc1:
        abc_level = st.selectbox("Уровень",
                                 ["Номенклатура", "Подкатегория", "Категория", "Группа"],
                                 key="abc_level_v2")
    with cc2:
        metric_opts = ["Выручка (сом)", "Количество (шт)"]
        if cost_ref is not None and not cost_ref.empty:
            metric_opts.append("Маржа (сом)")
        abc_metric_sel = st.selectbox("Метрика", metric_opts, key="abc_metric_v2")
    value_col = {"Выручка (сом)": "Сумма",
                 "Количество (шт)": "Количество",
                 "Маржа (сом)": "Маржа"}[abc_metric_sel]

    if cost_ref is None or cost_ref.empty:
        st.info("⚠️ Справочник себестоимости не загружен — метрика «Маржа» и колонки маржи недоступны.")

    # =========================================================================
    # РЕЖИМ A: один период
    # =========================================================================
    if abc_mode == "Один период":
        cb1, cb2 = st.columns([4, 1])
        with cb2:
            if st.button("↩️ Сбросить", key="abc_single_reset", help="Сбросить период к глобальному"):
                st.session_state["abc_single_from"] = pd.Timestamp(d_from).date()
                st.session_state["abc_single_to"] = pd.Timestamp(d_to).date()
                st.rerun()
        p_from, p_to = _period_picker("Период", (d_from, d_to), "abc_single")
        df_p = df_universe[(df_universe["Дата"] >= p_from) & (df_universe["Дата"] <= p_to)]
        st.caption(f"📅 {p_from:%d.%m.%Y} – {p_to:%d.%m.%Y}  ·  "
                   f"{len(df_p):,} строк  ·  "
                   f"{df_p['Номенклатура'].nunique() if not df_p.empty else 0} {abc_level.lower()}")

        if df_p.empty:
            st.info("Нет данных за выбранный период.")
            return

        res = _compute_abc(_agg_period(df_p, abc_level, cost_ref), value_col)
        stats = (res.groupby("ABC", observed=True)
                 .agg(SKU=(abc_level, "count"), Value=(value_col, "sum")).reset_index())
        tot_val = stats["Value"].sum() or 1.0
        tot_sku = stats["SKU"].sum() or 1
        stats["%выр"] = stats["Value"] / tot_val
        stats["%SKU"] = stats["SKU"] / tot_sku
        stats["ABC"] = pd.Categorical(stats["ABC"], categories=["A", "B", "C", "—"], ordered=True)
        stats = stats.sort_values("ABC")

        c_l, c_r = st.columns([1, 2])
        with c_l:
            st.markdown("**A/B/C сводка**")
            st.dataframe(stats, width="stretch", hide_index=True)
            top_n = st.slider("Top-N для Pareto", 10, 200, 30, 10, key="abc_topn_v2")
        with c_r:
            d_chart = res.head(top_n)
            st.plotly_chart(
                charts.pareto(d_chart, abc_level, value_col, "Кум. доля",
                              title=f"Pareto Top {top_n} · {p_from:%d.%m.%Y}–{p_to:%d.%m.%Y}"),
                width="stretch",
            )

        st.markdown("**Таблица**")
        show_cols = [abc_level, "Сумма", "Количество", "Доля", "Кум. доля", "ABC"]
        if "Маржа" in res.columns:
            show_cols += ["Маржа", "% маржи"]
        if abc_level == "Номенклатура" and "Себес полн." in res.columns:
            show_cols.insert(-2, "Себес полн.")
        st.dataframe(res[show_cols].head(500), width="stretch", hide_index=True)

        dl_btn(f"Скачать ABC ({abc_level})",
               [("ABC", res[show_cols], f"ABC {abc_level} — {abc_metric_sel}"),
                ("Сводка A/B/C", stats, "Сводка")],
               filename=f"abc_{abc_level.lower()}_{p_from:%Y%m%d}_{p_to:%Y%m%d}.xlsx",
               key="dl_abc_v2_single")
        return

    # =========================================================================
    # РЕЖИМ B: сравнение двух периодов
    # =========================================================================
    max_d = pd.Timestamp(df_universe["Дата"].max()).normalize() \
        if not df_universe.empty else pd.Timestamp("today").normalize()

    st.markdown("**Пресеты:**")
    bc1, bc2, bc3, bc4 = st.columns(4)

    def _set_dates(p1f, p1t, p2f, p2t):
        st.session_state["abc_cmp_p1_from"] = p1f.date()
        st.session_state["abc_cmp_p1_to"] = p1t.date()
        st.session_state["abc_cmp_p2_from"] = p2f.date()
        st.session_state["abc_cmp_p2_to"] = p2t.date()

    if bc1.button("YTD vs прошлый год", width="stretch", key="abc_p_ytd"):
        p2f = pd.Timestamp(year=max_d.year, month=1, day=1)
        p2t = max_d
        p1f = pd.Timestamp(year=max_d.year - 1, month=1, day=1)
        p1t = pd.Timestamp(year=max_d.year - 1, month=max_d.month, day=max_d.day)
        _set_dates(p1f, p1t, p2f, p2t)
        st.rerun()
    if bc2.button("Последние 30 vs пред. 30", width="stretch", key="abc_p_30"):
        p2t = max_d
        p2f = max_d - pd.Timedelta(days=29)
        p1t = p2f - pd.Timedelta(days=1)
        p1f = p1t - pd.Timedelta(days=29)
        _set_dates(p1f, p1t, p2f, p2t)
        st.rerun()
    if bc3.button("Месяц vs прошлый год", width="stretch", key="abc_p_mom"):
        p2f = pd.Timestamp(year=max_d.year, month=max_d.month, day=1)
        p2t = max_d
        p1f = pd.Timestamp(year=max_d.year - 1, month=max_d.month, day=1)
        p1t = pd.Timestamp(year=max_d.year - 1, month=max_d.month, day=max_d.day)
        _set_dates(p1f, p1t, p2f, p2t)
        st.rerun()
    if bc4.button("Квартал vs прошлый год", width="stretch", key="abc_p_qoq"):
        qm = ((max_d.month - 1) // 3) * 3 + 1
        p2f = pd.Timestamp(year=max_d.year, month=qm, day=1)
        p2t = max_d
        p1f = pd.Timestamp(year=max_d.year - 1, month=qm, day=1)
        p1t = pd.Timestamp(year=max_d.year - 1, month=max_d.month, day=max_d.day)
        _set_dates(p1f, p1t, p2f, p2t)
        st.rerun()

    d_p2t = max_d
    d_p2f = max_d - pd.Timedelta(days=29)
    d_p1t = d_p2f - pd.Timedelta(days=1)
    d_p1f = d_p1t - pd.Timedelta(days=29)

    st.markdown("**Период 1 (база сравнения):**")
    p1f, p1t = _period_picker("Период 1", (d_p1f, d_p1t), "abc_cmp_p1")
    st.markdown("**Период 2 (анализируемый):**")
    p2f, p2t = _period_picker("Период 2", (d_p2f, d_p2t), "abc_cmp_p2")

    p1f, p1t, p2f, p2t, clipped, clip_msg = _auto_clip(p1f, p1t, p2f, p2t)
    if clipped:
        st.warning(f"⚠️ {clip_msg}")
    st.caption(f"📅 П1: {p1f:%d.%m.%Y}–{p1t:%d.%m.%Y}  ·  П2: {p2f:%d.%m.%Y}–{p2t:%d.%m.%Y}")

    df_p1 = df_universe[(df_universe["Дата"] >= p1f) & (df_universe["Дата"] <= p1t)]
    df_p2 = df_universe[(df_universe["Дата"] >= p2f) & (df_universe["Дата"] <= p2t)]

    if df_p1.empty and df_p2.empty:
        st.info("Нет данных ни в одном из периодов.")
        return

    r1 = _compute_abc(_agg_period(df_p1, abc_level, cost_ref), value_col)
    r2 = _compute_abc(_agg_period(df_p2, abc_level, cost_ref), value_col)
    r1 = r1[[abc_level, value_col, "ABC"]].rename(
        columns={value_col: f"{value_col}_1", "ABC": "ABC_1"})
    r2_keep = [abc_level, value_col, "ABC"]
    if "% маржи" in r2.columns:
        r2_keep.append("% маржи")
    if "Маржа" in r2.columns and value_col != "Маржа":
        r2_keep.append("Маржа")
    r2 = r2[r2_keep].rename(columns={value_col: f"{value_col}_2", "ABC": "ABC_2"})

    m = r1.merge(r2, on=abc_level, how="outer")
    m[f"{value_col}_1"] = m[f"{value_col}_1"].fillna(0)
    m[f"{value_col}_2"] = m[f"{value_col}_2"].fillna(0)
    m["Δ"] = m[f"{value_col}_2"] - m[f"{value_col}_1"]
    m["Δ_%"] = np.where(m[f"{value_col}_1"] > 0,
                        m["Δ"] / m[f"{value_col}_1"], np.nan)

    v1, v2 = m[f"{value_col}_1"].sum(), m[f"{value_col}_2"].sum()
    d_abs = v2 - v1
    d_pct = d_abs / v1 if v1 else 0
    mk1, mk2, mk3 = st.columns(3)
    fmt = (lambda x: money(x)) if value_col != "Количество" else (lambda x: num(x))
    mk1.metric(f"{abc_metric_sel} · П1", fmt(v1))
    mk2.metric(f"{abc_metric_sel} · П2", fmt(v2), delta=f"{d_pct*100:+.1f}%")
    n_new = int((m[f"{value_col}_1"] == 0).sum())
    n_lost = int((m[f"{value_col}_2"] == 0).sum())
    mk3.metric("Новинки / Снятые", f"+{n_new} / −{n_lost}")

    sub_tabs = st.tabs(["📊 Pareto-Drift", "🔄 ABC-матрица", "📈 Growers",
                        "📉 Decliners", "🆕 Новинки/Снятые", "🚨 Кандидаты"])

    with sub_tabs[0]:
        st.markdown("**Pareto Периода 2 + смещение класса ABC**")
        drift = m.sort_values(f"{value_col}_2", ascending=False).copy()
        drift["ABC_1"] = drift["ABC_1"].fillna("—")
        drift["ABC_2"] = drift["ABC_2"].fillna("—")
        drift["Drift"] = drift["ABC_1"].astype(str) + " → " + drift["ABC_2"].astype(str)
        cols = [abc_level, f"{value_col}_1", f"{value_col}_2", "Δ", "Δ_%",
                "ABC_1", "ABC_2", "Drift"]
        st.dataframe(drift[cols].head(100), width="stretch", hide_index=True)

    with sub_tabs[1]:
        st.markdown("**Матрица переходов ABC (Период 1 → Период 2)**")
        mm = m.copy()
        mm["ABC_1"] = mm["ABC_1"].fillna("новинки")
        mm["ABC_2"] = mm["ABC_2"].fillna("сняты")
        pivot_n = pd.crosstab(mm["ABC_1"], mm["ABC_2"])
        pivot_v = (mm.groupby(["ABC_1", "ABC_2"])[f"{value_col}_2"]
                   .sum().unstack(fill_value=0))
        a, b = st.columns(2)
        with a:
            st.markdown("По SKU (число позиций)")
            st.dataframe(pivot_n, width="stretch")
        with b:
            st.markdown(f"По {abc_metric_sel} в Периоде 2")
            st.dataframe(pivot_v.round(0).astype("Int64", errors="ignore"),
                         width="stretch")

    with sub_tabs[2]:
        st.markdown("**Топ-20 драйверов роста**")
        grow = m[m["Δ"] > 0].sort_values("Δ", ascending=False).head(20)
        show = [abc_level, f"{value_col}_1", f"{value_col}_2", "Δ", "Δ_%", "ABC_2"]
        st.dataframe(grow[show], width="stretch", hide_index=True)

    with sub_tabs[3]:
        st.markdown("**Топ-20 деклайнеров**")
        decl = m[m["Δ"] < 0].sort_values("Δ").head(20)
        show = [abc_level, f"{value_col}_1", f"{value_col}_2", "Δ", "Δ_%", "ABC_1", "ABC_2"]
        st.dataframe(decl[show], width="stretch", hide_index=True)

    with sub_tabs[4]:
        cl, cr = st.columns(2)
        new_items = m[m[f"{value_col}_1"] == 0].sort_values(f"{value_col}_2", ascending=False)
        lost_items = m[m[f"{value_col}_2"] == 0].sort_values(f"{value_col}_1", ascending=False)
        with cl:
            st.markdown(f"**🆕 Новинки** ({len(new_items)})")
            st.dataframe(new_items[[abc_level, f"{value_col}_2", "ABC_2"]].head(50),
                         width="stretch", hide_index=True)
        with cr:
            st.markdown(f"**❌ Снятые** ({len(lost_items)})")
            st.dataframe(lost_items[[abc_level, f"{value_col}_1", "ABC_1"]].head(50),
                         width="stretch", hide_index=True)

    with sub_tabs[5]:
        st.markdown("**🚨 Кандидаты на вывод** (≥ 2 сигналов риска)")
        cands = m.copy()
        flags_list = []
        sig_list = []
        for _, r in cands.iterrows():
            flags = []
            if r.get("ABC_2") == "C":
                flags.append("ABC=C")
            pm = r.get("% маржи")
            if pd.notna(pm) and pm < 0.30:
                flags.append("%маржи<30")
            dp = r.get("Δ_%")
            if pd.notna(dp) and dp < -0.30 and r[f"{value_col}_1"] > 0:
                flags.append("Δ<−30%")
            if r[f"{value_col}_2"] == 0 and r[f"{value_col}_1"] > 0:
                flags.append("снято")
            sig_list.append(len(flags))
            flags_list.append(", ".join(flags))
        cands["Сигналов"] = sig_list
        cands["Флаги"] = flags_list
        cands = (cands[cands["Сигналов"] >= 2]
                 .sort_values(["Сигналов", f"{value_col}_1"], ascending=[False, False]))
        show = [abc_level, "Сигналов", "Флаги", "ABC_1", "ABC_2",
                f"{value_col}_1", f"{value_col}_2", "Δ", "Δ_%"]
        if "% маржи" in cands.columns:
            show.append("% маржи")
        if cands.empty:
            st.success("✅ Кандидатов на вывод нет.")
        else:
            st.dataframe(cands[show].head(100), width="stretch", hide_index=True)

    dl_btn("Скачать сравнение",
           [("Сравнение", m, f"ABC {abc_level} · П1 vs П2"),
            ("Growers", m[m["Δ"] > 0].sort_values("Δ", ascending=False), "Драйверы роста"),
            ("Decliners", m[m["Δ"] < 0].sort_values("Δ"), "Падающие"),
            ("Новинки", m[m[f"{value_col}_1"] == 0].sort_values(f"{value_col}_2", ascending=False),
             "Новые в Периоде 2"),
            ("Снятые", m[m[f"{value_col}_2"] == 0].sort_values(f"{value_col}_1", ascending=False),
             "Исчезли в Периоде 2")],
           filename=(f"abc_cmp_{p1f:%Y%m%d}-{p1t:%Y%m%d}_"
                     f"vs_{p2f:%Y%m%d}-{p2t:%Y%m%d}.xlsx"),
           key="dl_abc_v2_cmp")
