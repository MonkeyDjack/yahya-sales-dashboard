"""События филиалов (открытия, простои) и like-for-like логика сравнений."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class BranchEvent:
    opened: date | None = None                          # дата полноценного старта
    closed_ranges: tuple[tuple[date, date], ...] = ()   # окна простоя (вкл. границы)


# Начало данных в базе — филиалы без opened считаются работающими с этой даты
DATA_START = date(2025, 1, 1)

BRANCH_EVENTS: dict[str, BranchEvent] = {
    "ЭРКИНДИК":  BranchEvent(opened=date(2025, 1, 2)),
    "АЗБУКА":    BranchEvent(opened=date(2026, 1, 1)),
    "NGROUP":    BranchEvent(opened=date(2026, 1, 2)),
    # реконструкция 08.02–01.03.2026 (22 дня)
    "АЗИЯ МОЛЛ": BranchEvent(closed_ranges=((date(2026, 2, 8), date(2026, 3, 1)),)),
}


def _overlap_days(a_from: date, a_to: date, b_from: date, b_to: date) -> int:
    lo = max(a_from, b_from)
    hi = min(a_to, b_to)
    return max((hi - lo).days + 1, 0)


def branch_coverage(branch: str, p_from: date, p_to: date) -> float:
    """Доля дней периода, когда филиал полноценно работал, 0..1."""
    total = (p_to - p_from).days + 1
    if total <= 0:
        return 0.0
    ev = BRANCH_EVENTS.get(branch, BranchEvent())
    opened = ev.opened or DATA_START
    # дни до открытия — не работал
    working_from = max(p_from, opened)
    if working_from > p_to:
        return 0.0
    working = (p_to - working_from).days + 1
    for c_from, c_to in ev.closed_ranges:
        working -= _overlap_days(working_from, p_to, c_from, c_to)
    return max(working, 0) / total


def _reason(branch: str, p_from: date, p_to: date) -> str:
    ev = BRANCH_EVENTS.get(branch, BranchEvent())
    opened = ev.opened or DATA_START
    if opened > p_from:
        return f"открыт {opened:%d.%m.%Y}"
    for c_from, c_to in ev.closed_ranges:
        if _overlap_days(p_from, p_to, c_from, c_to) > 0:
            days = (c_to - c_from).days + 1
            return f"закрыт {c_from:%d.%m}–{c_to:%d.%m.%Y} ({days} дн.)"
    return "неполный период"


def lfl_split(branches: list[str],
              period1: tuple[date, date], period2: tuple[date, date],
              min_coverage: float = 0.95) -> tuple[list[str], dict[str, str]]:
    """Делит филиалы на сопоставимые и исключённые.

    Филиал включается, только если работал ≥ min_coverage дней
    в ОБОИХ периодах. Возвращает (включённые, {филиал: причина}).
    """
    included: list[str] = []
    excluded: dict[str, str] = {}
    for br in branches:
        cov1 = branch_coverage(br, *period1)
        cov2 = branch_coverage(br, *period2)
        if cov1 >= min_coverage and cov2 >= min_coverage:
            included.append(br)
        else:
            bad = period1 if cov1 < min_coverage else period2
            excluded[br] = _reason(br, *bad)
    return included, excluded


def lfl_caption(excluded: dict[str, str]) -> str:
    if not excluded:
        return "LFL: все выбранные филиалы сопоставимы в обоих периодах."
    parts = [f"{br} ({reason})" for br, reason in excluded.items()]
    return "LFL: исключены " + ", ".join(parts)


def closures_in(branches: list[str], p_from: date, p_to: date) -> dict[str, str]:
    """Филиалы из списка, у которых в период попало окно простоя или открытие."""
    out: dict[str, str] = {}
    for br in branches:
        if branch_coverage(br, p_from, p_to) < 1.0:
            out[br] = _reason(br, p_from, p_to)
    return out
