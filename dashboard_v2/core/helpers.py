"""Форматирование, KPI-агрегаты, ABC, аномалии, прогноз, cross-sell, склад."""
from __future__ import annotations

from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd
import streamlit as st

from core.config import CHECKS_COL, A_THR, B_THR


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------
def money(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:,.0f}".replace(",", " ")


def num(x: float, decimals: int = 0) -> str:
    if pd.isna(x):
        return "—"
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(x).replace(",", " ")


def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def pct(x: float | None, decimals: int = 1) -> str:
    if x is None or pd.isna(x):
        return "—"
    return f"{x:+.{decimals}f}%"


# ---------------------------------------------------------------------------
# Чеки и KPI
# ---------------------------------------------------------------------------
def clean_checks(s: pd.Series) -> pd.Series:
    return (s.astype(str).str.strip()
            .str.replace(r"\s+", " ", regex=True)
            .replace({"": pd.NA, "nan": pd.NA}))


def count_checks(frame: pd.DataFrame) -> int:
    if CHECKS_COL not in frame.columns or frame.empty:
        return 0
    return int(clean_checks(frame[CHECKS_COL]).dropna().nunique())


def kpi_group(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_cols + ["Выручка", "Количество", "Чеков",
                                                  "Средний чек", "Позиции/чек", "Товаров/чек", "Доля выручки"])
    g = frame.groupby(group_cols, dropna=False).agg(
        Выручка=("Сумма", "sum"), Количество=("Количество", "sum"), Строк=("Сумма", "size"),
    ).reset_index()
    checks = frame[group_cols + [CHECKS_COL]].copy()
    checks[CHECKS_COL] = clean_checks(checks[CHECKS_COL])
    checks = checks.dropna(subset=[CHECKS_COL])
    if not checks.empty:
        cnt = checks.groupby(group_cols)[CHECKS_COL].nunique().reset_index().rename(columns={CHECKS_COL: "Чеков"})
        g = g.merge(cnt, on=group_cols, how="left")
    else:
        g["Чеков"] = 0
    g["Чеков"] = g["Чеков"].fillna(0).astype(int)
    g["Средний чек"] = g.apply(lambda r: r["Выручка"] / r["Чеков"] if r["Чеков"] else 0.0, axis=1)
    g["Позиции/чек"] = g.apply(lambda r: r["Строк"] / r["Чеков"] if r["Чеков"] else 0.0, axis=1)
    g["Товаров/чек"] = g.apply(lambda r: r["Количество"] / r["Чеков"] if r["Чеков"] else 0.0, axis=1)
    total = float(g["Выручка"].sum()) or 0.0
    g["Доля выручки"] = g["Выручка"] / total if total else 0.0
    return g.sort_values("Выручка", ascending=False).drop(columns=["Строк"])


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------
def build_abc(frame: pd.DataFrame, group_cols: list[str], metric_col: str = "Сумма") -> pd.DataFrame:
    g = (frame.groupby(group_cols, dropna=False)[metric_col]
         .sum().reset_index().rename(columns={metric_col: "Value"})
         .sort_values("Value", ascending=False).reset_index(drop=True))
    total = float(g["Value"].sum()) if not g.empty else 0.0
    if total <= 0 or pd.isna(total):
        g["Share"] = g["CumShare"] = 0.0
    else:
        g["Share"] = g["Value"] / total
        g["CumShare"] = g["Share"].cumsum()
    g["ABC"] = g["CumShare"].apply(lambda x: "A" if x <= A_THR else ("B" if x <= B_THR else "C"))
    return g


def abc_summary(abc_df: pd.DataFrame) -> pd.DataFrame:
    if abc_df.empty:
        return pd.DataFrame(columns=["ABC", "SKU_count", "SKU_share", "Value", "Value_share"])
    tsku = len(abc_df)
    tval = float(abc_df["Value"].sum()) or 0.0
    s = abc_df.groupby("ABC")["Value"].agg(SKU_count="count", Value="sum").reset_index()
    s["SKU_share"] = s["SKU_count"] / tsku if tsku else 0.0
    s["Value_share"] = s["Value"] / tval if tval else 0.0
    s["ABC"] = pd.Categorical(s["ABC"], categories=["A", "B", "C"], ordered=True)
    return s.sort_values("ABC").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Время / дневные ряды
# ---------------------------------------------------------------------------
def add_time_cols(frame: pd.DataFrame) -> pd.DataFrame:
    """Hour + DOW из колонки «Время». Пустой df, если времени нет."""
    out = frame.copy()
    if "Время" not in out.columns:
        return out.iloc[0:0].copy()
    t = pd.to_datetime(out["Время"].astype(str).str.strip(),
                       format="%H:%M:%S", errors="coerce")
    out["Hour"] = t.dt.hour
    out = out[out["Hour"].notna()].copy()
    out["Hour"] = out["Hour"].astype(int)
    out["DOW"] = out["Дата"].dt.dayofweek
    return out


def daily_series(frame: pd.DataFrame, metric_col: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["Day", "Value"])
    return (frame.set_index("Дата")[metric_col].resample("D").sum().reset_index()
            .rename(columns={"Дата": "Day", metric_col: "Value"}))


def detect_anomalies(daily_df: pd.DataFrame, z_threshold: float = 2.0) -> pd.DataFrame:
    """daily_df: колонки Day, Value. Возвращает строки с |Z| > threshold."""
    if daily_df.empty or len(daily_df) < 7:
        return pd.DataFrame()
    d = daily_df.copy()
    mu = d["Value"].mean()
    sd = d["Value"].std() or 1.0
    d["Z"] = (d["Value"] - mu) / sd
    d["Тип"] = d["Z"].apply(lambda z: "⬆️ Пик" if z > z_threshold else ("⬇️ Провал" if z < -z_threshold else None))
    return d[d["Тип"].notna()].sort_values("Z", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Маржа (через справочник себестоимости)
# ---------------------------------------------------------------------------
def margin_by_sku(frame: pd.DataFrame, cost_ref: pd.DataFrame | None) -> pd.DataFrame:
    """SKU-агрегат с маржой: Маржа = (Ср.цена − Себес полн.) × Кол."""
    if frame.empty:
        return pd.DataFrame(columns=["Номенклатура", "Сумма", "Количество", "Маржа"])
    sku = (frame.groupby("Номенклатура", dropna=False)
           .agg(Сумма=("Сумма", "sum"), Количество=("Количество", "sum"))
           .reset_index())
    if cost_ref is not None and not cost_ref.empty:
        sku = sku.merge(cost_ref[["Номенклатура", "Себес полн."]], on="Номенклатура", how="left")
        sku["Ср. цена"] = np.where(sku["Количество"] > 0, sku["Сумма"] / sku["Количество"], np.nan)
        sku["Маржа"] = ((sku["Ср. цена"] - sku["Себес полн."]) * sku["Количество"]).fillna(0)
    else:
        sku["Себес полн."] = np.nan
        sku["Ср. цена"] = np.nan
        sku["Маржа"] = np.nan
    return sku


# ---------------------------------------------------------------------------
# Cross-sell
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def build_crosssell(df_in_hash: pd.DataFrame, min_support: int = 5) -> pd.DataFrame:
    """Пары номенклатур из одного чека: Pair_count, Support, Confidence, Lift."""
    if df_in_hash.empty or CHECKS_COL not in df_in_hash.columns:
        return pd.DataFrame()

    df_c = df_in_hash[[CHECKS_COL, "Номенклатура"]].copy()
    df_c[CHECKS_COL] = clean_checks(df_c[CHECKS_COL])
    df_c = df_c.dropna(subset=[CHECKS_COL, "Номенклатура"])
    checks_grouped = df_c.groupby(CHECKS_COL)["Номенклатура"].apply(lambda s: sorted(set(s)))
    total_checks = len(checks_grouped)
    if total_checks == 0:
        return pd.DataFrame()

    item_count: Counter = Counter()
    pair_count: Counter = Counter()
    for items in checks_grouped.values:
        if len(items) < 2:
            continue
        for it in items:
            item_count[it] += 1
        for a, b in combinations(items, 2):
            pair_count[(a, b)] += 1

    rows = []
    for (a, b), cnt in pair_count.items():
        if cnt < min_support:
            continue
        sa, sb = item_count[a], item_count[b]
        support_a = sa / total_checks
        support_b = sb / total_checks
        conf_ab = cnt / sa if sa else 0.0
        conf_ba = cnt / sb if sb else 0.0
        lift = conf_ab / support_b if support_b else 0.0
        rows.append({
            "A": a, "B": b, "Pair_count": cnt,
            "Support_A": support_a, "Support_B": support_b,
            "Confidence_A→B": conf_ab, "Confidence_B→A": conf_ba,
            "Lift": round(lift, 3),
        })
    res = pd.DataFrame(rows)
    if res.empty:
        return res
    return res.sort_values(["Lift", "Pair_count"], ascending=[False, False]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Прогноз спроса
# ---------------------------------------------------------------------------
def forecast_demand(df_in: pd.DataFrame, horizon_days: int,
                    metric: str = "Количество") -> pd.DataFrame:
    """Среднее по дню недели за последние 4 недели + линейный тренд за 30 дней."""
    if df_in.empty:
        return pd.DataFrame()
    daily = df_in.groupby(df_in["Дата"].dt.date)[metric].sum()
    if len(daily) < 7:
        avg = float(daily.mean()) if len(daily) else 0.0
        last = pd.Timestamp(daily.index[-1]) if len(daily) else pd.Timestamp.today()
        future = [last + pd.Timedelta(days=i + 1) for i in range(horizon_days)]
        return pd.DataFrame({"Дата": future, "Прогноз": [avg] * horizon_days})

    idx = pd.to_datetime(daily.index)
    daily.index = idx
    dow_avg = {}
    cutoff_28 = idx.max() - pd.Timedelta(days=28)
    last28 = daily[daily.index >= cutoff_28] if len(daily) >= 28 else daily
    for d in range(7):
        vals = last28[last28.index.dayofweek == d]
        dow_avg[d] = float(vals.mean()) if len(vals) else float(daily.mean())

    cutoff_30 = idx.max() - pd.Timedelta(days=30)
    last30 = daily[daily.index >= cutoff_30] if len(daily) >= 30 else daily
    x = np.arange(len(last30))
    y = last30.values.astype(float)
    if len(x) >= 2 and np.std(x) > 0:
        slope, _ = np.polyfit(x, y, 1)
    else:
        slope = 0.0

    last_ts = idx.max()
    future_rows = []
    for i in range(1, horizon_days + 1):
        ts = last_ts + pd.Timedelta(days=i)
        base_val = dow_avg[ts.dayofweek]
        adj = base_val + slope * i * 0.3
        future_rows.append({"Дата": ts, "Прогноз": max(adj, 0.0),
                            "День недели": ts.strftime("%a")})
    return pd.DataFrame(future_rows)


# ---------------------------------------------------------------------------
# Склад: неснижаемые остатки + BOM
# ---------------------------------------------------------------------------
def build_safety_stock(df_in: pd.DataFrame, days_in_period: int, cover_days: int,
                       abc_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if df_in.empty:
        return pd.DataFrame()
    extras = [c for c in ["Категория", "Подкатегория", "Группа"] if c in df_in.columns]
    g = (df_in.groupby("Номенклатура", dropna=False)
         .agg(Итого_кол=("Количество", "sum"), Итого_сом=("Сумма", "sum"))
         .reset_index())
    g["Среднее/день (кол)"] = g["Итого_кол"] / days_in_period
    g["Среднее/день (сом)"] = g["Итого_сом"] / days_in_period
    g["Остаток (шт)"] = (g["Среднее/день (кол)"] * cover_days).apply(lambda x: max(int(np.ceil(x)), 1))
    g["Остаток (сом)"] = g["Среднее/день (сом)"] * cover_days
    if abc_df is not None and not abc_df.empty:
        abc_map = abc_df.set_index("Номенклатура")["ABC"].to_dict()
        g["ABC"] = g["Номенклатура"].map(abc_map).fillna("—")
    else:
        g["ABC"] = "—"
    if extras:
        meta = df_in[["Номенклатура"] + extras].drop_duplicates("Номенклатура").reset_index(drop=True)
        g = g.merge(meta, on="Номенклатура", how="left")
    g = g.rename(columns={"Итого_кол": "Итого (кол)", "Итого_сом": "Итого (сом)"})
    order = ["Номенклатура"] + extras + ["Итого (кол)", "Итого (сом)",
             "Среднее/день (кол)", "Среднее/день (сом)", "Остаток (шт)", "Остаток (сом)", "ABC"]
    g = g[[c for c in order if c in g.columns]]
    return g.sort_values("Остаток (шт)", ascending=False).reset_index(drop=True)


def build_components(df_sales: pd.DataFrame, bom: pd.DataFrame,
                     days: int, cover: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df_sales.empty or bom.empty:
        return pd.DataFrame(), pd.DataFrame()
    sales_agg = (df_sales.groupby("Номенклатура", dropna=False)["Количество"]
                 .sum().reset_index().rename(columns={"Количество": "Прямые продажи"}))
    sales_map = dict(zip(sales_agg["Номенклатура"], sales_agg["Прямые продажи"]))
    sets_in_bom = set(bom["Набор"].unique())
    sets_sold = {k: v for k, v in sales_map.items() if k in sets_in_bom}
    direct = {k: v for k, v in sales_map.items() if k not in sets_in_bom}

    from_sets: dict[str, float] = {}
    for _, row in bom.iterrows():
        nb, comp, cnt = row["Набор"], row["Компонент"], float(row["Кол"])
        sold = sets_sold.get(nb, 0)
        from_sets[comp] = from_sets.get(comp, 0) + sold * cnt

    comp_unit = {}
    for _, row in bom.iterrows():
        c = row["Компонент"]
        if c not in comp_unit:
            comp_unit[c] = "кг" if float(row["Кол"]) < 1 else "шт"

    all_components = set(direct) | set(from_sets)
    rows_c = []
    for comp in sorted(all_components):
        dq = direct.get(comp, 0)
        fs = from_sets.get(comp, 0)
        tot = dq + fs
        unit = comp_unit.get(comp, "шт")
        avg = tot / days if days else 0
        stock = (round(avg * cover, 2) if unit == "кг"
                 else (max(int(np.ceil(avg * cover)), 1) if tot > 0 else 0))
        rows_c.append({
            "Компонент": comp, "Ед": unit,
            "Прямые продажи": round(dq, 3) if unit == "кг" else int(dq),
            "Из наборов":     round(fs, 3) if unit == "кг" else int(fs),
            "Итого":          round(tot, 3) if unit == "кг" else int(tot),
            "Среднее/день":   round(avg, 3),
            f"Остаток ({unit})": stock,
        })
    df_c = pd.DataFrame(rows_c)
    if not df_c.empty:
        df_c = df_c.sort_values(df_c.columns[-1], ascending=False).reset_index(drop=True)

    rows_s = []
    for nb in sorted(sets_in_bom):
        sold = sets_sold.get(nb, 0)
        avg = sold / days if days else 0
        rows_s.append({
            "Набор": nb, "Продано (шт)": int(sold),
            "Среднее/день": round(avg, 2),
            "Остаток (коробок)": max(int(np.ceil(avg * cover)), 1) if sold > 0 else 0,
        })
    df_s = pd.DataFrame(rows_s).sort_values("Продано (шт)", ascending=False).reset_index(drop=True)
    return df_c, df_s
