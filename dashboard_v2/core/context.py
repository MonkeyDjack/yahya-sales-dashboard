"""AppContext — все данные/фильтры, передаваемые в страницы."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass
class AppContext:
    df: pd.DataFrame            # вся база (после basic_clean)
    df_f: pd.DataFrame          # глобальные фильтры + глобальный период
    df_universe: pd.DataFrame   # глобальные фильтры БЕЗ периода
    cost_ref: pd.DataFrame      # справочник себестоимости
    ap: dict                    # применённые фильтры (см. core.filters)
    d_from: date
    d_to: date
    days_cnt: int
    min_d: date                 # первая дата данных
    max_d: date                 # последняя дата данных (свежесть)
    metric_col: str             # «Сумма» или «Количество»


def build_context(df: pd.DataFrame, ap: dict, cost_ref: pd.DataFrame) -> AppContext:
    d_from, d_to = ap["date_range"]

    df_f = df[(df["Дата"] >= pd.Timestamp(d_from)) & (df["Дата"] <= pd.Timestamp(d_to))]
    df_universe = df
    for key, col in [("branches", "Филиал"), ("points", "Точки"),
                     ("groups", "Группа"), ("categories", "Категория"),
                     ("subcategories", "Подкатегория"), ("items", "Номенклатура")]:
        vals = ap.get(key) or []
        if vals:
            df_f = df_f[df_f[col].isin(vals)]
            df_universe = df_universe[df_universe[col].isin(vals)]

    return AppContext(
        df=df,
        df_f=df_f.copy(),
        df_universe=df_universe.copy(),
        cost_ref=cost_ref,
        ap=ap,
        d_from=d_from,
        d_to=d_to,
        days_cnt=max((d_to - d_from).days + 1, 1),
        min_d=df["Дата"].min().date(),
        max_d=df["Дата"].max().date(),
        metric_col="Сумма" if ap.get("abc_metric", "Сумма") == "Сумма" else "Количество",
    )
