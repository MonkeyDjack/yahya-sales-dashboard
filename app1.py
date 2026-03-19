import streamlit as st
import pandas as pd
from pathlib import Path
import io
from datetime import date
import matplotlib.pyplot as plt

# ============ Page ============
st.set_page_config(page_title="Dashboard (Base)", layout="wide")

# ============ Data loading helpers ============
@st.cache_data(show_spinner=True)
def load_excel_from_bytes(xlsx_bytes: bytes, sheet_name: str | None = None) -> pd.DataFrame:
    """Load xlsx from uploaded bytes."""
    bio = io.BytesIO(xlsx_bytes)
    if sheet_name is None:
        xls = pd.ExcelFile(bio)
        # попытка выбрать “базовый” лист, иначе первый
        preferred = ["база", "База", "Sheet1", "Лист1", "Лист 1"]
        sheet_name = next((s for s in preferred if s in xls.sheet_names), xls.sheet_names[0])

    df = pd.read_excel(bio, sheet_name=sheet_name, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df

@st.cache_data(show_spinner=True)
def load_excel_from_path(path: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Load xlsx from local path."""
    if sheet_name is None:
        xls = pd.ExcelFile(path)
        preferred = ["база", "База", "Sheet1", "Лист1", "Лист 1"]
        sheet_name = next((s for s in preferred if s in xls.sheet_names), xls.sheet_names[0])

    df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    return df

def basic_clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "Дата" in df.columns:
        dt = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=True)
        df["Дата"] = dt.dt.normalize()  # datetime64[ns], время 00:00
        df = df[df["Дата"].notna()]     # убираем NaT (это и фиксит твою ошибку)

    for col in ["Количество", "Сумма", "Цена"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Филиал", "Точки", "Номенклатура", "Категория", "Подкатегория", "Время"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    return df


def validate_minimum(df: pd.DataFrame) -> None:
    """Минимальная проверка структуры."""
    required = ["Филиал", "Точки", "Номенклатура", "Количество", "Сумма", "Дата"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"В данных не хватает колонок: {missing}")
        st.stop()

    if df["Дата"].isna().all():
        st.error("Не удалось распознать ни одной даты в колонке 'Дата'. Проверь формат дат.")
        st.stop()

def safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0

def money(x: float) -> str:
    # если хочешь с валютой: return f"{x:,.0f} сом".replace(",", " ")
    return f"{x:,.0f}".replace(",", " ")

# ============ Sidebar: source ============
st.sidebar.header("Источник данных")

source_mode = st.sidebar.radio(
    "Откуда брать данные?",
    ["Загрузить вручную", "Локальный файл рядом с app.py"],
    index=1
)


df = None

if source_mode == "Загрузить вручную":
    up = st.sidebar.file_uploader("Excel файл (.xlsx)", type=["xlsx"], key="uploader_xlsx")

    if up is not None:
        st.session_state["uploaded_xlsx_bytes"] = up.getvalue()

    if "uploaded_xlsx_bytes" in st.session_state:
        df = load_excel_from_bytes(st.session_state["uploaded_xlsx_bytes"])

else:
    # по умолчанию ищем один из файлов рядом с app.py
    p1 = Path("Итоговый_отчет1.xlsx")
    p0 = Path("Итоговый_отчет.xlsx")
    path = str(p1) if p1.exists() else str(p0)

    try:
        df = load_excel_from_path(path)
        st.sidebar.caption(f"Локальный файл: {path}")
    except Exception as e:
        st.error(f"Не удалось прочитать файл '{path}'. Ошибка: {e}")
        st.stop()

# ============ Guard ============
if df is None or df.empty:
    st.info("Загрузите Excel файл, чтобы начать.")
    st.stop()

df = basic_clean(df)
validate_minimum(df)
# ============ Sidebar: filters (apply button) ============
min_ts = df["Дата"].min()
max_ts = df["Дата"].max()
min_d = min_ts.date()
max_d = max_ts.date()

branches_all = sorted(df["Филиал"].dropna().astype(str).unique().tolist())

# applied (то, что реально влияет на данные)
if "applied_filters" not in st.session_state:
    st.session_state.applied_filters = {
        "date_range": (min_d, max_d),
        "branches": branches_all,
        "points": [],          # пусто = все точки
        "categories": [],      # пусто = все категории
        "subcategories": [],   # пусто = все подкатегории
        "abc_metric": "Сумма",
        "items": []
    }


# версии ключей (нужно, чтобы корректно "ресетить" виджеты при смене файла/списков)
if "filters_version" not in st.session_state:
    st.session_state.filters_version = 0

# ---- нормализация applied под текущий файл ----
ap_from, ap_to = st.session_state.applied_filters["date_range"]
ap_branches = st.session_state.applied_filters.get("branches", branches_all)

# если applied содержит филиалы, которых больше нет в новом файле — сброс
need_reset = (ap_from < min_d) or (ap_to > max_d) or (not set(ap_branches).issubset(set(branches_all)))
if need_reset:
    st.session_state.applied_filters["date_range"] = (min_d, max_d)
    st.session_state.applied_filters["branches"] = branches_all
    st.session_state.applied_filters["points"] = []
    st.session_state.filters_version += 1

# ---- вычисляем доступные точки на основе applied филиалов ----
branches_selected_applied = st.session_state.applied_filters.get("branches", branches_all) or branches_all
df_for_points = df[df["Филиал"].isin(branches_selected_applied)]
points_all = sorted(df_for_points["Точки"].dropna().astype(str).unique().tolist())

# applied points тоже нормализуем (чтобы не было "мертвых" значений)
ap_points = st.session_state.applied_filters.get("points", [])
if ap_points and not set(ap_points).issubset(set(points_all)):
    st.session_state.applied_filters["points"] = []
    st.session_state.filters_version += 1

st.sidebar.header("Фильтры")

with st.sidebar.form("filters_form", clear_on_submit=False):
    default_from, default_to = st.session_state.applied_filters["date_range"]
    default_branches = st.session_state.applied_filters.get("branches", branches_all)

    draft_date_range = st.date_input(
        "Период",
        value=(default_from, default_to),
        min_value=min_d,
        max_value=max_d,
        format="DD.MM.YYYY",
        key=f"date_range_input_{st.session_state.filters_version}",
    )

    draft_branches = st.multiselect(
        "Филиал",
        options=branches_all,
        default=default_branches,
        key=f"branches_input_{st.session_state.filters_version}",
    )

    # points options зависят от ВЫБРАННЫХ в форме филиалов
    branches_for_points = draft_branches or branches_all
    df_points_draft = df[df["Филиал"].isin(branches_for_points)]
    points_options = sorted(df_points_draft["Точки"].dropna().astype(str).unique().tolist())

    # default points: если ранее были выбраны, оставим только те, что есть в options
    default_points = [p for p in st.session_state.applied_filters.get("points", []) if p in points_options]

    draft_points = st.multiselect(
        "Точки",
        options=points_options,
        default=default_points,
        key=f"points_input_{st.session_state.filters_version}",
    )
        # --- Категория / Подкатегория ---
    # Категории зависят от выбранных филиалов/точек (draft), чтобы не показывать мусор
    df_cat_base = df.copy()
    df_cat_base = df_cat_base[df_cat_base["Филиал"].isin(branches_for_points)]
    if draft_points:
        df_cat_base = df_cat_base[df_cat_base["Точки"].isin(draft_points)]

    categories_options = sorted(df_cat_base["Категория"].dropna().astype(str).unique().tolist())

    # default: applied, но только те, что есть в options
    default_categories = [
        c for c in st.session_state.applied_filters.get("categories", [])
        if c in categories_options
    ]

    draft_categories = st.multiselect(
        "Категория",
        options=categories_options,
        default=default_categories,   # по умолчанию пусто = все
        key=f"categories_input_{st.session_state.filters_version}",
        help="Оставь пустым — будут показаны все категории",
    )

    # Подкатегории: если выбраны категории — показываем только из них
    df_sub_base = df_cat_base
    if draft_categories:
        df_sub_base = df_sub_base[df_sub_base["Категория"].isin(draft_categories)]

    subcategories_options = sorted(df_sub_base["Подкатегория"].dropna().astype(str).unique().tolist())

    default_subcategories = [
        sc for sc in st.session_state.applied_filters.get("subcategories", [])
        if sc in subcategories_options
    ]

    draft_subcategories = st.multiselect(
        "Подкатегория",
        options=subcategories_options,
        default=default_subcategories,  # по умолчанию пусто = все
        key=f"subcategories_input_{st.session_state.filters_version}",
        help="Если выбрана Категория — здесь будут только доступные Подкатегории",
    )
    # --- Номенклатура (зависит от выбранных фильтров в форме) ---
    df_item_base = df_cat_base  # уже отфильтрован по филиалам (+ точкам, если выбраны)

    if draft_categories:
        df_item_base = df_item_base[df_item_base["Категория"].isin(draft_categories)]
    if draft_subcategories:
        df_item_base = df_item_base[df_item_base["Подкатегория"].isin(draft_subcategories)]

    items_options = sorted(df_item_base["Номенклатура"].dropna().astype(str).unique().tolist())

    default_items = [
        x for x in st.session_state.applied_filters.get("items", [])
        if x in items_options
    ]

    draft_items = st.multiselect(
        "Номенклатура",
        options=items_options,
        default=default_items,  # пусто = все
        key=f"items_input_{st.session_state.filters_version}",
        help="Оставь пустым — будут показаны все номенклатуры. Можно искать по названию.",
    )

    draft_metric = st.radio(
        "ABC метрика",
        options=["Сумма", "Количество"],
        index=0 if st.session_state.applied_filters.get("abc_metric", "Сумма") == "Сумма" else 1,
        horizontal=True,
        key=f"abc_metric_input_{st.session_state.filters_version}",
    )


    apply_btn = st.form_submit_button("Применить")

if apply_btn:
    # --- дата ---
    if isinstance(draft_date_range, tuple) and len(draft_date_range) == 2:
        d_from, d_to = draft_date_range
    else:
        d_from = d_to = draft_date_range
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    # --- филиалы ---
    if not draft_branches:
        draft_branches = branches_all

    # --- точки ---
    # пусто = все точки внутри выбранных филиалов
    st.session_state.applied_filters["date_range"] = (d_from, d_to)
    st.session_state.applied_filters["branches"] = draft_branches
    st.session_state.applied_filters["points"] = draft_points
    st.session_state.applied_filters["categories"] = draft_categories
    st.session_state.applied_filters["subcategories"] = draft_subcategories
    st.session_state.applied_filters["abc_metric"] = draft_metric
    st.session_state.applied_filters["items"] = draft_items


        # если выбраны категории — подкатегории должны быть валидны в их рамках
    if draft_categories and draft_subcategories:
        # пересчитаем доступные подкатегории для выбранных категорий
        df_tmp = df[df["Филиал"].isin(draft_branches)]
        if draft_points:
            df_tmp = df_tmp[df_tmp["Точки"].isin(draft_points)]
        df_tmp = df_tmp[df_tmp["Категория"].isin(draft_categories)]
        valid_sub = set(df_tmp["Подкатегория"].dropna().astype(str).unique().tolist())

        draft_subcategories = [x for x in draft_subcategories if x in valid_sub]
        st.session_state.applied_filters["subcategories"] = draft_subcategories

    # подчищаем items, если они больше не доступны в рамках выбранных категорий/подкатегорий
    # (чтобы не получить пустой датасет из-за "мертвого" выбора)
    df_tmp = df[df["Филиал"].isin(draft_branches)]
    if draft_points:
        df_tmp = df_tmp[df_tmp["Точки"].isin(draft_points)]
    if draft_categories:
        df_tmp = df_tmp[df_tmp["Категория"].isin(draft_categories)]
    if draft_subcategories:
        df_tmp = df_tmp[df_tmp["Подкатегория"].isin(draft_subcategories)]

    valid_items = set(df_tmp["Номенклатура"].dropna().astype(str).unique().tolist())
    st.session_state.applied_filters["items"] = [x for x in draft_items if x in valid_items]



# ---- применяем фильтры по applied ----
d_from, d_to = st.session_state.applied_filters["date_range"]
branches_selected = st.session_state.applied_filters.get("branches", branches_all) or branches_all
points_selected = st.session_state.applied_filters.get("points", [])

from_ts = pd.Timestamp(d_from)
to_ts = pd.Timestamp(d_to)

df_filtered = df[(df["Дата"] >= from_ts) & (df["Дата"] <= to_ts)].copy()
df_filtered = df_filtered[df_filtered["Филиал"].isin(branches_selected)].copy()

# если points_selected пустой — не фильтруем (значит "все точки")
if points_selected:
    df_filtered = df_filtered[df_filtered["Точки"].isin(points_selected)].copy()

categories_selected = st.session_state.applied_filters.get("categories", [])
subcategories_selected = st.session_state.applied_filters.get("subcategories", [])

# Категория: пусто = не фильтруем
if categories_selected:
    df_filtered = df_filtered[df_filtered["Категория"].isin(categories_selected)].copy()

# Подкатегория: пусто = не фильтруем
if subcategories_selected:
    df_filtered = df_filtered[df_filtered["Подкатегория"].isin(subcategories_selected)].copy()

items_selected = st.session_state.applied_filters.get("items", [])

# Номенклатура: пусто = не фильтруем
if items_selected:
    df_filtered = df_filtered[df_filtered["Номенклатура"].isin(items_selected)].copy()

# ============ KPI by branch / point ============
checks_col = "Склад/Товар"

def count_checks(frame: pd.DataFrame) -> int:
    if checks_col not in frame.columns or frame.empty:
        return 0
    s = (
        frame[checks_col]
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .replace({"": pd.NA, "nan": pd.NA})
        .dropna()
    )
    return int(s.nunique())

def kpi_table(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_cols + ["Выручка", "Количество", "Чеков", "Средний чек", "Позиции/чек", "Товаров/чек"])

    g = frame.groupby(group_cols, dropna=False).agg(
        Выручка=("Сумма", "sum"),
        Количество=("Количество", "sum"),
        Строк=("Сумма", "size"),
    ).reset_index()

    # Чеки считаем отдельно (nunique по "Склад/Товар")
    checks = (
        frame[group_cols + [checks_col]]
        .copy()
    )
    checks[checks_col] = (
        checks[checks_col]
        .astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        .replace({"": pd.NA, "nan": pd.NA})
    )

    checks = checks.dropna(subset=[checks_col])
    if not checks.empty:
        checks_cnt = checks.groupby(group_cols)[checks_col].nunique().reset_index().rename(columns={checks_col: "Чеков"})
        g = g.merge(checks_cnt, on=group_cols, how="left")
    else:
        g["Чеков"] = 0

    g["Чеков"] = g["Чеков"].fillna(0).astype(int)

    # Средний чек / позиции / товары в чеке
    g["Средний чек"] = g.apply(lambda r: (r["Выручка"] / r["Чеков"]) if r["Чеков"] else 0.0, axis=1)
    g["Позиции/чек"] = g.apply(lambda r: (r["Строк"] / r["Чеков"]) if r["Чеков"] else 0.0, axis=1)
    g["Товаров/чек"] = g.apply(lambda r: (r["Количество"] / r["Чеков"]) if r["Чеков"] else 0.0, axis=1)

    # Для сортировки и доли
    total_sales = float(g["Выручка"].sum()) if g["Выручка"].sum() else 0.0
    g["Доля выручки"] = g["Выручка"] / total_sales if total_sales else 0.0

    # Красивый порядок
    g = g.sort_values("Выручка", ascending=False)

    # убираем вспомогательное
    g = g.drop(columns=["Строк"])

    return g

kpi_branch = kpi_table(df_filtered, ["Филиал"])
kpi_branch_point = kpi_table(df_filtered, ["Филиал", "Точки"])


# ============ ABC calculation ============
import matplotlib.pyplot as plt

metric = st.session_state.applied_filters.get("abc_metric", "Сумма")
metric_col = "Сумма" if metric == "Сумма" else "Количество"

A_thr = 0.80
B_thr = 0.95

def build_abc(df_in: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    g = (
        df_in.groupby(group_cols, dropna=False)[metric_col]
        .sum()
        .reset_index()
        .rename(columns={metric_col: "Value"})
    )
    g = g.sort_values("Value", ascending=False).reset_index(drop=True)

    total = float(g["Value"].sum()) if not g.empty else 0.0
    if total <= 0 or pd.isna(total):
        g["Share"] = 0.0
        g["CumShare"] = 0.0
    else:
        g["Share"] = g["Value"] / total
        g["CumShare"] = g["Share"].cumsum()

    def cls(x: float) -> str:
        if x <= A_thr:
            return "A"
        if x <= B_thr:
            return "B"
        return "C"

    g["ABC"] = g["CumShare"].apply(cls)
    return g

def abc_summary(abc_df: pd.DataFrame) -> pd.DataFrame:
    """Сводка A/B/C: кол-во SKU, доля SKU, доля Value."""
    if abc_df.empty:
        return pd.DataFrame(columns=["ABC", "SKU_count", "SKU_share", "Value", "Value_share"])

    total_sku = len(abc_df)
    total_val = float(abc_df["Value"].sum()) if abc_df["Value"].sum() else 0.0

    s = (
        abc_df.groupby("ABC")["Value"]
        .agg(SKU_count="count", Value="sum")
        .reset_index()
    )
    s["SKU_share"] = s["SKU_count"] / total_sku if total_sku else 0.0
    s["Value_share"] = s["Value"] / total_val if total_val else 0.0

    # порядок A,B,C
    s["ABC"] = pd.Categorical(s["ABC"], categories=["A", "B", "C"], ordered=True)
    return s.sort_values("ABC").reset_index(drop=True)

def pareto_chart(abc_df: pd.DataFrame, label_col: str, top_n: int = 30):
    """Бар = Value, линия = CumShare. Без явных цветов."""
    d = abc_df.head(top_n).copy()

    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(range(len(d)), d["Value"])
    ax1.set_ylabel(metric_col)
    ax1.set_xlabel(label_col)

    ax1.set_xticks(range(len(d)))
    ax1.set_xticklabels(d[label_col].astype(str).tolist(), rotation=75, ha="right", fontsize=8)

    ax2 = ax1.twinx()
    ax2.plot(range(len(d)), d["CumShare"].values, marker="o")
    ax2.set_ylabel("Кумулятивная доля")
    ax2.set_ylim(0, 1.05)
    ax2.axhline(A_thr, linestyle="--")
    ax2.axhline(B_thr, linestyle="--")

    ax1.set_title(f"Pareto (Top {top_n})")
    fig.tight_layout()
    return fig

abc_overall = build_abc(df_filtered, ["Номенклатура"])
abc_by_branch = build_abc(df_filtered, ["Филиал", "Номенклатура"])
abc_stats = abc_summary(abc_overall)

# ============ Time analysis prep ============
metric = st.session_state.applied_filters.get("abc_metric", "Сумма")
metric_col = "Сумма" if metric == "Сумма" else "Количество"

df_time = df_filtered.copy()

if "Время" in df_time.columns:
    # 1) Приводим к datetime (берём только время)
    t = pd.to_datetime(df_time["Время"].astype(str).str.strip(), errors="coerce")

    # Если в "Время" уже datetime -> берем часы; если только время -> тоже ок
    df_time["Hour"] = t.dt.hour

    # Оставляем только строки, где час распознался
    df_time = df_time[df_time["Hour"].notna()].copy()
    df_time["Hour"] = df_time["Hour"].astype(int)
else:
    df_time = df_time.iloc[0:0].copy()  # пусто, чтобы UI не падал

# касса по филиалам и часам
if not df_time.empty:
    by_branch_hour = (
        df_time.groupby(["Филиал", "Hour"], dropna=False)[metric_col]
        .sum()
        .reset_index()
        .rename(columns={metric_col: "Value"})
    )

    # таблица-матрица: строки=филиалы, колонки=часы
    pivot_branch_hour = (
        by_branch_hour.pivot_table(index="Филиал", columns="Hour", values="Value", fill_value=0)
        .sort_index(axis=1)
    )

    # топ-час по каждому филиалу
    peak_by_branch = (
        by_branch_hour.sort_values(["Филиал", "Value"], ascending=[True, False])
        .groupby("Филиал", as_index=False)
        .head(1)
        .rename(columns={"Hour": "PeakHour", "Value": "PeakValue"})
    )
else:
    by_branch_hour = pd.DataFrame(columns=["Филиал", "Hour", "Value"])
    pivot_branch_hour = pd.DataFrame()
    peak_by_branch = pd.DataFrame(columns=["Филиал", "PeakHour", "PeakValue"])

# ============ Trend + comparison (prev period) ============
def aggregate_for_chart(df_in: pd.DataFrame, metric_col: str, freq: str) -> pd.DataFrame:
    if df_in.empty:
        return pd.DataFrame(columns=["Period", "Value"])
    s = (
        df_in.set_index("Дата")[metric_col]
        .resample(freq)
        .sum()
        .reset_index()
        .rename(columns={"Дата": "Period", metric_col: "Value"})
    )
    return s

def pick_freq(d_from: date, d_to: date) -> str:
    days = (d_to - d_from).days + 1
    if days <= 62:
        return "D"       # до ~2 месяцев: по дням
    if days <= 370:
        return "W-MON"   # до ~1 года: по неделям
    return "MS"          # больше года: по месяцам

freq = pick_freq(d_from, d_to)

# текущий период (df_filtered уже по нему)
cur_series = aggregate_for_chart(df_filtered, metric_col, freq)

# KPI totals (только текущий период)
cur_total = float(df_filtered[metric_col].sum()) if not df_filtered.empty else 0.0

# Top peaks by day (всегда по дням)
df_daily_cur = (
    df_filtered.set_index("Дата")[metric_col]
    .resample("D").sum().reset_index()
    .rename(columns={"Дата": "Day", metric_col: "Value"})
)

best_day = None
best_val = 0.0
if not df_daily_cur.empty:
    idx = df_daily_cur["Value"].idxmax()
    best_day = df_daily_cur.loc[idx, "Day"].date()
    best_val = float(df_daily_cur.loc[idx, "Value"])



# ============ UI ============
# ----------------------------
# Header + KPI
# ----------------------------
# Границы лет по текущему фильтру (df_filtered)
min_year = int(df_filtered["Дата"].dt.year.min()) if not df_filtered.empty else int(pd.Timestamp.today().year)
max_year = int(df_filtered["Дата"].dt.year.max()) if not df_filtered.empty else int(pd.Timestamp.today().year)

# выбранные фильтры (для подписи)
sel_branches = st.session_state.applied_filters.get("branches", [])
sel_points = st.session_state.applied_filters.get("points", [])

st.title(f"Sales Dashboard — {min_year}–{max_year}")
st.caption(
    f"Текущий срез: {d_from:%d.%m.%Y} — {d_to:%d.%m.%Y} | "
    f"Филиалы: {len(sel_branches)} | Точки: {len(sel_points)} | "
    f"Метрика: {metric_col}"
)

sales = float(df_filtered["Сумма"].sum()) if "Сумма" in df_filtered.columns else 0.0
qty = float(df_filtered["Количество"].sum()) if "Количество" in df_filtered.columns else 0.0

checks_col = "Склад/Товар"
if checks_col in df_filtered.columns:
    checks_series = (
        df_filtered[checks_col]
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)  # убираем двойные пробелы
    )
    # считаем только непустые
    checks_cnt = int(checks_series.replace({"": pd.NA, "nan": pd.NA}).dropna().nunique())
else:
    checks_cnt = 0

avg_check = safe_div(sales, checks_cnt)

st.markdown("### KPI")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Выручка", money(sales))
c2.metric("Количество", f"{qty:,.0f}".replace(",", " "))
c3.metric("Чеков", f"{checks_cnt:,}".replace(",", " "))
c4.metric("Средний чек", money(avg_check))

# дополнительный KPI — среднее в день по выбранной метрике
days_cnt = (d_to - d_from).days + 1
main_total = float(df_filtered[metric_col].sum()) if metric_col in df_filtered.columns else 0.0
main_per_day = safe_div(main_total, days_cnt)
c4.metric(f"{metric_col} / день", money(main_per_day))

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["ABC (общий)", "ABC по филиалам", "Время (пики кассы)", "Тренд", "KPI по филиалам"])


with tab1:
    st.subheader(f"ABC по номенклатуре (общий) — метрика: {metric_col}")

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Сводка A/B/C**")
        st.dataframe(abc_stats, use_container_width=True, hide_index=True)

        top_n = st.slider("Top-N для Pareto", 10, 200, 30, 10)
        st.caption("Линии: 80% (A) и 95% (B).")

    with c2:
        if abc_overall.empty:
            st.info("Нет данных для Pareto по выбранным фильтрам.")
        else:
            fig = pareto_chart(abc_overall, label_col="Номенклатура", top_n=top_n)
            st.pyplot(fig, clear_figure=True)

    st.markdown("**Таблица ABC**")
    st.dataframe(abc_overall.head(500), use_container_width=True)

with tab2:
    st.subheader("ABC по номенклатуре в разрезе филиалов")

    # выбор филиала для Pareto внутри филиала
    branches_in_data = sorted(abc_by_branch["Филиал"].dropna().astype(str).unique().tolist())
    if branches_in_data:
        selected_branch = st.selectbox("Филиал для Pareto", branches_in_data)

        abc_one_branch = abc_by_branch[abc_by_branch["Филиал"].astype(str) == str(selected_branch)].copy()
        abc_one_branch = abc_one_branch.sort_values("Value", ascending=False).reset_index(drop=True)
        # пересчёт CumShare внутри филиала (на всякий случай)
        total_b = float(abc_one_branch["Value"].sum()) if not abc_one_branch.empty else 0.0
        if total_b > 0:
            abc_one_branch["Share"] = abc_one_branch["Value"] / total_b
            abc_one_branch["CumShare"] = abc_one_branch["Share"].cumsum()
            abc_one_branch["ABC"] = abc_one_branch["CumShare"].apply(lambda x: "A" if x <= A_thr else ("B" if x <= B_thr else "C"))
        else:
            abc_one_branch["Share"] = 0.0
            abc_one_branch["CumShare"] = 0.0
            abc_one_branch["ABC"] = "C"

        top_n_b = st.slider("Top-N для Pareto (филиал)", 10, 200, 30, 10, key="topn_branch")
        if not abc_one_branch.empty:
            fig_b = pareto_chart(abc_one_branch.rename(columns={"Номенклатура": "Номенклатура"}), label_col="Номенклатура", top_n=top_n_b)
            st.pyplot(fig_b, clear_figure=True)

        st.markdown("**Таблица ABC (выбранный филиал)**")
        st.dataframe(abc_one_branch.head(500), use_container_width=True)

    st.markdown("**Полная таблица ABC по филиалам**")
    st.dataframe(abc_by_branch.head(500), use_container_width=True)

with tab3:
    st.subheader(f"Касса по времени (метрика: {metric_col})")

    if df_time.empty:
        st.info("Нет корректных данных в колонке 'Время' для выбранных фильтров.")
    else:
        c1, c2 = st.columns([1, 2])

        with c1:
            st.markdown("**Пиковый час по каждому филиалу**")
            # красивый формат часа
            view = peak_by_branch.copy()
            if not view.empty:
                view["PeakHour"] = view["PeakHour"].apply(lambda h: f"{int(h):02d}:00")
            st.dataframe(view, use_container_width=True, hide_index=True)

        with c2:
            st.markdown("**Матрица: филиалы × часы** (значение = сумма/кол-во)")
            st.dataframe(pivot_branch_hour, use_container_width=True)

        # Дополнительно: график по выбранному филиалу
        branches = sorted(by_branch_hour["Филиал"].dropna().astype(str).unique().tolist())
        sel = st.selectbox("Показать график по филиалу", branches)

        d = by_branch_hour[by_branch_hour["Филиал"].astype(str) == str(sel)].sort_values("Hour")
        # простой line chart
        chart_df = d.set_index("Hour")["Value"]
        st.line_chart(chart_df)

with tab4:
    st.subheader(f"Тренд за период — метрика: {metric_col}")

    compare_on = st.checkbox("Сравнить с другим периодом", value=False)

    comp_from = comp_to = None
    df_comp = pd.DataFrame()
    comp_series = pd.DataFrame(columns=["Period", "Value"])
    comp_total = 0.0
    comp_delta_pct = None
    comp_freq = None

    if compare_on:
        comp_from, comp_to = st.date_input(
            "Период сравнения",
            value=(d_from, d_to),
            format="DD.MM.YYYY",
            key="compare_date_range"
        )
        if comp_from > comp_to:
            comp_from, comp_to = comp_to, comp_from

        # база для сравнения: исходный df + все фильтры кроме даты
        df_comp_base = df.copy()

        branches_selected = st.session_state.applied_filters.get("branches", [])
        points_selected = st.session_state.applied_filters.get("points", [])
        categories_selected = st.session_state.applied_filters.get("categories", [])
        subcategories_selected = st.session_state.applied_filters.get("subcategories", [])
        items_selected = st.session_state.applied_filters.get("items", [])

        if branches_selected:
            df_comp_base = df_comp_base[df_comp_base["Филиал"].isin(branches_selected)]
        if points_selected:
            df_comp_base = df_comp_base[df_comp_base["Точки"].isin(points_selected)]
        if categories_selected:
            df_comp_base = df_comp_base[df_comp_base["Категория"].isin(categories_selected)]
        if subcategories_selected:
            df_comp_base = df_comp_base[df_comp_base["Подкатегория"].isin(subcategories_selected)]
        if items_selected:
            df_comp_base = df_comp_base[df_comp_base["Номенклатура"].isin(items_selected)]

        comp_from_ts = pd.Timestamp(comp_from)
        comp_to_ts = pd.Timestamp(comp_to)
        df_comp = df_comp_base[(df_comp_base["Дата"] >= comp_from_ts) & (df_comp_base["Дата"] <= comp_to_ts)].copy()

        comp_freq = pick_freq(comp_from, comp_to)
        comp_series = aggregate_for_chart(df_comp, metric_col, comp_freq)
        comp_total = float(df_comp[metric_col].sum()) if not df_comp.empty else 0.0

        if comp_total != 0:
            comp_delta_pct = (cur_total - comp_total) / comp_total * 100.0

    # KPI сверху — всегда видно итог за период
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Итого за период", f"{cur_total:,.0f}".replace(",", " "))

    if compare_on:
        c2.metric("Итого (сравнение)", f"{comp_total:,.0f}".replace(",", " "))
        if comp_delta_pct is None:
            c3.metric("Δ к сравнению", "—")
        else:
            c3.metric("Δ к сравнению", f"{comp_delta_pct:+.1f}%")
    else:
        c2.metric("Итого (сравнение)", "—")
        c3.metric("Δ к сравнению", "—")

    if best_day is None:
        c4.metric("Лучший день", "—")
    else:
        c4.metric("Лучший день", f"{best_day:%d.%m.%Y} | {best_val:,.0f}".replace(",", " "))

    # Подписи периодов
    if compare_on:
        st.caption(
            f"Текущий период: {d_from:%d.%m.%Y} — {d_to:%d.%m.%Y}  •  "
            f"Сравнение: {comp_from:%d.%m.%Y} — {comp_to:%d.%m.%Y}  •  "
            f"Агрегация: {'дни' if freq=='D' else ('недели' if freq.startswith('W') else 'месяцы')}"
        )
    else:
        st.caption(
            f"Текущий период: {d_from:%d.%m.%Y} — {d_to:%d.%m.%Y}  •  "
            f"Агрегация: {'дни' if freq=='D' else ('недели' if freq.startswith('W') else 'месяцы')}"
        )

    # График: текущий + (опционально) сравнение
    if cur_series.empty and (not compare_on or comp_series.empty):
        st.info("Нет данных для графика.")
    else:
        fig, ax = plt.subplots(figsize=(12, 4))

        if not cur_series.empty:
            ax.plot(cur_series["Period"], cur_series["Value"], marker="o", linewidth=1, label="Текущий период")

        if compare_on and not comp_series.empty:
            ax.plot(comp_series["Period"], comp_series["Value"], marker="o", linewidth=1, label="Период сравнения")

        ax.set_xlabel("Период")
        ax.set_ylabel(metric_col)
        ax.set_title("Тренд")
        ax.legend()
        fig.autofmt_xdate()
        st.pyplot(fig, clear_figure=True)

    # Топ-10 пиковых дней — удобно даже на год
    st.markdown("**Топ-10 дней (пики) в текущем периоде**")
    if df_daily_cur.empty:
        st.info("Нет данных по дням.")
    else:
        top10 = df_daily_cur.sort_values("Value", ascending=False).head(10).copy()
        top10["Day"] = top10["Day"].dt.date
        st.dataframe(top10[["Day", "Value"]], use_container_width=True, hide_index=True)

with tab5:
    st.subheader("KPI по филиалам → детализация по точкам")

    if df_filtered.empty:
        st.info("Нет данных по выбранным фильтрам.")
    else:
        # Таблица по филиалам
        st.markdown("### Филиалы (итог)")
        view_b = kpi_branch.copy()

        # форматирование (без использования pandas Styler, чтобы было проще)
        view_b["Выручка"] = view_b["Выручка"].round(0)
        view_b["Средний чек"] = view_b["Средний чек"].round(0)
        view_b["Позиции/чек"] = view_b["Позиции/чек"].round(2)
        view_b["Товаров/чек"] = view_b["Товаров/чек"].round(2)
        view_b["Доля выручки"] = (view_b["Доля выручки"] * 100).round(1)

        st.dataframe(view_b, use_container_width=True, hide_index=True)

        st.divider()

        # Drill-down
        branches_list = sorted(df_filtered["Филиал"].dropna().astype(str).unique().tolist())
        sel_branch = st.selectbox("Выбери филиал для детализации", branches_list)

        st.markdown(f"### Точки в филиале: {sel_branch}")
        view_p = kpi_branch_point[kpi_branch_point["Филиал"].astype(str) == str(sel_branch)].copy()

        if view_p.empty:
            st.info("В этом филиале нет данных по точкам.")
        else:
            view_p["Выручка"] = view_p["Выручка"].round(0)
            view_p["Средний чек"] = view_p["Средний чек"].round(0)
            view_p["Позиции/чек"] = view_p["Позиции/чек"].round(2)
            view_p["Товаров/чек"] = view_p["Товаров/чек"].round(2)

            st.dataframe(view_p, use_container_width=True, hide_index=True)

            # Мини-график: выручка по точкам внутри филиала
            chart = view_p.set_index("Точки")["Выручка"]
            st.bar_chart(chart)