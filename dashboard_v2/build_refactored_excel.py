"""
Разовый скрипт: читает ./Итоговый_отчет1.xlsx (оригинал с VLOOKUP'ами)
и генерит dashboard_v2/docs/Итоговый_отчет1.xlsx — «плоскую» копию
с уже рассчитанными значениями (Точки, Категория, Подкатегория, Группа).

Зачем отдельно от оригинала:
  - В оригинале нужны формулы, чтобы ты мог добавлять новые данные из 1С
    и VLOOKUP'ы протягивались. Это твой рабочий файл.
  - В docs/ нужна «самодостаточная» копия: pandas + openpyxl не умеют
    пересчитывать формулы на лету, поэтому мы пишем их результаты как значения.

Что делает скрипт:
  Лист1:
    - «Под категория» → «Подкатегория»
    - Нормализация подкатегорий (Капучинно → Капучино, и т.п.)
    - Новая колонка «Группа» (8 верхнеуровневых групп)
  база:
    - Строим lookup-мапы по Номенклатуре (Точки/Категория/Подкатегория из Лист1)
    - Заполняем пустые Точки/Категорию/Подкатегорию из lookup
    - Нормализуем Подкатегорию
    - Добавляем Группу
    - Сохраняем всё значениями (формул нет)

Запуск:
    python dashboard_v2/build_refactored_excel.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import openpyxl
from openpyxl.styles import Font

sys.path.insert(0, str(Path(__file__).parent))
from category_mapping import (
    normalize_subcategory, category_to_group, CATEGORY_TO_GROUP,
)

SRC  = Path(__file__).parent.parent / "Итоговый_отчет1.xlsx"
# /docs/ на корне репо (требование GitHub Pages)
DEST = Path(__file__).parent.parent / "docs" / "Итоговый_отчет1.xlsx"


def main() -> None:
    t0 = time.time()

    # ------------------------------------------------------------------
    # 1. Читаем оба листа через pandas (только значения)
    # ------------------------------------------------------------------
    print(f"Чтение {SRC} ...")
    t = time.time()
    ref = pd.read_excel(str(SRC), sheet_name="Лист1", engine="openpyxl")
    ref.columns = [str(c).strip() for c in ref.columns]
    # Переименовываем "Под категория" → "Подкатегория"
    ref = ref.rename(columns={"Под категория": "Подкатегория"})
    print(f"  Лист1: {len(ref)} строк за {time.time()-t:.1f} с")

    t = time.time()
    data = pd.read_excel(str(SRC), sheet_name="база", engine="openpyxl")
    data.columns = [str(c).strip() for c in data.columns]
    print(f"  база: {len(data)} строк за {time.time()-t:.1f} с")

    # ------------------------------------------------------------------
    # 2. Чистим Лист1 + добавляем Группу
    # ------------------------------------------------------------------
    print("\nЛист1: нормализация подкатегорий и расчёт группы ...")
    ref["Номенклатура"] = ref["Номенклатура"].astype("string").str.strip()
    ref["Точки"]        = ref["Точки"].astype("string").str.strip()
    ref["Категория"]    = ref["Категория"].astype("string").str.strip()
    ref["Подкатегория"] = ref["Подкатегория"].apply(normalize_subcategory)
    ref["Группа"]       = ref["Категория"].apply(category_to_group)

    unknown = set(ref.loc[~ref["Категория"].isin(CATEGORY_TO_GROUP.keys()), "Категория"].dropna().unique())
    if unknown:
        print(f"  ⚠️ Категории не найдены в маппинге → попадут в 'Дополнения и прочее': {sorted(unknown)}")

    # ------------------------------------------------------------------
    # 3. Строим lookup-мапы и заполняем базу
    # ------------------------------------------------------------------
    print("\nбаза: досчитываем Точки/Категорию/Подкатегорию/Группу ...")
    data["Номенклатура"] = data["Номенклатура"].astype("string").str.strip()

    map_tochki = dict(zip(ref["Номенклатура"], ref["Точки"]))
    map_cat    = dict(zip(ref["Номенклатура"], ref["Категория"]))
    map_sub    = dict(zip(ref["Номенклатура"], ref["Подкатегория"]))
    map_group  = dict(zip(ref["Номенклатура"], ref["Группа"]))

    # Точки: если пусто или NaN — берём из справочника
    tochki_mapped = data["Номенклатура"].map(map_tochki)
    data["Точки"] = data["Точки"].astype("string").str.strip() if "Точки" in data.columns else pd.Series(pd.NA, index=data.index)
    data["Точки"] = data["Точки"].where(data["Точки"].notna() & (data["Точки"] != ""), tochki_mapped)

    # Категория: нормализуем строку, пустое → lookup
    data["Категория"] = data["Категория"].astype("string").str.strip() if "Категория" in data.columns else pd.Series(pd.NA, index=data.index)
    cat_mapped = data["Номенклатура"].map(map_cat)
    data["Категория"] = data["Категория"].where(data["Категория"].notna() & (data["Категория"] != ""), cat_mapped)

    # Подкатегория: normalize + fallback к lookup
    sub_mapped = data["Номенклатура"].map(map_sub)
    data["Подкатегория"] = data["Подкатегория"].apply(normalize_subcategory) \
        if "Подкатегория" in data.columns else sub_mapped
    # где после normalize стоит "Без подкатегории" — берём из справочника, если там что-то содержательное
    need_fill = data["Подкатегория"].isin(["Без подкатегории"]) & sub_mapped.notna() & (sub_mapped != "Без подкатегории")
    data.loc[need_fill, "Подкатегория"] = sub_mapped[need_fill]

    # Группа: сначала прямой lookup по SKU, потом fallback — по Категории
    data["Группа"] = data["Номенклатура"].map(map_group)
    missing_group = data["Группа"].isna()
    if missing_group.any():
        data.loc[missing_group, "Группа"] = data.loc[missing_group, "Категория"].apply(category_to_group)

    # ------------------------------------------------------------------
    # 4. Итоговый порядок колонок
    # ------------------------------------------------------------------
    cols_order = ["Точки","Номенклатура","Склад/Товар","Количество","Цена","Сумма",
                  "Дата","Время","Месяц","Год","Филиал","Категория","Подкатегория","Группа"]
    cols_order = [c for c in cols_order if c in data.columns]
    data = data[cols_order]

    print("\nСтатистика:")
    print(f"  строк в базе: {len(data)}")
    print(f"  пропусков по колонкам (после досчёта):")
    for c in ["Точки","Категория","Подкатегория","Группа"]:
        if c in data.columns:
            print(f"    {c}: {int(data[c].isna().sum())}")
    print(f"  распределение по группам:")
    for grp, cnt in data["Группа"].value_counts(dropna=False).items():
        print(f"    {grp}: {cnt}")

    # ------------------------------------------------------------------
    # 5. Пишем плоский xlsx (только значения)
    # ------------------------------------------------------------------
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nСохранение -> {DEST} ...")
    t = time.time()
    with pd.ExcelWriter(str(DEST), engine="openpyxl") as xw:
        ref[["Номенклатура","Точки","Категория","Подкатегория","Группа"]].to_excel(
            xw, sheet_name="Лист1", index=False
        )
        data.to_excel(xw, sheet_name="база", index=False)

    size_mb = DEST.stat().st_size / 1024 / 1024
    print(f"  сохранено за {time.time()-t:.1f} с, размер {size_mb:.1f} МБ")
    print(f"\n✅ Всего: {time.time()-t0:.1f} с")


if __name__ == "__main__":
    main()
