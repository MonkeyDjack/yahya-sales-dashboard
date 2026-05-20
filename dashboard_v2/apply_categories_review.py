"""Применяет правки категорий из reports/categories_review.xlsx к docs/база.parquet.

Шаги:
  1. Читает xlsx (юзер правил Группа/Категория/Подкатегория)
  2. Сравнивает с текущей канонической (Г, К, П) на SKU в parquet
  3. Показывает diff: сколько SKU изменилось и в чём
  4. Бэкапит parquet (.bak_before_manual_review)
  5. Применяет: для каждого SKU обновляет ВСЕ его строки в parquet
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "docs" / "база.parquet"
XLSX = ROOT / "reports" / "categories_review.xlsx"
BACKUP = ROOT / "docs" / "база.parquet.bak_before_manual_review"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"Читаю xlsx: {XLSX}")
    rev = pd.read_excel(XLSX, sheet_name="Категории")
    rev = rev[["Номенклатура", "Группа", "Категория", "Подкатегория"]].copy()
    rev["Номенклатура"] = rev["Номенклатура"].astype(str).str.strip()
    for c in ["Группа", "Категория", "Подкатегория"]:
        rev[c] = rev[c].astype(str).str.strip().replace({"nan": "", "": pd.NA})
    print(f"  SKU в файле: {len(rev)}")

    print(f"\nЧитаю parquet: {PARQUET}")
    pq = pd.read_parquet(PARQUET)
    print(f"  строк: {len(pq):,}, SKU: {pq['Номенклатура'].nunique()}")

    # Текущая канонические значения на SKU
    cur = (pq.groupby(["Номенклатура", "Группа", "Категория", "Подкатегория"])
              .size().reset_index(name="n"))
    cur = (cur.sort_values(["Номенклатура", "n"], ascending=[True, False])
              .drop_duplicates("Номенклатура")
              .drop(columns="n"))
    cur.columns = ["Номенклатура", "Группа_old", "Категория_old", "Подкатегория_old"]

    # Сверка
    cmp = rev.merge(cur, on="Номенклатура", how="left")
    missing_in_pq = cmp[cmp["Группа_old"].isna() & cmp["Категория_old"].isna()]
    if not missing_in_pq.empty:
        print(f"\n⚠️ {len(missing_in_pq)} SKU из xlsx не найдено в parquet — пропускаю эти.")
        cmp = cmp[~cmp["Номенклатура"].isin(missing_in_pq["Номенклатура"])]

    def _safe(s):
        return "" if pd.isna(s) else str(s).strip()

    diffs = []
    for _, r in cmp.iterrows():
        g_new, k_new, p_new = _safe(r["Группа"]), _safe(r["Категория"]), _safe(r["Подкатегория"])
        g_old, k_old, p_old = _safe(r["Группа_old"]), _safe(r["Категория_old"]), _safe(r["Подкатегория_old"])
        if (g_new, k_new, p_new) != (g_old, k_old, p_old):
            diffs.append({
                "Номенклатура": r["Номенклатура"],
                "Группа": (g_old, g_new),
                "Категория": (k_old, k_new),
                "Подкатегория": (p_old, p_new),
            })

    print(f"\nИзменено SKU: {len(diffs)} из {len(cmp)}")
    if not diffs:
        print("Нет изменений. Выхожу.")
        return

    # Разбивка по типу правки
    chg_grp = sum(1 for d in diffs if d["Группа"][0] != d["Группа"][1])
    chg_cat = sum(1 for d in diffs if d["Категория"][0] != d["Категория"][1])
    chg_sub = sum(1 for d in diffs if d["Подкатегория"][0] != d["Подкатегория"][1])
    print(f"  Группа: {chg_grp}, Категория: {chg_cat}, Подкатегория: {chg_sub}")

    # Покажем первые 30 изменений
    print("\nПервые 30 изменений:")
    for d in diffs[:30]:
        chg_parts = []
        for field in ("Группа", "Категория", "Подкатегория"):
            old, new = d[field]
            if old != new:
                chg_parts.append(f"{field}: {old!r} → {new!r}")
        print(f"  • {d['Номенклатура']}")
        for cp in chg_parts:
            print(f"      {cp}")

    # Бэкап
    if not BACKUP.exists():
        print(f"\nБэкап: {BACKUP.name}")
        shutil.copy2(PARQUET, BACKUP)
    else:
        print(f"\nБэкап уже существует: {BACKUP.name} (пропускаю)")

    # Применение
    chg_map = {d["Номенклатура"]: (d["Группа"][1], d["Категория"][1], d["Подкатегория"][1])
                  for d in diffs}
    g_new = pq["Номенклатура"].map(lambda s: chg_map.get(s, (None, None, None))[0])
    k_new = pq["Номенклатура"].map(lambda s: chg_map.get(s, (None, None, None))[1])
    p_new = pq["Номенклатура"].map(lambda s: chg_map.get(s, (None, None, None))[2])

    affected = pq["Номенклатура"].isin(chg_map)
    pq.loc[affected & g_new.notna(), "Группа"]       = g_new[affected & g_new.notna()]
    pq.loc[affected & k_new.notna(), "Категория"]    = k_new[affected & k_new.notna()]
    pq.loc[affected & p_new.notna(), "Подкатегория"] = p_new[affected & p_new.notna()]

    affected_rows = int(affected.sum())
    print(f"\nЗатронуто строк parquet: {affected_rows:,}")

    pq.to_parquet(PARQUET, engine="pyarrow", compression="snappy", index=False)
    print(f"Сохранено: {PARQUET}")


if __name__ == "__main__":
    main()
