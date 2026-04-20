"""
Мэппинг категорий и подкатегорий → верхнеуровневые группы.

Используется:
- build_refactored_excel.py → при подготовке Итоговый_отчет1.xlsx
- app2.py → при загрузке данных, как страховка если Группа отсутствует

Если нужно пересобрать структуру — правь только этот файл.
"""

from __future__ import annotations
import pandas as pd


GROUP_HOT_DRINKS   = "Напитки горячие"
GROUP_COLD_DRINKS  = "Напитки холодные"
GROUP_CHOCO        = "Шоколад и конфеты"
GROUP_DESSERTS     = "Десерты и выпечка"
GROUP_FOOD         = "Еда"
GROUP_SETS         = "Наборы и коробки"
GROUP_SEASONAL     = "Сезонные"
GROUP_OTHER        = "Дополнения и прочее"

GROUP_ORDER = [
    GROUP_HOT_DRINKS, GROUP_COLD_DRINKS, GROUP_CHOCO, GROUP_DESSERTS,
    GROUP_FOOD, GROUP_SETS, GROUP_SEASONAL, GROUP_OTHER,
]


CATEGORY_TO_GROUP: dict[str, str] = {
    # --- Напитки горячие ---
    "Кофе":              GROUP_HOT_DRINKS,
    "Какао":             GROUP_HOT_DRINKS,
    "Чай":               GROUP_HOT_DRINKS,
    "Чай В Пачке":       GROUP_HOT_DRINKS,
    "Дрип Кофе":         GROUP_HOT_DRINKS,
    "Матча":             GROUP_HOT_DRINKS,

    # --- Напитки холодные ---
    "Айс Кофе":          GROUP_COLD_DRINKS,
    "Айс Ти":            GROUP_COLD_DRINKS,
    "Лимонад":           GROUP_COLD_DRINKS,
    "Смузи":             GROUP_COLD_DRINKS,
    "Фреш":              GROUP_COLD_DRINKS,
    "Милк Шейк":         GROUP_COLD_DRINKS,
    "Морс":              GROUP_COLD_DRINKS,
    "Не Сп Напитки":     GROUP_COLD_DRINKS,

    # --- Шоколад и конфеты ---
    "Конфеты":           GROUP_CHOCO,
    "Плитки":            GROUP_CHOCO,
    "Драже":             GROUP_CHOCO,
    "Нуга":              GROUP_CHOCO,
    "Медианты":          GROUP_CHOCO,
    "Батончики":         GROUP_CHOCO,
    "Фондю":             GROUP_CHOCO,
    "Фигуры":            GROUP_CHOCO,
    "Шокочупсы":         GROUP_CHOCO,
    "Шоко Зверята":      GROUP_CHOCO,
    "Для Детей":         GROUP_CHOCO,

    # --- Десерты и выпечка ---
    "Десерт":            GROUP_DESSERTS,
    "Круассаны":         GROUP_DESSERTS,
    "Сабле":             GROUP_DESSERTS,
    "Печенье Штучное":   GROUP_DESSERTS,
    "Мороженное":        GROUP_DESSERTS,
    "Сырники":           GROUP_DESSERTS,

    # --- Еда ---
    "Сендвич":           GROUP_FOOD,
    "Салаты":            GROUP_FOOD,
    "Супы":              GROUP_FOOD,
    "Пицца":             GROUP_FOOD,
    "Феттучини":         GROUP_FOOD,
    "Боулы":             GROUP_FOOD,
    "Хлеб":              GROUP_FOOD,
    "Завтраки":          GROUP_FOOD,
    "Тартины":           GROUP_FOOD,
    "Гарнир":            GROUP_FOOD,
    "Комбо":             GROUP_FOOD,

    # --- Наборы и коробки ---
    "Наборы":            GROUP_SETS,
    "Коробки Сборные":   GROUP_SETS,
    "Корзины":           GROUP_SETS,

    # --- Сезонные ---
    "8 Марта":           GROUP_SEASONAL,
    "14 Февраля":        GROUP_SEASONAL,
    "23 Февраля":        GROUP_SEASONAL,
    "1 Сентября":        GROUP_SEASONAL,
    "Новый Год":         GROUP_SEASONAL,
    "Пасха":             GROUP_SEASONAL,
    "Рамадан":           GROUP_SEASONAL,

    # --- Дополнения и прочее ---
    "Добавки К Напиткам":GROUP_OTHER,
    "Соусы":             GROUP_OTHER,
    "Мед В Упаковке":    GROUP_OTHER,
    "Стаканы":           GROUP_OTHER,
    "Пакеты":            GROUP_OTHER,
    "Пф":                GROUP_OTHER,
    "Другое":            GROUP_OTHER,
}


SUBCATEGORY_NORMALIZE: dict[str, str] = {
    "нет подкатегорий":       "Без подкатегории",
    "конфеты корпусные":      "Корпусные конфеты",
    "конфеты нарезные":       "Нарезные конфеты",
    "конфеты коктельные":     "Коктейльные конфеты",
    "корпусная коллекция":    "Корпусная коллекция",
    "птичье молоко":          "Птичье молоко",
    "финики":                 "Финики",
    "трюфели":                "Трюфели",
    "драже классика":         "Драже классика",
    "драже без сахара":       "Драже без сахара",
    "дубайские плитки":       "Дубайские плитки",
    "стандартные плитки":     "Стандартные плитки",
    "весовой шоколад":        "Весовой шоколад",
    "шестригранник":          "Шестигранник",
    "павони":                 "Павони",
    "круассан сендвич":       "Круассан-сэндвич",
    "итальянский сендвич":    "Итальянский сэндвич",
    "ролл":                   "Ролл",
    "симит":                  "Симит",
    "чиабатта":               "Чиабатта",
    "сиропы":                 "Сиропы",
    "молоко":                 "Молоко",
    "лимон":                  "Лимон",
    "мед":                    "Мёд",
    "мята":                   "Мята",
    "эспрессо":               "Эспрессо",
    "трубочки":               "Трубочки",
    "вафли":                  "Вафли",
    "выпечка":                "Выпечка",
    "торты":                  "Торты",
    "чизкейки":               "Чизкейки",
    "пирожное":               "Пирожное",
    "тарталетки":             "Тарталетки",
    "тарты":                  "Тарты",
    "трайфл":                 "Трайфл",
    "клубника в шок":         "Клубника в шоколаде",
    "афогато":                "Афогато",
    "мокко":                  "Мокко",
    "флэт уайт":              "Флэт-уайт",
    "наборы":                 "Наборы",
    "сигары":                 "Сигары",
    "плитки":                 "Плитки",
    "фигуры":                 "Фигуры",
    "конфеты":                "Конфеты",
    "нарезные наборы":        "Нарезные наборы",
    "плиточные наборы":       "Плиточные наборы",
    "премиум наборы":         "Премиум наборы",
    "коктельные наборы":      "Коктейльные наборы",
    "нац. Конфеты":           "Нац. конфеты",
    "старое":                 "Старое",
    "Тартины":                "Тартины",
    "Капучинно":              "Капучино",      # фикс двойного «н»
    "Американо":              "Американо",
    "Латте":                  "Латте",
    "Раф":                    "Раф",
    "Бамбл":                  "Бамбл",
    "Шу":                     "Шу",
    "Рамадан":                "Рамадан",
    "100 на 100":             "100×100",
    "Y плитки":               "Y-плитки",
    "Нац. Плитки":            "Нац. плитки",
    "корпусная коллекция":    "Корпусная коллекция",
    "Фигуры":                 "Фигуры",
    "Тарталетки":             "Тарталетки",
}


def normalize_subcategory(value) -> str:
    """Нормализует одну подкатегорию (регистр, опечатки)."""
    if pd.isna(value):
        return "Без подкатегории"
    s = str(value).strip()
    if not s:
        return "Без подкатегории"
    if s in SUBCATEGORY_NORMALIZE:
        return SUBCATEGORY_NORMALIZE[s]
    # fallback: Title Case для первого слова
    return s[0].upper() + s[1:]


def category_to_group(category) -> str:
    if pd.isna(category):
        return GROUP_OTHER
    return CATEGORY_TO_GROUP.get(str(category).strip(), GROUP_OTHER)


def apply_mapping(df: pd.DataFrame) -> pd.DataFrame:
    """Применяет Группа + нормализацию Подкатегории к DataFrame in-place-style.

    Ожидает колонки «Категория», «Подкатегория». Добавляет «Группа».
    Если «Группа» уже есть — не перезаписывает.
    """
    df = df.copy()
    if "Подкатегория" in df.columns:
        df["Подкатегория"] = df["Подкатегория"].apply(normalize_subcategory)
    if "Группа" not in df.columns and "Категория" in df.columns:
        df["Группа"] = df["Категория"].apply(category_to_group)
    return df
