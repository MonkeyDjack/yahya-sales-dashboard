"""Загрузка данных. Единственный источник — GitHub Pages (fallback на локальные
файлы в docs/ для офлайн-разработки)."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from category_mapping import apply_mapping
from core.config import GH_PAGES_PARQUET, GH_PAGES_COST, GH_PAGES_BOM, BOM_NAME, SEASONAL_KEYWORDS

_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


def _fetch_parquet(url: str, local_name: str) -> pd.DataFrame:
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        return pd.read_parquet(io.BytesIO(r.content), engine="pyarrow")
    except Exception:
        local = _DOCS_DIR / local_name
        if local.exists():
            return pd.read_parquet(local)
        raise


def basic_clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "Дата" in df.columns:
        dt = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=True)
        df["Дата"] = dt.dt.normalize()
        df = df[df["Дата"].notna()]
    for col in ["Количество", "Сумма", "Цена"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["Филиал", "Точки", "Номенклатура", "Категория",
                "Подкатегория", "Группа", "Время"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    # страховка: если Группа отсутствует или пустая — досчитаем в памяти
    df = apply_mapping(df)
    return df


@st.cache_data(ttl=3600, show_spinner="Загрузка базы продаж…")
def load_sales() -> pd.DataFrame:
    return basic_clean(_fetch_parquet(GH_PAGES_PARQUET, "база.parquet"))


@st.cache_data(ttl=3600, show_spinner="Загрузка справочника себестоимости…")
def load_cost_reference() -> pd.DataFrame:
    try:
        return _fetch_parquet(GH_PAGES_COST, "себестоимость.parquet")
    except Exception:
        return pd.DataFrame(columns=["Номенклатура", "Себес сырья", "ПНР",
                                     "Себес полн.", "Розница", "Сегмент"])


@st.cache_data(ttl=3600, show_spinner=False)
def load_bom() -> pd.DataFrame:
    """BOM наборов (без сезонных)."""
    for src_fn in [
        lambda: requests.get(GH_PAGES_BOM, timeout=60).content,
        lambda: (_DOCS_DIR / BOM_NAME).read_bytes(),
    ]:
        try:
            df_bom = pd.read_excel(io.BytesIO(src_fn()))
            df_bom.columns = ["Набор", "Компонент", "Кол"]
            df_bom["Набор"]     = df_bom["Набор"].astype(str).str.strip()
            df_bom["Компонент"] = df_bom["Компонент"].astype(str).str.strip()
            df_bom["Кол"]       = pd.to_numeric(df_bom["Кол"], errors="coerce").fillna(0)
            df_bom = df_bom[~df_bom["Набор"].str.lower().apply(
                lambda n: any(k in n for k in SEASONAL_KEYWORDS))].reset_index(drop=True)
            return df_bom
        except Exception:
            continue
    return pd.DataFrame(columns=["Набор", "Компонент", "Кол"])


def clear_caches() -> None:
    st.cache_data.clear()


def validate_minimum(df: pd.DataFrame) -> None:
    required = ["Филиал", "Точки", "Номенклатура", "Количество", "Сумма", "Дата"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"В данных не хватает колонок: {missing}")
        st.stop()
    if df["Дата"].isna().all():
        st.error("Не удалось распознать ни одной даты.")
        st.stop()
