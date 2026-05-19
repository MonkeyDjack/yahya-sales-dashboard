"""Сборка docs/себестоимость.parquet из xlsx-прайсов.

Источники:
  - D:/claude/себес шоколад.xlsx
  - D:/claude/себес цены кухня и бар.xlsx

Логика:
  * Чистим заголовки и секции-разделители
  * Нормализуем имена (нижний регистр, ё→е, точки, скобки «(1 шт)» и т.п.)
  * Учитываем суффикс «В» (Вынос): позиции «… В» имеют тот же себес,
    что и пара без «В». В прайсе кухня/бар пары уже есть; для шоколада
    при джойне расширяем варианты в обе стороны.
  * Сегмент: «Шоколад» / «Кухня и бар»

Выход:
    docs/себестоимость.parquet
    Колонки: Номенклатура | Себес сырья | ПНР | Себес полн. | Розница | Сегмент | Источник

Запуск:
    python dashboard_v2/build_cost_reference.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "себестоимость.parquet"
CHOC_PATH = Path("D:/claude/себес шоколад.xlsx")
KB_PATH = Path("D:/claude/себес цены кухня и бар.xlsx")

_PAREN = re.compile(r"\(\s*1\s*(?:шт|конфета)\s*\)", re.IGNORECASE)
_TAIL_V = re.compile(r"\s+[Вв]\s*$")
_SP = re.compile(r"\s+")


def norm(s) -> str:
    if pd.isna(s):
        return ""
    t = str(s).lower().strip()
    t = t.replace("ё", "е").replace('"', "").replace("'", "")
    t = _PAREN.sub(" ", t)
    t = t.replace(".", " ").replace(",", " ")
    t = _SP.sub(" ", t).strip()
    return t


def variants(s: str) -> list[str]:
    """Расширенный набор ключей: с/без «плитка», с/без хвостового « В» (Вынос)."""
    out: set[str] = set()
    base = norm(s)
    out.add(base)
    if base.startswith("плитка "):
        out.add(base[len("плитка "):])
    else:
        out.add("плитка " + base)
    base_no_v = _TAIL_V.sub("", base).strip()
    if base_no_v != base:
        out.add(base_no_v)
    else:
        out.add(base + " в")  # пара «с В»
    return [v for v in out if v]


def load_chocolate() -> pd.DataFrame:
    df = pd.read_excel(CHOC_PATH)
    df = df.rename(columns={df.columns[0]: "Номенклатура"})
    df = df.dropna(subset=["Номенклатура"]).copy()
    df["Номенклатура"] = df["Номенклатура"].astype(str).str.strip()
    df["Себес сырья"] = pd.to_numeric(df.get("себес сырьевая"), errors="coerce")
    df["ПНР"] = pd.to_numeric(df.get("пнр"), errors="coerce")
    df["Себес полн."] = pd.to_numeric(df.get("себес+пнр"), errors="coerce")
    df["Розница"] = pd.to_numeric(df.get("розница"), errors="coerce")
    df["Сегмент"] = "Шоколад"
    df["Источник"] = "себес шоколад.xlsx"
    return df[["Номенклатура", "Себес сырья", "ПНР", "Себес полн.", "Розница",
                "Сегмент", "Источник"]]


def load_kitchen_bar() -> pd.DataFrame:
    raw = pd.read_excel(KB_PATH, header=None)
    # Находим строку, где Unnamed:1 == 'Номенклатура' — это шапка
    header_row = None
    for i in range(min(10, len(raw))):
        row_vals = raw.iloc[i].astype(str).tolist()
        if any("Номенклатура" in v for v in row_vals):
            header_row = i
            break
    if header_row is None:
        header_row = 1
    df = raw.iloc[header_row + 2:].copy()
    df.columns = ["Comment", "Номенклатура", "Себес полн.", "Розница",
                   "C1", "C2", "C3", "C4"][: df.shape[1]]
    df = df[["Номенклатура", "Себес полн.", "Розница"]].copy()
    df = df.dropna(subset=["Номенклатура"])
    df["Номенклатура"] = df["Номенклатура"].astype(str).str.strip()
    # Секции-заголовки: и себес и цена пустые
    df["Себес полн."] = pd.to_numeric(df["Себес полн."], errors="coerce")
    df["Розница"] = pd.to_numeric(df["Розница"], errors="coerce")
    df = df[df["Себес полн."].notna() | df["Розница"].notna()].copy()
    df["Себес сырья"] = pd.NA
    df["ПНР"] = pd.NA
    df["Сегмент"] = "Кухня и бар"
    df["Источник"] = "себес цены кухня и бар.xlsx"
    return df[["Номенклатура", "Себес сырья", "ПНР", "Себес полн.", "Розница",
                "Сегмент", "Источник"]]


def match_against_sales(cost: pd.DataFrame, sales_skus: list[str]) -> pd.DataFrame:
    """Проставляем колонку Номенклатура продаж (matched_sku).

    Если в прайсе строка X имеет вариант, совпадающий с продажным SKU Y,
    привязываем X к Y. Для пар «без В / с В» (Вынос) даём ОБА SKU — это значит
    одна строка прайса может породить 2 строки в итоговом справочнике."""
    # ключ продаж → канонический SKU продаж
    sales_map: dict[str, str] = {}
    for s in sales_skus:
        for v in variants(s):
            sales_map.setdefault(v, s)

    # Обратный индекс: variant ключ → набор продажных SKU, у которых он есть
    variant_to_skus: dict[str, set[str]] = {}
    for s in sales_skus:
        for v in variants(s):
            variant_to_skus.setdefault(v, set()).add(s)

    rows = []
    for _, r in cost.iterrows():
        cost_variants = set(variants(r["Номенклатура"]))
        matched: list[str] = []
        seen: set[str] = set()
        for v in cost_variants:
            for sku in variant_to_skus.get(v, ()):
                if sku not in seen:
                    seen.add(sku)
                    matched.append(sku)
        if not matched:
            # Не нашли пару — оставляем оригинальное имя из прайса
            rec = r.to_dict()
            rec["matched_sku"] = None
            rows.append(rec)
        else:
            for sku in matched:
                rec = r.to_dict()
                rec["matched_sku"] = sku
                rows.append(rec)
    out = pd.DataFrame(rows)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    print("Загружаю продажи…")
    pq = pd.read_parquet(ROOT / "docs" / "база.parquet")
    sales_skus = sorted(pq["Номенклатура"].dropna().unique().tolist())
    sales_rev = pq.groupby("Номенклатура")["Сумма"].sum()
    total_rev = sales_rev.sum()
    print(f"  SKU в продажах: {len(sales_skus):,}")

    print("\nЧитаю прайс шоколада…")
    choc = load_chocolate()
    print(f"  строк: {len(choc)}")

    print("Читаю прайс кухни/бара…")
    kb = load_kitchen_bar()
    print(f"  строк: {len(kb)}")

    print("\nСверяю с продажами…")
    cost_all = pd.concat([choc, kb], ignore_index=True)
    matched = match_against_sales(cost_all, sales_skus)

    # Финальная таблица: оставляем только строки с найденным матчем,
    # ключ = SKU продаж, сохраняем исходное имя из прайса для прозрачности.
    final = matched.dropna(subset=["matched_sku"]).copy()
    final["Номенклатура_прайс"] = final["Номенклатура"]
    final["Номенклатура"] = final["matched_sku"]
    final = final.drop(columns=["matched_sku"])

    # Дедупликация: если SKU продаж получил несколько строк прайса (редко), оставим ту, у кого больше данных
    final["_score"] = final[["Себес сырья", "ПНР", "Себес полн.", "Розница"]].notna().sum(axis=1)
    final = (final.sort_values(["Номенклатура", "_score"], ascending=[True, False])
                   .drop_duplicates("Номенклатура")
                   .drop(columns="_score"))

    cols = ["Номенклатура", "Себес сырья", "ПНР", "Себес полн.", "Розница",
            "Сегмент", "Источник", "Номенклатура_прайс"]
    final = final[cols].reset_index(drop=True)

    # --- метрики покрытия ---
    cov_skus = final["Номенклатура"].nunique()
    cov_rev = sales_rev.loc[sales_rev.index.intersection(final["Номенклатура"])].sum()
    uncov = sales_rev[~sales_rev.index.isin(final["Номенклатура"])]
    uncov_top10_rev = uncov.sort_values(ascending=False).head(10).sum()
    print()
    print(f"Покрытие: {cov_skus}/{len(sales_skus)} SKU "
          f"({cov_skus/len(sales_skus)*100:.1f}%)")
    print(f"Выручка покрытых: {cov_rev/1e6:.2f} млн из {total_rev/1e6:.2f} млн "
          f"({cov_rev/total_rev*100:.1f}%)")
    print(f"Топ-10 непокрытых по выручке: {uncov_top10_rev/1e6:.2f} млн")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    final.to_parquet(OUT, engine="pyarrow", compression="snappy", index=False)
    size_kb = OUT.stat().st_size / 1024
    print(f"\nСохранено: {OUT}  ({size_kb:.1f} КБ, {len(final)} строк)")


if __name__ == "__main__":
    main()
