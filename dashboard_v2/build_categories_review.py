"""Выгрузка справочника SKU для ручной ревизии категорий.

Берёт уникальные SKU из docs/база.parquet, для каждого SKU — каноническую
(Группа, Категория, Подкатегория) и выводит в Excel, отсортированный
по Категория → Подкатегория → Номенклатура.

Юзер правит в Excel столбцы Группа/Категория/Подкатегория, потом
скрипт apply_categories_review.py применит изменения обратно в parquet.

Выход: reports/categories_review.xlsx
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import xlsxwriter

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "docs" / "база.parquet"
OUT = ROOT / "reports" / "categories_review.xlsx"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    pq = pd.read_parquet(PARQUET)

    # Каноническая комбинация (Группа, Категория, Подкатегория) на SKU
    # — берём ту, что встречается чаще всего у этого SKU
    combos = (pq.groupby(["Номенклатура", "Группа", "Категория", "Подкатегория"])
                .size().reset_index(name="n"))
    canon = (combos.sort_values(["Номенклатура", "n"], ascending=[True, False])
                    .drop_duplicates("Номенклатура")
                    .drop(columns="n"))

    # Доп. контекст: общая выручка SKU (для приоритизации правок)
    rev = (pq.groupby("Номенклатура")["Сумма"].sum()
              .reset_index().rename(columns={"Сумма": "Выручка (всё время)"}))
    canon = canon.merge(rev, on="Номенклатура", how="left")

    # Сортировка: Категория → Подкатегория → Номенклатура
    canon = canon.sort_values(["Категория", "Подкатегория", "Номенклатура"],
                                na_position="last")

    cols = ["Номенклатура", "Группа", "Категория", "Подкатегория", "Выручка (всё время)"]
    canon = canon[cols].reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(OUT))
    ws = wb.add_worksheet("Категории")

    header_fmt = wb.add_format({
        "bold": True, "font_color": "white", "bg_color": "#1F4E79",
        "align": "center", "valign": "vcenter", "text_wrap": True,
        "font_name": "Calibri", "font_size": 11, "border": 1,
    })
    cell_fmt = wb.add_format({"font_name": "Calibri", "font_size": 10,
                                "border": 1, "border_color": "#BFBFBF"})
    edit_fmt = wb.add_format({"font_name": "Calibri", "font_size": 10,
                                "border": 1, "border_color": "#BFBFBF",
                                "bg_color": "#FFF8DC"})  # тёплый кремовый — «здесь правь»
    money_fmt = wb.add_format({"font_name": "Calibri", "font_size": 10,
                                 "border": 1, "border_color": "#BFBFBF",
                                 "num_format": "#,##0", "align": "right"})

    # Шапка
    for ci, c in enumerate(cols):
        ws.write(0, ci, c, header_fmt)
    ws.set_row(0, 30)

    # Тело
    for ri, row in enumerate(canon.itertuples(index=False), 1):
        ws.write_string(ri, 0, str(row[0]), cell_fmt)            # Номенклатура (key, не править)
        ws.write_string(ri, 1, str(row[1] or ""), edit_fmt)      # Группа (правится)
        ws.write_string(ri, 2, str(row[2] or ""), edit_fmt)      # Категория (правится)
        ws.write_string(ri, 3, str(row[3] or ""), edit_fmt)      # Подкатегория (правится)
        v = row[4]
        if pd.notna(v):
            ws.write_number(ri, 4, float(v), money_fmt)
        else:
            ws.write_blank(ri, 4, None, cell_fmt)

    # Ширины колонок
    ws.set_column(0, 0, 55)  # Номенклатура
    ws.set_column(1, 1, 22)  # Группа
    ws.set_column(2, 2, 22)  # Категория
    ws.set_column(3, 3, 24)  # Подкатегория
    ws.set_column(4, 4, 16)  # Выручка

    ws.freeze_panes(1, 1)
    ws.autofilter(0, 0, len(canon), len(cols) - 1)

    # Лист с инструкциями
    ws2 = wb.add_worksheet("ℹ️ Инструкция")
    info_fmt = wb.add_format({"font_name": "Calibri", "font_size": 11,
                                "text_wrap": True, "valign": "top"})
    title_fmt = wb.add_format({"bold": True, "font_size": 14,
                                 "font_color": "#1F4E79", "font_name": "Calibri"})
    ws2.set_column(0, 0, 100)
    ws2.write(0, 0, "Ревизия категорий — как править", title_fmt)
    ws2.write(2, 0, "1. Открой лист «Категории».", info_fmt)
    ws2.write(3, 0, "2. Жёлтые колонки (Группа / Категория / Подкатегория) — те, что можно править.", info_fmt)
    ws2.write(4, 0, "3. Колонка «Номенклатура» — ключ, НЕ менять (по ней скрипт найдёт SKU).", info_fmt)
    ws2.write(5, 0, "4. Колонка «Выручка (всё время)» — для приоритизации (фокусируйся на крупных).", info_fmt)
    ws2.write(6, 0, "5. Можно использовать автофильтр и сортировку — это не повлияет на применение правок.", info_fmt)
    ws2.write(7, 0, "6. Сохрани файл как есть (xlsx). Скрипт apply_categories_review.py прочитает изменения.", info_fmt)
    ws2.write(9, 0, f"Всего SKU: {len(canon)}", info_fmt)

    wb.close()
    size_kb = OUT.stat().st_size / 1024
    print(f"Готово: {OUT}  ({size_kb:.1f} КБ, {len(canon)} SKU)")


if __name__ == "__main__":
    main()
