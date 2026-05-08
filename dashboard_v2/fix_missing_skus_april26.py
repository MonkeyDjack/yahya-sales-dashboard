"""
Разовый скрипт: добавляет 6 SKU, отсутствующих в list1.parquet,
и обновляет соответствующие строки в база.parquet за апрель 2026.
"""
from __future__ import annotations
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

ROOT    = Path(__file__).parent.parent
PARQUET = ROOT / "docs" / "база.parquet"
REF_PQ  = ROOT / "docs" / "list1.parquet"

NEW_SKUS = [
    {"Номенклатура": "Смузи Клубника Банан 450 мл В",
     "Точки": "Бар", "Категория": "Смузи",
     "Подкатегория": "Без подкатегории", "Группа": "Напитки холодные"},
    {"Номенклатура": "Латте на миндаль молоке 350 мл В",
     "Точки": "Бар", "Категория": "Кофе",
     "Подкатегория": "Латте", "Группа": "Напитки горячие"},
    {"Номенклатура": "Флэт Уайт  200 мл  В",
     "Точки": "Бар", "Категория": "Кофе",
     "Подкатегория": "Флэт-уайт", "Группа": "Напитки горячие"},
    {"Номенклатура": "Кофе Бамбл  450 мл на свежевыжатом соке",
     "Точки": "Бар", "Категория": "Кофе",
     "Подкатегория": "Бамбл", "Группа": "Напитки горячие"},
    {"Номенклатура": "Соленая карамель-Талкан корпусная НК",
     "Точки": "Магазин", "Категория": "Конфеты",
     "Подкатегория": "Корпусные конфеты", "Группа": "Шоколад и конфеты"},
    {"Номенклатура": "Тарелка постановочная Waseela 25d",
     "Точки": "Магазин", "Категория": "Другое",
     "Подкатегория": "Без подкатегории", "Группа": "Дополнения и прочее"},
]


def main() -> None:
    # --- 1. list1.parquet ---
    print(f"Чтение {REF_PQ} ...")
    ref = pd.read_parquet(str(REF_PQ))
    print(f"  было: {len(ref)} строк")

    add = pd.DataFrame(NEW_SKUS)[ref.columns.tolist()]
    # удаляем возможные дубликаты по Номенклатуре, оставляем новые
    ref = ref[~ref["Номенклатура"].isin(add["Номенклатура"])]
    ref = pd.concat([ref, add], ignore_index=True)
    print(f"  стало: {len(ref)} строк (+{len(add)})")
    ref.to_parquet(str(REF_PQ), engine="pyarrow", compression="snappy", index=False)
    print(f"  сохранено -> {REF_PQ}")

    # --- 2. база.parquet ---
    print(f"\nЧтение {PARQUET} ...")
    base = pd.read_parquet(str(PARQUET))
    print(f"  всего строк: {len(base)}")

    target_names = [s["Номенклатура"] for s in NEW_SKUS]
    apr_mask = (base["Год"] == 2026) & (base["Месяц"] == "Апрель") & (base["Номенклатура"].isin(target_names))
    print(f"  строк за апрель 2026 для этих SKU: {int(apr_mask.sum())}")

    for s in NEW_SKUS:
        m = apr_mask & (base["Номенклатура"] == s["Номенклатура"])
        n = int(m.sum())
        if n == 0:
            print(f"   - {s['Номенклатура']}: 0 строк (пропускаем)")
            continue
        base.loc[m, "Точки"]        = s["Точки"]
        base.loc[m, "Категория"]    = s["Категория"]
        base.loc[m, "Подкатегория"] = s["Подкатегория"]
        base.loc[m, "Группа"]       = s["Группа"]
        print(f"   ✓ {s['Номенклатура']}: {n} строк → {s['Категория']} / {s['Подкатегория']} / {s['Группа']}")

    print(f"\nСохранение -> {PARQUET} ...")
    base.to_parquet(str(PARQUET), engine="pyarrow", compression="snappy", index=False)
    size_mb = PARQUET.stat().st_size / 1024 / 1024
    print(f"  размер: {size_mb:.2f} МБ")

    print("\n--- Контроль: NaN по апрелю 2026 ---")
    apr = base[(base["Год"] == 2026) & (base["Месяц"] == "Апрель")]
    for c in ["Точки", "Категория", "Подкатегория", "Группа"]:
        n = int(apr[c].isna().sum())
        print(f"  {c}: {n} NaN")

    print("\n✅ Готово")


if __name__ == "__main__":
    main()
