"""
Разовый скрипт: добавляет данные из апрель 26 год.xlsx в docs/база.parquet.
Заменяет частичные данные за апрель 2026 (1-3 апреля) полным месяцем.
"""
from __future__ import annotations
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from category_mapping import normalize_subcategory, category_to_group

ROOT     = Path(__file__).parent.parent
SRC_XLSX = ROOT / "апрель 26 год.xlsx"
PARQUET  = ROOT / "docs" / "база.parquet"
REF_PQ   = ROOT / "docs" / "list1.parquet"


def main() -> None:
    print(f"Чтение {SRC_XLSX} ...")
    new = pd.read_excel(str(SRC_XLSX), sheet_name="Лист1", engine="openpyxl")
    new.columns = [str(c).strip() for c in new.columns]
    print(f"  новых строк: {len(new)}")

    # Регистратор → Склад/Товар (в parquet это Чек ...)
    if "Регистратор" in new.columns and "Склад/Товар" not in new.columns:
        new = new.rename(columns={"Регистратор": "Склад/Товар"})

    new["Номенклатура"] = new["Номенклатура"].astype("string").str.strip()

    # Дата → строка dd.mm.YYYY (в parquet хранится как строка)
    if not pd.api.types.is_string_dtype(new["Дата"]):
        d = pd.to_datetime(new["Дата"], errors="coerce")
        new["Дата"] = d.dt.strftime("%d.%m.%Y")

    # Время → строка HH:MM:SS
    if not pd.api.types.is_string_dtype(new["Время"]):
        new["Время"] = new["Время"].astype(str)

    # Месяц / Год — фиксируем для апреля 2026
    new["Месяц"] = "Апрель"
    new["Год"]   = 2026

    # ---- Лукапы из list1.parquet ----
    ref = pd.read_parquet(str(REF_PQ))
    ref["Номенклатура"] = ref["Номенклатура"].astype("string").str.strip()
    map_tochki = dict(zip(ref["Номенклатура"], ref["Точки"]))
    map_cat    = dict(zip(ref["Номенклатура"], ref["Категория"]))
    map_sub    = dict(zip(ref["Номенклатура"], ref["Подкатегория"]))
    map_group  = dict(zip(ref["Номенклатура"], ref["Группа"]))

    # Точки: в новом файле всё NaN → берём из лукапа
    new_tochki = new["Номенклатура"].map(map_tochki)
    if "Точки" in new.columns:
        cur = new["Точки"].astype("string").str.strip()
        new["Точки"] = cur.where(cur.notna() & (cur != ""), new_tochki)
    else:
        new["Точки"] = new_tochki

    new["Категория"]    = new["Номенклатура"].map(map_cat)
    new["Подкатегория"] = new["Номенклатура"].map(map_sub).apply(normalize_subcategory)
    new["Группа"]       = new["Номенклатура"].map(map_group)

    miss_g = new["Группа"].isna()
    if miss_g.any():
        new.loc[miss_g, "Группа"] = new.loc[miss_g, "Категория"].apply(category_to_group)

    # Диагностика по неизвестным SKU
    unk = new.loc[new["Категория"].isna(), "Номенклатура"].dropna().unique()
    if len(unk):
        print(f"  ⚠️ {len(unk)} SKU не найдены в list1.parquet → Категория/Подкатегория = NaN, Группа = 'Дополнения и прочее':")
        for s in unk:
            print(f"     - {s}")

    # ---- Загружаем существующий паркет ----
    print(f"\nЧтение {PARQUET} ...")
    base = pd.read_parquet(str(PARQUET))
    print(f"  всего строк: {len(base)}")

    apr26_mask = (base["Год"] == 2026) & (base["Месяц"] == "Апрель")
    print(f"  существующих строк за апрель 2026: {int(apr26_mask.sum())} → удаляются")
    base = base.loc[~apr26_mask].copy()

    # ---- Приводим колонки нового DataFrame к порядку base ----
    cols = list(base.columns)
    for c in cols:
        if c not in new.columns:
            new[c] = pd.NA
    new = new[cols]

    # Касты типов под существующий parquet
    new["Точки"]        = new["Точки"].astype("string")
    new["Номенклатура"] = new["Номенклатура"].astype("string")
    new["Категория"]    = new["Категория"].astype("string")
    new["Год"]          = new["Год"].astype("int64")
    for c in ["Количество","Цена","Сумма"]:
        new[c] = pd.to_numeric(new[c], errors="coerce").astype("float64")

    merged = pd.concat([base, new], ignore_index=True)
    print(f"\nИтого после слияния: {len(merged)} строк")
    print("Распределение по Год / Месяц:")
    print(merged.groupby(['Год','Месяц']).size().sort_index().to_string())

    # ---- Пишем обратно ----
    print(f"\nСохранение -> {PARQUET} ...")
    merged.to_parquet(str(PARQUET), engine="pyarrow", compression="snappy", index=False)
    size_mb = PARQUET.stat().st_size / 1024 / 1024
    print(f"  размер: {size_mb:.2f} МБ")
    print("✅ Готово")


if __name__ == "__main__":
    main()
