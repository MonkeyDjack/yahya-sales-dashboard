"""
Аппенд июня 2026 в docs/база.parquet из «D:/Итоговый_отчет (6).xlsx».

В файле: 7 филиалов, дни 1–10 июня 2026, колонки уже канонические
(Склад/Товар присутствует). Заменяем ВЕСЬ июнь 2026 в parquet —
повторный запуск с более полным файлом месяца безопасен.

Категория / Подкатегория / Группа — лукап из list1.parquet.
После аппенда прогнать: python dashboard_v2/fix_categories.py

Запуск: python dashboard_v2/append_june_2026.py
"""
from __future__ import annotations
import sys
import shutil
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from category_mapping import normalize_subcategory, category_to_group

ROOT     = Path(__file__).parent.parent
SRC_XLSX = Path(r"D:/Итоговый_отчет (6).xlsx")
PARQUET  = ROOT / "docs" / "база.parquet"
REF_PQ   = ROOT / "docs" / "list1.parquet"
BACKUP   = ROOT / "docs" / "база.parquet.bak_before_june2026"

MONTH_RU = "Июнь"
YEAR     = 2026
MONTH_NO = 6

FILIAL_ALIASES = {
    "АЗИЯ_МОЛЛ": "АЗИЯ МОЛЛ",
    "БП": "Бишкек Парк",
}


def main() -> None:
    print(f"Чтение {SRC_XLSX} ...")
    new = pd.read_excel(str(SRC_XLSX), sheet_name="Sheet1", engine="openpyxl")
    new.columns = [str(c).strip() for c in new.columns]

    if "Регистратор" in new.columns and "Склад/Товар" not in new.columns:
        new = new.rename(columns={"Регистратор": "Склад/Товар"})

    new["Филиал"] = new["Филиал"].astype("string").str.strip().replace(FILIAL_ALIASES)
    print(f"  новых строк: {len(new)}")
    print(f"  филиалы: {sorted(new['Филиал'].dropna().unique())}")
    d = pd.to_datetime(new["Дата"], dayfirst=True, errors="coerce")
    if d.isna().any():
        print(f"  ⚠️ строк с нечитаемой датой: {int(d.isna().sum())}")
    wrong_month = (d.dt.year != YEAR) | (d.dt.month != MONTH_NO)
    if wrong_month.any():
        print(f"  ⚠️ строк вне {MONTH_RU} {YEAR}: {int(wrong_month.sum())} — отбрасываю")
        new = new.loc[~wrong_month].copy()
        d = d.loc[~wrong_month]
    print(f"  дни: {sorted(d.dt.day.dropna().unique().astype(int))}")

    new["Номенклатура"] = new["Номенклатура"].astype("string").str.strip()
    new["Дата"]  = d.dt.strftime("%d.%m.%Y")
    new["Время"] = new["Время"].astype(str)
    new["Месяц"] = MONTH_RU
    new["Год"]   = YEAR

    new["Точки"] = new["Точки"].astype("string").str.strip()
    bad_case = new["Точки"].str.lower().isin(["магазин", "бар", "кухня"]) & \
               ~new["Точки"].isin(["Магазин", "Бар", "Кухня"])
    if bad_case.any():
        print(f"  нормализация регистра Точки: {int(bad_case.sum())} строк")
        new.loc[bad_case, "Точки"] = new.loc[bad_case, "Точки"].str.capitalize()

    # Лукапы из справочника
    ref = pd.read_parquet(str(REF_PQ))
    ref["Номенклатура"] = ref["Номенклатура"].astype("string").str.strip()
    map_tochki = dict(zip(ref["Номенклатура"], ref["Точки"]))
    map_cat    = dict(zip(ref["Номенклатура"], ref["Категория"]))
    map_sub    = dict(zip(ref["Номенклатура"], ref["Подкатегория"]))
    map_group  = dict(zip(ref["Номенклатура"], ref["Группа"]))

    nan_tochki = new["Точки"].isna() | (new["Точки"] == "")
    if nan_tochki.any():
        filled = new.loc[nan_tochki, "Номенклатура"].map(map_tochki)
        new.loc[nan_tochki, "Точки"] = filled.values
        print(f"  Точки подтянуто из list1: {filled.notna().sum()} / {int(nan_tochki.sum())}")

    bad = set(new["Точки"].dropna().unique()) - {"Магазин", "Бар", "Кухня"}
    if bad:
        print(f"  ⚠️ нестандартные Точки: {bad}")

    new["Категория"]    = new["Номенклатура"].map(map_cat)
    new["Подкатегория"] = new["Номенклатура"].map(map_sub).apply(normalize_subcategory)
    new["Группа"]       = new["Номенклатура"].map(map_group)
    miss_g = new["Группа"].isna()
    if miss_g.any():
        new.loc[miss_g, "Группа"] = new.loc[miss_g, "Категория"].apply(category_to_group)

    unk = new.loc[new["Категория"].isna(), "Номенклатура"].dropna().unique()
    if len(unk):
        print(f"  ⚠️ SKU без категории (нет в list1): {len(unk)}")
        for s in unk[:15]:
            print(f"     - {s}")

    # parquet — удалить весь июнь 2026 и записать новый
    print(f"\nЧтение {PARQUET} ...")
    base = pd.read_parquet(str(PARQUET))
    n_before = len(base)
    base_dates = pd.to_datetime(base["Дата"], format="%d.%m.%Y", errors="coerce")
    month_mask = ((base["Год"] == YEAR) & (base["Месяц"] == MONTH_RU)) \
               | ((base_dates.dt.year == YEAR) & (base_dates.dt.month == MONTH_NO))
    n_remove = int(month_mask.sum())
    print(f"  всего строк до изменений: {n_before}")
    print(f"  удаляем старых строк {MONTH_RU.lower()}я {YEAR}: {n_remove}")
    base = base.loc[~month_mask].copy()

    cols = list(base.columns)
    for c in cols:
        if c not in new.columns:
            new[c] = pd.NA
    new = new[cols]

    new["Точки"]        = new["Точки"].astype("string")
    new["Номенклатура"] = new["Номенклатура"].astype("string")
    new["Категория"]    = new["Категория"].astype("string")
    new["Год"]          = new["Год"].astype("int64")
    for c in ["Количество", "Цена", "Сумма"]:
        new[c] = pd.to_numeric(new[c], errors="coerce").astype("float64")

    merged = pd.concat([base, new], ignore_index=True)
    print(f"\nИтого после слияния: {len(merged)} ({len(merged) - n_before:+d})")

    m = merged[(merged["Год"] == YEAR) & (merged["Месяц"] == MONTH_RU)]
    print(f"\nКонтроль {MONTH_RU.lower()}я {YEAR}:")
    print(f"  строк:  {len(m)}")
    print(f"  сумма:  {m['Сумма'].sum():,.0f}")
    print(f"  Точки:  {dict(m['Точки'].value_counts())}")
    for b in sorted(m["Филиал"].unique()):
        sub = m[m["Филиал"] == b]
        days = sub["Дата"].nunique()
        s = sub["Сумма"].sum()
        print(f"    {b:12} {days:>2} дн., {s:>14,.0f} сом")

    if not BACKUP.exists():
        print(f"\nБэкап -> {BACKUP.name} ...")
        shutil.copy2(str(PARQUET), str(BACKUP))

    print(f"\nСохранение -> {PARQUET} ...")
    merged.to_parquet(str(PARQUET), engine="pyarrow", compression="snappy", index=False)
    print(f"  размер: {PARQUET.stat().st_size/1024/1024:.2f} МБ")
    print("✅ Готово. Теперь: python dashboard_v2/fix_categories.py")


if __name__ == "__main__":
    main()
