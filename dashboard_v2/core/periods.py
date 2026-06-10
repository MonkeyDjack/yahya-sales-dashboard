"""Периоды: дефолт, пресеты, сравнения с нормализацией на день и LFL."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from core.events import lfl_split
from core.helpers import count_checks, margin_by_sku, safe_div

# Порядок важен — так пресеты рендерятся в sidebar
PRESETS = ["7 дней", "30 дней", "Тек. месяц", "Прош. месяц",
           "Квартал", "YTD", "12 мес", "Вся история"]


def default_period(max_data_date: date, days: int = 30) -> tuple[date, date]:
    """Последние N дней ДАННЫХ (не календаря)."""
    return (max_data_date - timedelta(days=days - 1), max_data_date)


def preset_range(preset: str, min_d: date, max_d: date) -> tuple[date, date]:
    """Все пресеты отсчитываются от даты свежести данных max_d."""
    if preset == "7 дней":
        f = max_d - timedelta(days=6)
    elif preset == "30 дней":
        f = max_d - timedelta(days=29)
    elif preset == "Тек. месяц":
        f = max_d.replace(day=1)
    elif preset == "Прош. месяц":
        first_cur = max_d.replace(day=1)
        last_prev = first_cur - timedelta(days=1)
        return (max(last_prev.replace(day=1), min_d), last_prev)
    elif preset == "Квартал":
        qm = ((max_d.month - 1) // 3) * 3 + 1
        f = max_d.replace(month=qm, day=1)
    elif preset == "YTD":
        f = max_d.replace(month=1, day=1)
    elif preset == "12 мес":
        f = max_d - timedelta(days=364)
    else:  # Вся история
        f = min_d
    return (max(f, min_d), max_d)


def prev_period(d_from: date, d_to: date) -> tuple[date, date]:
    """Смежный предыдущий период той же длины."""
    n = (d_to - d_from).days + 1
    return (d_from - timedelta(days=n), d_to - timedelta(days=n))


def yoy_period(d_from: date, d_to: date) -> tuple[date, date]:
    """−364 дня (52 недели): сохраняет день недели — корректнее для розницы."""
    return (d_from - timedelta(days=364), d_to - timedelta(days=364))


@dataclass
class CompareResult:
    cur: dict = field(default_factory=dict)        # абсолюты текущего периода
    ref: dict = field(default_factory=dict)        # абсолюты базового периода
    cur_per_day: dict = field(default_factory=dict)
    ref_per_day: dict = field(default_factory=dict)
    delta_pct: dict = field(default_factory=dict)  # Δ% по /день величинам
    lfl_included: list = field(default_factory=list)
    lfl_excluded: dict = field(default_factory=dict)
    cur_days: int = 0
    ref_days: int = 0


def _slice(df: pd.DataFrame, p: tuple[date, date], branches: list[str]) -> pd.DataFrame:
    f = df[(df["Дата"] >= pd.Timestamp(p[0])) & (df["Дата"] <= pd.Timestamp(p[1]))]
    return f[f["Филиал"].isin(branches)]


def _metrics(frame: pd.DataFrame, cost_ref: pd.DataFrame | None) -> dict:
    rev = float(frame["Сумма"].sum()) if not frame.empty else 0.0
    qty = float(frame["Количество"].sum()) if not frame.empty else 0.0
    checks = count_checks(frame)
    out = {
        "Выручка": rev,
        "Количество": qty,
        "Чеков": checks,
        "Средний чек": safe_div(rev, checks),
    }
    if cost_ref is not None and not cost_ref.empty and not frame.empty:
        out["Маржа"] = float(margin_by_sku(frame, cost_ref)["Маржа"].sum())
    return out


def compare_kpis(df_universe: pd.DataFrame,
                 cur: tuple[date, date], ref: tuple[date, date],
                 branches: list[str], lfl: bool,
                 cost_ref: pd.DataFrame | None = None) -> CompareResult:
    """KPI двух периодов. Δ% считается ПО per-day величинам, чтобы
    неравные периоды сравнивались честно. При lfl=True оба периода
    режутся до филиалов, сопоставимых в обоих окнах."""
    res = CompareResult()
    res.cur_days = (cur[1] - cur[0]).days + 1
    res.ref_days = (ref[1] - ref[0]).days + 1

    if lfl:
        res.lfl_included, res.lfl_excluded = lfl_split(branches, cur, ref)
    else:
        res.lfl_included, res.lfl_excluded = list(branches), {}

    use_branches = res.lfl_included if res.lfl_included else list(branches)
    f_cur = _slice(df_universe, cur, use_branches)
    f_ref = _slice(df_universe, ref, use_branches)

    res.cur = _metrics(f_cur, cost_ref)
    res.ref = _metrics(f_ref, cost_ref)

    per_day_keys = {"Выручка", "Количество", "Чеков", "Маржа"}
    for k, v in res.cur.items():
        res.cur_per_day[k] = v / res.cur_days if k in per_day_keys else v
    for k, v in res.ref.items():
        res.ref_per_day[k] = v / res.ref_days if k in per_day_keys else v
    for k in res.cur:
        c, r = res.cur_per_day.get(k, 0), res.ref_per_day.get(k, 0)
        res.delta_pct[k] = (c - r) / r * 100 if r else None
    return res
