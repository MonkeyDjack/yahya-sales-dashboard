"""Константы приложения: источники данных, цвета, пороги ABC."""
from __future__ import annotations

from urllib.parse import quote

GH_USER = "MonkeyDjack"
GH_REPO = "yahya-sales-dashboard"
BOM_NAME = "разбивка_наборов.xlsx"

_PAGES_BASE = f"https://{GH_USER.lower()}.github.io/{GH_REPO}"
GH_PAGES_PARQUET = f"{_PAGES_BASE}/{quote('база.parquet')}"
GH_PAGES_COST    = f"{_PAGES_BASE}/{quote('себестоимость.parquet')}"
GH_PAGES_BOM     = f"{_PAGES_BASE}/{quote(BOM_NAME)}"

# Колонка с идентификатором чека
CHECKS_COL = "Склад/Товар"

# Пороги ABC (кумулятивная доля)
A_THR, B_THR = 0.80, 0.95

COLORS = {
    "primary": "#1F4E79",
    "accent":  "#E67E22",
    "danger":  "#C0392B",
    "ok":      "#27AE60",
    "violet":  "#8E44AD",
    "teal":    "#16A085",
}

# Наборы, исключаемые из BOM как сезонные
SEASONAL_KEYWORDS = ['23 февраля', '14 февраля', '8 марта', '1 сентября',
                     'рамадан', 'новый год', 'пасх', 'наурыз', 'весна']

# url_path страниц, у которых СВОЙ выбор периода (глобальный период не применяется)
OWN_PERIOD_PAGES = {"abc", "dynamics", "plan-fact"}
