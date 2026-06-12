"""Однократный фикс категорий в docs/база.parquet.

Что делает:
  1. Для каждого SKU определяет КАНОНИЧЕСКУЮ пару (Категория, Подкатегория) —
     самую частую комбинацию в его строках. Это автоматически отбрасывает
     fallback-шум «Конфеты / Корпусные конфеты», который был проставлен части
     строк ошибочно.
  2. Перезаписывает Категория и Подкатегория во ВСЕХ строках SKU на каноническую.
  3. Пересчитывает Группа через category_mapping.category_to_group(Категория).
  4. Доп. override: «Нац.коллекция - соленая карамель и талкан на 15к» сейчас
     канонично попадает в Плитки/Нац. плитки — это рассинхрон с остальными 5
     Нац.коллекциями, исправляю на Наборы/Нац. конфеты.
  5. Бэкапит исходный parquet в docs/база.parquet.bak_before_category_fix.

Запуск:
    python dashboard_v2/fix_categories.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard_v2"))
from category_mapping import category_to_group  # noqa: E402

PARQUET = ROOT / "docs" / "база.parquet"
BACKUP = ROOT / "docs" / "база.parquet.bak_before_category_fix"

# Ручные переопределения для SKU, у которых канон неверный
MANUAL_OVERRIDES: dict[str, tuple[str, str]] = {
    "Нац.коллекция - соленая карамель и талкан на 15к": ("Наборы", "Нац. конфеты"),
    # Драже Клубника в БШ — относится к классическому драже (как остальные)
    "Драже Клубника в БШ 100г": ("Драже", "Драже классика"),
    # Новинки драже (май 2026) — пришли из 1С с «Без подкатегории»;
    # мода по истории их не вылечит, поэтому канон задаём явно
    "Драже Кешью в МШ 90г": ("Драже", "Драже классика"),
    "Драже Клубника в МШ 80г.": ("Драже", "Драже классика"),
    "Драже Фундук в МШ 90г": ("Драже", "Драже классика"),
    "Драже Нуга  в темном шоколаде": ("Драже", "Драже классика"),  # двойной пробел — так в 1С
    # 1С прислал категорию в другом регистре («Коробки сборные») — канон с заглавной
    "Коробка золото Новогодний бокс": ("Коробки Сборные", "Коробки Сборные"),
}

# Подкатегория = Категория, если канон уйдёт в «Без подкатегории» (читаемее в отчётах)
SUBCATEGORY_FALLBACK_FROM_CATEGORY = True


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    if not PARQUET.exists():
        print(f"❌ Не нашёл {PARQUET}")
        sys.exit(1)

    print(f"Читаю {PARQUET}…")
    df = pd.read_parquet(PARQUET)
    n_total = len(df)
    print(f"  строк: {n_total:,}, SKU: {df['Номенклатура'].nunique()}")

    # --- 1. Канонические пары (Категория, Подкатегория) по моде ---
    combos = (df.groupby(["Номенклатура", "Категория", "Подкатегория"])
                .size().reset_index(name="n"))
    canon = (combos.sort_values(["Номенклатура", "n"], ascending=[True, False])
                    .drop_duplicates("Номенклатура")
                    .set_index("Номенклатура")[["Категория", "Подкатегория"]])

    # Применяем ручные оверрайды
    for sku, (cat, sub) in MANUAL_OVERRIDES.items():
        if sku in canon.index:
            old = tuple(canon.loc[sku])
            canon.loc[sku] = [cat, sub]
            print(f"  override: {sku!r} {old} → ({cat!r}, {sub!r})")

    # «Без подкатегории» → Категория (по запросу: подкатегория должна быть осмысленной)
    if SUBCATEGORY_FALLBACK_FROM_CATEGORY:
        mask_empty_sub = canon["Подкатегория"].fillna("").str.strip().isin(
            ["", "Без подкатегории"]
        )
        n_fix = mask_empty_sub.sum()
        canon.loc[mask_empty_sub, "Подкатегория"] = canon.loc[mask_empty_sub, "Категория"]
        print(f"  fallback Подкатегория ← Категория: {n_fix} SKU")

    # --- 2. Перезапись строк ---
    df_new = df.copy()
    df_new["Категория"] = df_new["Номенклатура"].map(canon["Категория"])
    df_new["Подкатегория"] = df_new["Номенклатура"].map(canon["Подкатегория"])

    # --- 3. Пересчёт Группа ---
    old_group = df_new["Группа"].copy()
    df_new["Группа"] = df_new["Категория"].map(lambda c: category_to_group(c))

    # --- метрики ---
    changed_cat = (df["Категория"] != df_new["Категория"]).sum()
    changed_sub = (df["Подкатегория"] != df_new["Подкатегория"]).sum()
    changed_grp = (old_group != df_new["Группа"]).sum()
    print()
    print(f"Изменено строк:")
    print(f"  Категория:    {changed_cat:,} ({changed_cat/n_total*100:.2f}%)")
    print(f"  Подкатегория: {changed_sub:,} ({changed_sub/n_total*100:.2f}%)")
    print(f"  Группа:       {changed_grp:,} ({changed_grp/n_total*100:.2f}%)")

    # --- 4. Распределение после фикса ---
    print()
    print("Группа после фикса:")
    print(df_new["Группа"].value_counts())

    # --- 5. Бэкап + запись ---
    if not BACKUP.exists():
        print(f"\nБэкап: {BACKUP.name}")
        shutil.copy2(PARQUET, BACKUP)
    else:
        print(f"\nБэкап уже существует: {BACKUP.name} (пропускаю)")

    df_new.to_parquet(PARQUET, engine="pyarrow", compression="snappy", index=False)
    print(f"Сохранено: {PARQUET}")


if __name__ == "__main__":
    main()
