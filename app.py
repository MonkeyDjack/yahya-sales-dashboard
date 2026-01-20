import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go
from pathlib import Path
from typing import List, Optional
import io
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

st.set_page_config(page_title="Sales Dashboard", layout="wide")


# ----------------------------
# Helpers
# ----------------------------
def to_xlsx_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """
    sheets: {"SheetName": df, ...}
    Возвращает bytes для st.download_button(file_name=".xlsx")
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df_ in sheets.items():
            safe_name = (name[:31])  # Excel limit
            df_.to_excel(writer, sheet_name=safe_name, index=False)
    output.seek(0)
    return output.getvalue()

def abc_table(
    df_: pd.DataFrame,
    group_col: str,
    value_col: str = "Сумма",
    a_share: float = 0.80,
    b_share: float = 0.95,
) -> pd.DataFrame:
    """
    ABC-классификация по накопительной доле value_col (обычно "Сумма").
    A: до a_share (80%), B: до b_share (95%), C: остальное.
    Возвращает таблицу: group_col, value, share, cum_share, abc.
    """
    if df_.empty:
        return pd.DataFrame(columns=[group_col, value_col, "Доля", "Накопительная доля", "ABC"])

    t = (
        df_.groupby(group_col, as_index=False)[value_col]
           .sum()
           .sort_values(value_col, ascending=False)
           .reset_index(drop=True)
    )

    total = float(t[value_col].sum())
    if total <= 0:
        t["Доля"] = 0.0
        t["Накопительная доля"] = 0.0
        t["ABC"] = "C"
        return t.rename(columns={value_col: "Значение"}).assign(**{value_col: t[value_col]})

    t["Доля"] = t[value_col] / total
    t["Накопительная доля"] = t["Доля"].cumsum()

    def _abc(c):
        if c <= a_share:
            return "A"
        if c <= b_share:
            return "B"
        return "C"

    t["ABC"] = t["Накопительная доля"].apply(_abc)
    return t


def prune_selection(options: List[str], selected: Optional[List[str]], default_all: bool = True) -> List[str]:
    """Оставляет только те selected, которые есть в options.
    Если после фильтрации пусто — либо возвращает все options (default_all=True),
    либо пустой список.
    """
    options = [str(x) for x in options if pd.notna(x)]
    opt_set = set(options)
    sel = [str(x) for x in (selected or []) if str(x) in opt_set]
    if not sel and default_all:
        return options[:]
    return sel

def init_or_reset_key(key: str, options: List[str], reset: bool, default_all: bool = True):
    """Инициализирует session_state[key] ДО виджета.
    При reset=True — сбрасывает на все доступные options (или пусто).
    """
    if key not in st.session_state or reset:
        st.session_state[key] = options[:] if default_all else []
    else:
        st.session_state[key] = prune_selection(options, st.session_state.get(key), default_all=default_all)


def sync_multiselect_state(key: str, available: list[str], default_all: bool = True) -> None:
    """Очищает выбранные значения multiselect, если их больше нет в доступных опциях."""
    available = [str(x) for x in available]
    available_set = set(available)

    cur = st.session_state.get(key)
    if cur is None:
        st.session_state[key] = available[:] if default_all else []
        return

    cur = [str(x) for x in cur]
    cleaned = [x for x in cur if x in available_set]

    # если ничего не осталось — можно выбрать все доступные (если такой режим нужен)
    if default_all and not cleaned:
        cleaned = available[:]

    st.session_state[key] = cleaned






def normalize_category_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Нормализует Категория/Подкатегория:
    - чистит пробелы
    - если Подкатегория пустая или 'нет подкатегорий' -> подставляет Категорию
    """
    df = df.copy()

    if "Категория" in df.columns:
        df["Категория"] = df["Категория"].astype(str).str.strip()

    if "Подкатегория" in df.columns:
        df["Подкатегория"] = df["Подкатегория"].astype(str).str.strip()

    if "Категория" in df.columns and "Подкатегория" in df.columns:
        sub = df["Подкатегория"].astype(str).str.strip()
        cat = df["Категория"].astype(str).str.strip()

        bad = (
            sub.isna()
            | (sub == "")
            | (sub.str.lower().isin(["нет подкатегорий", "нет подкатегории", "nan", "none"]))
        )

        df.loc[bad, "Подкатегория"] = cat[bad]

    return df

def money(x: float) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:,.0f}".replace(",", " ")


def safe_div(a, b):
    return a / b if b else 0


def extract_hour_fast(s: pd.Series) -> pd.Series:
    """
    Пытается извлечь час из колонки "Время" максимально устойчиво.
    Поддерживает:
    - datetime64 / Timestamp
    - строки вида '17:30' / '17:30:48'
    - excel time как число (доля суток)
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.dt.hour

    # числовой excel-time (0..1)
    if pd.api.types.is_numeric_dtype(s):
        # 0.5 => 12:00
        h = np.floor((s.astype(float) % 1.0) * 24.0).astype("Int64")
        return h

    ss = s.astype(str).str.strip()

    # пробуем распарсить как время/датавремя
    t = pd.to_datetime(ss, errors="coerce", dayfirst=True, infer_datetime_format=True)
    # если это "1900-01-01 17:30:00" — ок, берём hour
    h = t.dt.hour.astype("Int64")

    # иногда время бывает "17:30" и to_datetime может дать NaT на части значений — попробуем явно HH:MM(:SS)
    mask = h.isna()
    if mask.any():
        t2 = pd.to_datetime(ss[mask], errors="coerce", format="%H:%M:%S")
        h.loc[mask] = t2.dt.hour.astype("Int64")
        mask2 = h.isna()
        if mask2.any():
            t3 = pd.to_datetime(ss[mask2], errors="coerce", format="%H:%M")
            h.loc[mask2] = t3.dt.hour.astype("Int64")

    return h


# ----------------------------
# Data loading
# ----------------------------
@st.cache_data(show_spinner=True)
def load_excel(path: str) -> pd.DataFrame:
    xls = pd.ExcelFile(path)

    preferred = ["база", "База", "Sheet1", "Лист1", "Лист 1"]
    sheet = next((s for s in preferred if s in xls.sheet_names), None)
    if sheet is None:
        sheet = xls.sheet_names[0]

    df = pd.read_excel(path, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]

    # Дата: держим как date (для фильтрации), а datetime создаём при необходимости (для графиков)
    if "Дата" in df.columns:
        dt = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=True)
        df["Дата"] = dt.dt.date  # <-- важно: date, не datetime64

    for col in ["Количество", "Сумма", "Цена"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Филиал", "Точки", "Номенклатура", "Категория", "Подкатегория"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    if "Время" in df.columns:
        df["Время"] = df["Время"].astype(str).str.strip()

    return df

@st.cache_data(show_spinner=True, ttl=3600)
def load_excel_from_drive(file_id: str) -> pd.DataFrame:
    """
    Скачивает XLSX из Google Drive по file_id (приватный файл),
    используя service account json из st.secrets.
    """
    sa_info = dict(st.secrets["google"]["service_account"])
    file_id = st.secrets["drive"]["file_id"]
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )

    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)

    df = pd.read_excel(fh, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]

    # минимальная нормализация дат/чисел как у вас
    if "Дата" in df.columns:
        dt = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=True)
        df["Дата"] = dt.dt.date

    for col in ["Количество", "Сумма", "Цена"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["Филиал", "Точки", "Номенклатура", "Категория", "Подкатегория"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    if "Время" in df.columns:
        df["Время"] = df["Время"].astype(str).str.strip()

    return df


# ----------------------------
# Sidebar: source
# ----------------------------
st.sidebar.header("Источник данных")

source_mode = st.sidebar.radio(
    "Откуда брать данные?",
    ["Google Drive (приватный файл)", "Загрузить вручную", "Локальный файл рядом с app.py"],
    index=0
)

df = None

if source_mode == "Google Drive (приватный файл)":
    # file_id хранится в secrets
    file_id = st.secrets["drive"]["file_id"]
    df = load_excel_from_drive(file_id)
    df = normalize_category_columns(df)

    if st.sidebar.button("Обновить данные сейчас"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.divider()
    if st.sidebar.button("🔄 Перезагрузить данные из Google Drive"):
        st.cache_data.clear()
        st.rerun()


elif source_mode == "Загрузить вручную":
    up = st.sidebar.file_uploader("Excel файл (.xlsx)", type=["xlsx"])
    if up is not None:
        df = pd.read_excel(io.BytesIO(up.getvalue()), engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]
        if "Дата" in df.columns:
            dt = pd.to_datetime(df["Дата"], errors="coerce", dayfirst=True)
            df["Дата"] = dt.dt.date
        df = normalize_category_columns(df)

else:
    p1 = Path("Итоговый_отчет1.xlsx")
    p0 = Path("Итоговый_отчет.xlsx")
    path = str(p1) if p1.exists() else str(p0)

    try:
        df = load_excel(path)
        df = normalize_category_columns(df)
    except Exception as e:
        st.error(f"Не удалось прочитать файл '{path}'. Ошибка: {e}")
        st.stop()

if df is None or df.empty:
    st.info("Загрузите Excel файл, чтобы начать.")
    st.stop()


# ----------------------------
# Validation
# ----------------------------
required = ["Филиал", "Точки", "Номенклатура", "Количество", "Сумма", "Дата"]
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"В данных не хватает колонок: {missing}. Проверьте заголовки в Excel.")
    st.stop()

df = df[df["Дата"].notna()].copy()
if df.empty:
    st.error("Не удалось распознать ни одной даты в колонке 'Дата'. Проверьте формат дат в Excel.")
    st.stop()

# ----------------------------
# Sidebar: filters (динамический период без года) + каскад Филиал→Точки→Категория→Подкатегория
# ----------------------------
st.sidebar.header("Фильтры")

# --- 0) Период (динамический)
min_date = df["Дата"].min()
max_date = df["Дата"].max()

if "period" not in st.session_state:
    st.session_state["period"] = (min_date, max_date)

cur_from, cur_to = st.session_state["period"]
cur_from = max(min_date, cur_from)
cur_to = min(max_date, cur_to)
if cur_from > cur_to:
    cur_from, cur_to = min_date, max_date

date_from, date_to = st.sidebar.date_input(
    "Период",
    value=(cur_from, cur_to),
    min_value=min_date,
    max_value=max_date,
    key="period_picker"
)
st.session_state["period"] = (date_from, date_to)

# Фиксируем факт изменения периода (нужно, чтобы каскад корректно пересобирал списки)
prev_period = st.session_state.get("_sb_prev_period")
period_changed = (prev_period is not None and tuple(prev_period) != (date_from, date_to))
st.session_state["_sb_prev_period"] = (date_from, date_to)

# --- Вспомогательная функция: подготовка session_state ДО виджета
def prepare_multiselect_state(key: str, options: list[str], reset: bool, default_all_on_first: bool = True) -> None:
    """Гарантирует, что st.session_state[key] содержит только валидные значения из options.
    - reset=True -> ставит все options
    - первый запуск -> ставит все options (если default_all_on_first=True)
    - важно: если пользователь сам очистил выбор ([]) — мы это уважаем (НЕ подставляем обратно все).
    """
    opts = [str(x) for x in options if pd.notna(x)]
    opt_set = set(opts)

    if key not in st.session_state:
        st.session_state[key] = opts[:] if default_all_on_first else []
        return

    if reset:
        st.session_state[key] = opts[:]
        return

    cur = st.session_state.get(key, [])
    cur = [str(x) for x in cur if pd.notna(x)]
    st.session_state[key] = [x for x in cur if x in opt_set]

# --- Базовый срез для построения списков (чтобы опции были релевантны периоду)
df_period = df[(df["Дата"] >= date_from) & (df["Дата"] <= date_to)].copy()

# ----------------------------
# 1) Филиалы (зависят от периода)
# ----------------------------
branches_all = sorted(df_period["Филиал"].dropna().astype(str).unique().tolist())

prepare_multiselect_state(
    key="sb_branches",
    options=branches_all,
    reset=period_changed,              # если поменяли период — обновим список доступных
    default_all_on_first=True
)

sel_branches = st.sidebar.multiselect(
    "Филиал",
    options=branches_all,
    key="sb_branches"
)

# changes (для каскада вниз)
prev_branches = st.session_state.get("_sb_prev_branches")
branches_changed = (prev_branches is not None and tuple(prev_branches) != tuple(sel_branches))
st.session_state["_sb_prev_branches"] = list(sel_branches)

# Если филиалы не выбраны — дальше смысла нет
if not sel_branches:
    st.title("Sales Dashboard")
    st.warning("Выберите хотя бы один филиал в сайдбаре.")
    st.stop()

df_br = df_period[df_period["Филиал"].isin(sel_branches)].copy()

# ----------------------------
# 2) Точки (зависят от периода + филиалов)
# ----------------------------
points_all = sorted(df_br["Точки"].dropna().astype(str).unique().tolist())

prepare_multiselect_state(
    key="sb_points",
    options=points_all,
    reset=period_changed or branches_changed,
    default_all_on_first=True
)

sel_points = st.sidebar.multiselect(
    "Точки",
    options=points_all,
    key="sb_points"
)

prev_points = st.session_state.get("_sb_prev_points")
points_changed = (prev_points is not None and tuple(prev_points) != tuple(sel_points))
st.session_state["_sb_prev_points"] = list(sel_points)

if not sel_points:
    st.title("Sales Dashboard")
    st.warning("Выберите хотя бы одну точку в сайдбаре.")
    st.stop()

df_bp = df_br[df_br["Точки"].isin(sel_points)].copy()

# ----------------------------
# 3) Категория / Подкатегория (каскадно зависят от точек)
# ----------------------------
has_cat = "Категория" in df.columns
has_sub = "Подкатегория" in df.columns

sel_cats = None
sel_subs = None

if has_cat:
    cats_all = sorted(df_bp["Категория"].dropna().astype(str).unique().tolist())

    prepare_multiselect_state(
        key="sb_cats",
        options=cats_all,
        reset=period_changed or branches_changed or points_changed,
        default_all_on_first=True
    )

    sel_cats = st.sidebar.multiselect(
        "Категория",
        options=cats_all,
        key="sb_cats"
    )

    prev_cats = st.session_state.get("_sb_prev_cats")
    cats_changed = (prev_cats is not None and tuple(prev_cats) != tuple(sel_cats))
    st.session_state["_sb_prev_cats"] = list(sel_cats)

    # если категории пустые — дальше будет пусто, но это осознанный выбор
    df_bpc = df_bp[df_bp["Категория"].isin(sel_cats)].copy() if sel_cats else df_bp.iloc[0:0].copy()
else:
    cats_changed = False
    df_bpc = df_bp

if has_sub:
    # Подкатегории считаем уже после фильтра по категориям (если он есть)
    subs_all = sorted(df_bpc["Подкатегория"].dropna().astype(str).unique().tolist())

    prepare_multiselect_state(
        key="sb_subs",
        options=subs_all,
        reset=period_changed or branches_changed or points_changed or cats_changed,
        default_all_on_first=True
    )

    sel_subs = st.sidebar.multiselect(
        "Подкатегория",
        options=subs_all,
        key="sb_subs"
    )

# ----------------------------
# Поиск по номенклатуре
# ----------------------------
name_q = st.sidebar.text_input("Поиск по номенклатуре (часть названия)", value="", key="sb_name_q")

# ----------------------------
# Ограничения / топ / сортировка
# ----------------------------
st.sidebar.subheader("Ограничения (на уровне агрегата)")
min_qty = st.sidebar.number_input("Min Кол-во (за период)", min_value=0.0, value=0.0, step=1.0, key="sb_min_qty")
min_sales = st.sidebar.number_input("Min Сумма (за период)", min_value=0.0, value=0.0, step=1000.0, key="sb_min_sales")

st.sidebar.subheader("Top / сортировка")
top_n = st.sidebar.slider("Top N", min_value=5, max_value=200, value=10, step=1, key="sb_top_n")
sort_by = st.sidebar.selectbox("Сортировать по", ["Сумма", "Количество", "Средняя цена"], key="sb_sort_by")
sort_order = st.sidebar.selectbox("Порядок", ["убыванию", "возрастанию"], key="sb_sort_order")

# ----------------------------
# Apply base filters (row-level)
# ----------------------------
f = df.copy()

# период
f = f[(f["Дата"] >= date_from) & (f["Дата"] <= date_to)]

# филиалы/точки
f = f[f["Филиал"].isin(sel_branches)]
f = f[f["Точки"].isin(sel_points)]

# категории/подкатегории
if has_cat and sel_cats is not None:
    f = f[f["Категория"].isin(sel_cats)]
if has_sub and sel_subs is not None:
    f = f[f["Подкатегория"].isin(sel_subs)]

# поиск
if name_q.strip():
    q = name_q.strip().lower()
    f = f[f["Номенклатура"].astype(str).str.lower().str.contains(q, na=False)]

if f.empty:
    st.title("Sales Dashboard")
    st.warning("По текущим фильтрам данных нет. Измените период/филиалы/точки/категории.")
    st.stop()



# ----------------------------
# Header + KPI
# ----------------------------
min_y = pd.to_datetime(min_date).year
max_y = pd.to_datetime(max_date).year

st.title(f"Sales Dashboard — {min_y}–{max_y}")
st.caption(
    f"Данные из Excel. Текущий срез: {date_from} — {date_to} | "
    f"Филиалы: {len(sel_branches)} | Точки: {len(sel_points)}"
)

sales = float(f["Сумма"].sum())
qty = float(f["Количество"].sum())
avg_price = safe_div(sales, qty) if qty else 0

st.markdown("### KPI")
c1, c2, c3 = st.columns(3)
c1.metric("Выручка", money(sales))
c2.metric("Количество", f"{qty:,.0f}".replace(",", " "))
c3.metric("Средняя цена", money(avg_price))

st.divider()

st.markdown("### ABC анализ")
st.caption("ABC по накопительной доле выручки в текущих фильтрах. Можно переключить уровень и метрику.")

abc_c1, abc_c2, abc_c3, abc_c4 = st.columns([0.30, 0.22, 0.24, 0.24])

with abc_c1:
    abc_level = st.selectbox(
        "Уровень",
        options=["Номенклатура", "Категория", "Подкатегория", "Филиал", "Точки"],
        index=0,
        key="abc_level"
    )

with abc_c2:
    abc_metric = st.selectbox(
        "Метрика",
        options=["Сумма", "Количество"],
        index=0,
        key="abc_metric"
    )

with abc_c3:
    a_share = st.number_input("Порог A (доля)", min_value=0.50, max_value=0.95, value=0.80, step=0.01, key="abc_a")

with abc_c4:
    b_share = st.number_input("Порог B (доля)", min_value=0.60, max_value=0.99, value=0.95, step=0.01, key="abc_b")

# защита от некорректных порогов
if b_share <= a_share:
    st.warning("Порог B должен быть больше порога A. Исправьте значения.")
else:
    # проверяем наличие колонок
    if abc_level not in f.columns:
        st.warning(f"Колонки '{abc_level}' нет в данных — ABC по этому уровню недоступен.")
    elif abc_metric not in f.columns:
        st.warning(f"Колонки '{abc_metric}' нет в данных — ABC по этой метрике недоступен.")
    else:
        abc = abc_table(
            df_=f,
            group_col=abc_level,
            value_col=abc_metric,
            a_share=float(a_share),
            b_share=float(b_share),
        )

        # summary по классам
        summary = (
            abc.groupby("ABC", as_index=False)[abc_metric]
               .sum()
               .sort_values("ABC")
        )
        total_val = float(abc[abc_metric].sum()) if not abc.empty else 0.0
        summary["Доля"] = summary[abc_metric] / (total_val if total_val else 1.0)

        s1, s2 = st.columns([0.62, 0.38])

        with s1:
            st.markdown("**Таблица ABC**")
            if abc_metric == "Сумма":
                fmt_value = lambda v: money(v)
            else:
                fmt_value = lambda v: f"{v:,.0f}".replace(",", " ")

            st.dataframe(
                abc.style.format({
                    abc_metric: fmt_value,
                    "Доля": "{:.2%}",
                    "Накопительная доля": "{:.2%}",
                }),
                use_container_width=True,
                height=520
            )

            xlsx_bytes = to_xlsx_bytes({
                "ABC": abc,
                "Summary": summary,
            })

            st.download_button(
                "Скачать ABC (XLSX)",
                data=xlsx_bytes,
                file_name=f"abc_{abc_level}_{abc_metric}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


        with s2:
            st.markdown("**Итоги по классам**")
            if abc_metric == "Сумма":
                summary_fmt = summary.style.format({abc_metric: lambda v: money(v), "Доля": "{:.1%}"})
            else:
                summary_fmt = summary.style.format({abc_metric: lambda v: f"{v:,.0f}".replace(",", " "), "Доля": "{:.1%}"})

            st.dataframe(summary_fmt, use_container_width=True, height=220)

            # график накопительной доли (Pareto)
            st.markdown("**Парето (накопительная доля)**")
            pareto = abc.copy()
            pareto["_rank"] = range(1, len(pareto) + 1)
            fig_p = px.line(pareto, x="_rank", y="Накопительная доля", markers=False)
            fig_p.update_layout(xaxis_title="Позиция в ранге", yaxis_title="Накопительная доля")
            st.plotly_chart(fig_p, use_container_width=True)
# ----------------------------
# Overview charts
# ----------------------------
st.divider()
st.markdown("Динамика выручки")
left, right = st.columns([1.2, 0.8])

with left:
    by_day = (
        f.assign(_dt=pd.to_datetime(f["Дата"]))
         .groupby("_dt", as_index=False)["Сумма"].sum()
         .sort_values("_dt")
         .rename(columns={"_dt": "Дата"})
    )
    st.plotly_chart(px.line(by_day, x="Дата", y="Сумма"), use_container_width=True)

with right:
    st.subheader("Структура по точкам")
    by_points = (
        f.groupby("Точки", as_index=False)["Сумма"].sum()
         .sort_values("Сумма", ascending=False)
    )
    st.plotly_chart(px.bar(by_points, x="Точки", y="Сумма"), use_container_width=True)

st.divider()

# ----------------------------
# Products / Top (уровень товара)
# ----------------------------
st.markdown("### Обзор продукции")
level_options = ["Номенклатура"]
if has_cat:
    level_options.append("Категория")
if has_sub:
    level_options.append("Подкатегория")

lvl = st.selectbox("Уровень товара для анализа", level_options, index=0)
group_col = "Номенклатура" if lvl == "Номенклатура" else ("Категория" if lvl == "Категория" else "Подкатегория")

agg = (
    f.groupby(group_col, as_index=False)
     .agg({"Сумма": "sum", "Количество": "sum"})
)
agg["Средняя цена"] = agg.apply(lambda r: safe_div(r["Сумма"], r["Количество"]), axis=1)

agg = agg[(agg["Количество"] >= min_qty) & (agg["Сумма"] >= min_sales)]
if agg.empty:
    st.warning("После ограничений Min Кол-во / Min Сумма список пуст. Уменьшите пороги.")
    st.stop()

ascending = (sort_order == "возрастанию")
agg_sorted = agg.sort_values(sort_by, ascending=ascending)
top = agg_sorted.head(top_n)

st.subheader(f"Top {lvl}")
fig_top = px.bar(top.sort_values(sort_by, ascending=False), x=sort_by, y=group_col, orientation="h")
st.plotly_chart(fig_top, use_container_width=True)

top_display = top.copy()
top_display["Доля выручки"] = top_display["Сумма"] / (agg["Сумма"].sum() if agg["Сумма"].sum() else 1)

st.dataframe(
    top_display.rename(columns={"Сумма": "Выручка"})
    .style.format({
        "Выручка": lambda v: money(v),
        "Количество": lambda v: f"{v:,.0f}".replace(",", " "),
        "Средняя цена": lambda v: money(v),
        "Доля выручки": "{:.1%}",
    }),
    use_container_width=True,
    height=420
)

st.divider()

# ----------------------------
# Branch comparison + trends (исправляем ось времени)
# ----------------------------
st.markdown("### Обзор филиалов")
st.subheader("Сравнение филиалов и тренды")

controls = st.columns([0.34, 0.33, 0.33])
with controls[0]:
    trend_metric = st.selectbox("Метрика для тренда", ["Выручка", "Количество", "Средняя цена"], index=0)
with controls[1]:
    trend_grain = st.selectbox("Гранулярность", ["День", "Неделя", "Месяц"], index=0)
with controls[2]:
    default_trend = sel_branches[:min(4, len(sel_branches))] if sel_branches else branches_all[:min(4, len(branches_all))]
trend_branches = st.multiselect(
    "Филиалы для сравнения (линии на графике)",
    options=branches_all,
    default=default_trend
)


b1, b2 = st.columns([0.55, 0.45])

with b1:
    st.markdown("**Рейтинг филиалов (по выручке/кол-ву) в текущих фильтрах**")
    by_branch = (
        f.groupby("Филиал", as_index=False)
         .agg({"Сумма": "sum", "Количество": "sum"})
    )
    by_branch["Средняя цена"] = by_branch.apply(lambda r: safe_div(r["Сумма"], r["Количество"]), axis=1)
    by_branch = by_branch.sort_values("Сумма", ascending=False)

    st.dataframe(
        by_branch.style.format({
            "Сумма": lambda v: money(v),
            "Количество": lambda v: f"{v:,.0f}".replace(",", " "),
            "Средняя цена": lambda v: money(v),
        }),
        use_container_width=True,
        height=320
    )

with b2:
    st.markdown("**Тренд по выбранным филиалам**")
    if not trend_branches:
        st.info("Выберите хотя бы один филиал для тренда.")
    else:
        tmp = f[f["Филиал"].isin(trend_branches)].copy()
        tmp["_dt"] = pd.to_datetime(tmp["Дата"], errors="coerce")
        tmp = tmp[tmp["_dt"].notna()]
        if tmp.empty:
            st.warning("Нет данных для построения тренда по выбранным фильтрам.")
        else:
            if trend_grain == "День":
                tmp["_bucket_dt"] = tmp["_dt"].dt.floor("D")
            elif trend_grain == "Неделя":
                # начало недели (понедельник)
                tmp["_bucket_dt"] = (tmp["_dt"] - pd.to_timedelta(tmp["_dt"].dt.weekday, unit="D")).dt.floor("D")
            else:
                tmp["_bucket_dt"] = tmp["_dt"].dt.to_period("M").dt.to_timestamp()

            g = (
                tmp.groupby(["_bucket_dt", "Филиал"], as_index=False)
                   .agg({"Сумма": "sum", "Количество": "sum"})
                   .sort_values(["_bucket_dt", "Филиал"])
            )

            if trend_metric == "Выручка":
                g["_value"] = g["Сумма"]
                y_title = "Выручка"
            elif trend_metric == "Количество":
                g["_value"] = g["Количество"]
                y_title = "Количество"
            else:
                g["_value"] = g.apply(lambda r: safe_div(r["Сумма"], r["Количество"]), axis=1)
                y_title = "Средняя цена"

            fig_trend = px.line(g, x="_bucket_dt", y="_value", color="Филиал", markers=True)
            fig_trend.update_layout(xaxis_title="Период", yaxis_title=y_title, legend_title="Филиал")
            st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ----------------------------
# Report: Branch (expand) -> Pivot by time bucket (по выбранному уровню)
# ----------------------------
st.markdown("### Обзор продаж номенклатур по филиалам")
st.caption(
    "Итоги по филиалу + раскрытие филиала → Pivot по выбранному уровню товара. "
    "Колонки — период (день/неделя/месяц/год), значения — сумма или количество."
)

data = f.copy()
data["_Дата_dt"] = pd.to_datetime(data["Дата"], errors="coerce")
data = data[data["_Дата_dt"].notna()].copy()
if data.empty:
    st.warning("Нет корректных дат для построения отчёта.")
    st.stop()

c1, c2, c3, c4 = st.columns([0.26, 0.20, 0.28, 0.26])
with c1:
    pivot_grain = st.selectbox("Колонки по периоду", ["День", "Неделя", "Месяц", "Год"], index=2, key="rep_grain")
with c2:
    pivot_value = st.selectbox("Показатель", ["Сумма", "Количество"], index=0, key="rep_value")
with c3:
   rep_branches = st.multiselect(
    "Филиалы (в отчете)",
    options=branches_all,
    default=sel_branches,
    key="rep_branches"
)

with c4:
    rep_top = st.slider("Top (если ничего не выбрано вручную)", 10, 500, 200, step=10, key="rep_top")

if rep_branches:
    data = data[data["Филиал"].isin(rep_branches)]
if data.empty:
    st.warning("По выбранным филиалам в отчёте данных нет.")
    st.stop()

# бакеты времени
if pivot_grain == "День":
    data["_bucket"] = data["_Дата_dt"].dt.date
elif pivot_grain == "Неделя":
    data["_bucket"] = (data["_Дата_dt"] - pd.to_timedelta(data["_Дата_dt"].dt.weekday, unit="D")).dt.date
elif pivot_grain == "Месяц":
    data["_bucket"] = data["_Дата_dt"].dt.to_period("M").dt.to_timestamp().dt.date
else:
    data["_bucket"] = data["_Дата_dt"].dt.year.astype(int)

# --- поиск и выбор элементов (как вы просили: text_input + multiselect)
item_col = group_col  # тот же уровень, что выбран в Products

st.markdown(f"#### Выбор: {lvl} для отчёта")
st.caption("Введите часть названия → выберите несколько позиций. Если список пуст — берём Top по выручке в текущем срезе.")

all_items_full = sorted(data[item_col].dropna().astype(str).unique().tolist())

if "rep_items_selected" not in st.session_state:
    st.session_state["rep_items_selected"] = []

cc1, cc2 = st.columns([0.5, 0.5])
with cc1:
    rep_search = st.text_input("Поиск", value="", key="rep_search")
with cc2:
    st.caption("Подсказка: в мультиселекте тоже есть поиск — можно просто печатать внутри.")

filtered_items = all_items_full
if rep_search.strip():
    ps = rep_search.strip().lower()
    filtered_items = [x for x in all_items_full if ps in x.lower()]

# важно: чтобы выбранные не пропадали при фильтрации поиска
options_items = sorted(set(filtered_items) | set(st.session_state["rep_items_selected"]))

rep_selected = st.multiselect(
    "Выберите позиции",
    options=options_items,
    default=st.session_state["rep_items_selected"],
    key="rep_selected_multiselect"
)
st.session_state["rep_items_selected"] = rep_selected

if rep_selected:
    chosen_items = rep_selected
else:
    chosen_items = (
        data.groupby(item_col, as_index=False)["Сумма"].sum()
            .sort_values("Сумма", ascending=False)
            .head(rep_top)[item_col].astype(str).tolist()
    )
    st.caption(f"Список пуст — использую Top {len(chosen_items)} по выручке (в текущем срезе).")

data = data[data[item_col].astype(str).isin([str(x) for x in chosen_items])].copy()
if data.empty:
    st.warning("После отбора позиций данных нет.")
    st.stop()

# итоги по филиалам
branch_totals = (
    data.groupby("Филиал", as_index=False)
        .agg({"Сумма": "sum", "Количество": "sum"})
)
branch_totals["Средняя цена"] = branch_totals.apply(lambda r: safe_div(r["Сумма"], r["Количество"]), axis=1)
branch_totals = branch_totals.sort_values("Сумма", ascending=False)

st.markdown("#### Итоги по филиалам (раскройте нужный филиал ниже)")
st.dataframe(
    branch_totals.style.format({
        "Сумма": lambda v: money(v),
        "Количество": lambda v: f"{v:,.0f}".replace(",", " "),
        "Средняя цена": lambda v: money(v),
    }),
    use_container_width=True,
    height=260
)

value_col = pivot_value  # "Сумма" или "Количество"

def sort_bucket_cols(cols):
    try:
        return sorted(cols)
    except Exception:
        return list(cols)

for br in branch_totals["Филиал"].tolist():
    br_df = data[data["Филиал"] == br].copy()
    if br_df.empty:
        continue

    p = pd.pivot_table(
        br_df,
        index=[item_col],
        columns="_bucket",
        values=value_col,
        aggfunc="sum",
        fill_value=0
    )

    p = p.reindex(sort_bucket_cols(p.columns), axis=1)
    p["_Итого"] = p.sum(axis=1)
    p = p.sort_values("_Итого", ascending=False)

    if pivot_value == "Сумма":
        styled = p.style.format(lambda v: money(v) if pd.notna(v) else "—")
    else:
        styled = p.style.format(lambda v: f"{v:,.0f}".replace(",", " ") if pd.notna(v) else "—")

    br_sales = float(br_df["Сумма"].sum())
    br_qty = float(br_df["Количество"].sum())
    br_avg = safe_div(br_sales, br_qty) if br_qty else 0

    with st.expander(
        f"{br} — Выручка: {money(br_sales)} | Кол-во: {br_qty:,.0f}".replace(",", " ") + f" | Ср.цена: {money(br_avg)}",
        expanded=False
    ):
        st.dataframe(styled, use_container_width=True, height=520)

        out = p.reset_index()
        csv_rep = out.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            f"Скачать CSV по филиалу: {br}",
            data=csv_rep,
            file_name=f"pivot_{br}_{pivot_grain.lower()}_{pivot_value.lower()}.csv",
            mime="text/csv"
        )

st.divider()

# ----------------------------
# Branch structure: 100% stacked with selectable breakdown (Точки / Категория / Подкатегория)
# ----------------------------
st.subheader("Структура филиалов и состав их выручки")
st.caption(
    "Каждый столбец — филиал. Внутри столбца можно переключать разрез: по точкам, категориям или подкатегориям. "
    "Полезно для сравнения структуры продаж между филиалами."
)

def prune_selection(options: List[str], selected: Optional[List[str]], default_all: bool = True) -> List[str]:
    """Оставляет только значения, которые есть в options. Если результат пуст — возвращает все options (если default_all)."""
    options_set = set(options)
    selected = selected or []
    cleaned = [x for x in selected if x in options_set]
    if (not cleaned) and default_all:
        return options[:]  # все доступные
    return cleaned

def get_color_order(df_: pd.DataFrame, dim_col: str, value_col: str) -> List[str]:
    """Порядок сегментов по убыванию вклада (глобально, по всем филиалам) — чтобы стек был стабильный."""
    if df_.empty:
        return []
    return (
        df_.groupby(dim_col, as_index=False)[value_col]
           .sum()
           .sort_values(value_col, ascending=False)[dim_col]
           .astype(str)
           .tolist()
    )
base = f.copy()
if base.empty:
    st.warning("По текущим фильтрам данных нет.")
    st.stop()

# наличие колонок
has_cat = "Категория" in base.columns
has_sub = "Подкатегория" in base.columns

# нормализуем типы корректно (без превращения NaN -> "nan")
for col in ["Филиал", "Точки"] + (["Категория"] if has_cat else []) + (["Подкатегория"] if has_sub else []):
    base[col] = base[col].astype("string").str.strip()

with st.expander("Настройки графика", expanded=False):
    c1, c2, c3 = st.columns([0.28, 0.28, 0.44])

    with c1:
        metric = st.selectbox("Метрика", ["Выручка", "Количество"], index=0, key="brstk_metric")

    with c2:
        mode = st.selectbox("Вид", ["100% (доли)", "Абсолютные"], index=0, key="brstk_mode")

    with c3:
        breakdown_options = ["Точки"]
        if has_cat:
            breakdown_options.append("Категория")
        if has_sub:
            breakdown_options.append("Подкатегория")

        breakdown = st.selectbox(
            "Разрез внутри столбца",
            breakdown_options,
            index=0,
            key="brstk_breakdown"
        )

    # ---------- 1) Точки ----------
points_all = sorted(base["Точки"].dropna().astype(str).unique().tolist())

# Инициализация значения по умолчанию ДО создания виджета
if "brstk_points" not in st.session_state:
    st.session_state["brstk_points"] = points_all[:]  # все

# Предыдущее значение (для определения "изменились точки или нет")
prev_points = tuple(st.session_state.get("_brstk_prev_points", st.session_state["brstk_points"]))

# ВАЖНО: после создания виджета НЕЛЬЗЯ писать st.session_state["brstk_points"] = ...
sel_points_local = st.multiselect(
    "Точки (учитывать в графике)",
    options=points_all,
    default=prune_selection(points_all, st.session_state.get("brstk_points"), default_all=True),
    key="brstk_points",
)

points_changed = tuple(sel_points_local) != prev_points
st.session_state["_brstk_prev_points"] = tuple(sel_points_local)

# Срез по точкам — от него считаем доступные категории/подкатегории
tmp0 = base[base["Точки"].isin(sel_points_local)].copy() if sel_points_local else base.iloc[0:0].copy()

# ---------- 2) Категории (зависят от точек) ----------
sel_cats = None
cats_changed = False

if has_cat:
    cats_all = sorted(tmp0["Категория"].dropna().astype(str).unique().tolist())

    # Инициализация ДО виджета
    if "brstk_cats" not in st.session_state:
        st.session_state["brstk_cats"] = cats_all[:]

    # Если изменили точки — сбросить категории на доступные (ДО виджета)
    if points_changed:
        st.session_state["brstk_cats"] = cats_all[:]

    prev_cats = tuple(st.session_state.get("_brstk_prev_cats", st.session_state["brstk_cats"]))

    sel_cats = st.multiselect(
        "Категории (фильтр)",
        options=cats_all,
        default=prune_selection(cats_all, st.session_state.get("brstk_cats"), default_all=True),
        key="brstk_cats",
    )

    cats_changed = tuple(sel_cats) != prev_cats
    st.session_state["_brstk_prev_cats"] = tuple(sel_cats)

# ---------- 3) Подкатегории (зависят от точек + категорий) ----------
sel_subs = None

if has_sub:
    tmp_sub = tmp0.copy()
    if has_cat and sel_cats:
        tmp_sub = tmp_sub[tmp_sub["Категория"].isin(sel_cats)]

    subs_all = sorted(tmp_sub["Подкатегория"].dropna().astype(str).unique().tolist())

    # Инициализация ДО виджета
    if "brstk_subs" not in st.session_state:
        st.session_state["brstk_subs"] = subs_all[:]

    # Если изменили точки или категории — сбросить подкатегории (ДО виджета)
    if points_changed or cats_changed:
        st.session_state["brstk_subs"] = subs_all[:]

    sel_subs = st.multiselect(
        "Подкатегории (фильтр)",
        options=subs_all,
        default=prune_selection(subs_all, st.session_state.get("brstk_subs"), default_all=True),
        key="brstk_subs",
    )


# ----------------------------
# Применяем локальные фильтры (только для этого графика)
# ----------------------------
data = base.copy()

data = data[data["Точки"].isin(sel_points_local)]

if has_cat and sel_cats is not None and len(sel_cats) > 0:
    data = data[data["Категория"].isin(sel_cats)]

if has_sub and sel_subs is not None and len(sel_subs) > 0:
    data = data[data["Подкатегория"].isin(sel_subs)]

if data.empty:
    st.warning("По выбранным настройкам нет данных для построения графика.")
    st.stop()

val_col = "Сумма" if metric == "Выручка" else "Количество"

# Выбираем колонку разреза
if breakdown == "Точки":
    dim = "Точки"
elif breakdown == "Категория":
    dim = "Категория"
else:
    dim = "Подкатегория"

mix = (
    data.groupby(["Филиал", dim], as_index=False)[val_col]
        .sum()
        .rename(columns={val_col: "Значение"})
)

if mix.empty:
    st.warning("Нет данных после группировки.")
    st.stop()

# Порядок сегментов по убыванию (глобально), чтобы стек был "красивый" и стабильный
color_order = get_color_order(mix, dim, "Значение")

if mode == "100% (доли)":
    totals = mix.groupby("Филиал", as_index=False)["Значение"].sum().rename(columns={"Значение": "_total"})
    mix = mix.merge(totals, on="Филиал", how="left")
    mix["Доля"] = mix["Значение"] / mix["_total"].replace({0: 1})

    fig = px.bar(
        mix,
        x="Филиал",
        y="Доля",
        color=dim,
        barmode="stack",
        category_orders={dim: color_order},
        hover_data={"Значение": True, "_total": True, "Доля": ":.1%"},
    )
    fig.update_layout(yaxis_tickformat=".0%", yaxis_title="Доля")
else:
    fig = px.bar(
        mix,
        x="Филиал",
        y="Значение",
        color=dim,
        barmode="stack",
        category_orders={dim: color_order},
        hover_data={"Значение": True},
    )
    fig.update_layout(yaxis_title=metric)

fig.update_layout(legend_title=dim)
st.plotly_chart(fig, use_container_width=True)

# ----------------------------
# Time & Peaks: Heatmap (stable controls + outlier handling)
# ----------------------------
st.markdown("### Time & Peaks")
st.caption("Пики спроса: день недели × час.")

if "Время" not in df.columns:
    st.info("В данных нет колонки 'Время' — heatmap по часам недоступен.")
else:
    # defaults in session_state
    if "heat_params" not in st.session_state:
        st.session_state["heat_params"] = {
            "period": (date_from, date_to),
            "branches": sel_branches,
            "points": sel_points,
            "metric": "Выручка",
            "agg_mode": "Сумма за период",
            "scale_mode": "Обычная",
            "cap_pct": "95%",
        }
    if "heat_ready" not in st.session_state:
        st.session_state["heat_ready"] = False

    with st.expander("Фильтры и настройки Time & Peaks", expanded=False):
        with st.form("heatmap_form", clear_on_submit=False):
            hp = st.session_state["heat_params"]
    
            # 1) период
            h_date_from, h_date_to = st.date_input(
                "Период для Time & Peaks",
                value=hp["period"],
                min_value=min_date,
                max_value=max_date,
                key="heat_period"
            )
    
            # 2) defaults должны быть subset options -> чистим
            default_branches = prune_selection(branches_all, hp.get("branches"), default_all=True)
            default_points   = prune_selection(points_all,   hp.get("points"),   default_all=True)
    
            h_branches = st.multiselect(
                "Филиалы для Time & Peaks",
                options=branches_all,
                default=default_branches,
                key="heat_branches"
            )
    
            # ВАЖНО: если хочешь, чтобы точки зависели от выбранных филиалов — пересчитай options
            # иначе оставь points_all как есть.
            # Пример каскада (рекомендую):
            points_for_heat = sorted(
                df[df["Филиал"].isin(h_branches)]["Точки"].dropna().unique().tolist()
            ) if h_branches else points_all
    
            default_points = prune_selection(points_for_heat, hp.get("points"), default_all=True)
    
            h_points = st.multiselect(
                "Точки для Time & Peaks",
                options=points_for_heat,
                default=default_points,
                key="heat_points"
            )
    
            metric_h = st.selectbox(
                "Метрика",
                ["Выручка", "Количество"],
                index=0 if hp["metric"] == "Выручка" else 1,
                key="heat_metric"
            )
    
            c1, c2, c3 = st.columns(3)
            with c1:
                agg_mode = st.selectbox(
                    "Агрегация",
                    ["Сумма за период", "Среднее по дням"],
                    index=0 if hp["agg_mode"] == "Сумма за период" else 1,
                    key="hm_agg_mode"
                )
            with c2:
                scale_mode = st.selectbox(
                    "Шкала цвета",
                    ["Обычная", "Логарифмическая"],
                    index=0 if hp["scale_mode"] == "Обычная" else 1,
                    key="hm_scale_mode"
                )
            with c3:
                cap_pct = st.selectbox(
                    "Ограничить пики (перцентиль)",
                    ["Без ограничений", "95%", "99%"],
                    index=1 if hp["cap_pct"] == "95%" else (2 if hp["cap_pct"] == "99%" else 0),
                    key="hm_cap_pct"
                )
    
            build_heat = st.form_submit_button("Построить heatmap")
    
            if build_heat:
                st.session_state["heat_params"] = {
                    "period": (h_date_from, h_date_to),
                    "branches": h_branches,
                    "points": h_points,
                    "metric": metric_h,
                    "agg_mode": agg_mode,
                    "scale_mode": scale_mode,
                    "cap_pct": cap_pct,
                }
                st.session_state["heat_ready"] = True


    # рендер: если уже строили хотя бы раз — показываем последний результат
    if not st.session_state["heat_ready"]:
        st.info("Выберите параметры и нажмите «Построить heatmap».")
    else:
        hp = st.session_state["heat_params"]
        h_date_from, h_date_to = hp["period"]
        h_branches, h_points = hp["branches"], hp["points"]
        metric_h, agg_mode = hp["metric"], hp["agg_mode"]
        scale_mode, cap_pct = hp["scale_mode"], hp["cap_pct"]

        with st.spinner("Строю heatmap..."):
            heat = df.copy()

            # ВАЖНО: df['Дата'] уже date -> сравниваем date с date (без dtype конфликтов)
            heat = heat[(heat["Дата"] >= h_date_from) & (heat["Дата"] <= h_date_to)]
            heat = heat[heat["Филиал"].isin(h_branches)] if h_branches else heat
            heat = heat[heat["Точки"].isin(h_points)] if h_points else heat

            if heat.empty:
                st.warning("По выбранным фильтрам Time & Peaks нет данных.")
            else:
                heat["_dt"] = pd.to_datetime(heat["Дата"], errors="coerce")
                heat["_hour"] = extract_hour_fast(heat["Время"])
                heat = heat[heat["_dt"].notna() & heat["_hour"].notna()]

                if heat.empty:
                    st.warning("Не удалось извлечь час из 'Время'. Проверьте формат времени (например 10:35 или 10:35:12).")
                else:
                    heat["_dow"] = heat["_dt"].dt.dayofweek
                    dow_map = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}
                    heat["_dow_name"] = heat["_dow"].map(dow_map)

                    val_col = "Сумма" if metric_h == "Выручка" else "Количество"

                    if agg_mode == "Сумма за период":
                        h = heat.groupby(["_dow_name", "_hour"], as_index=False)[val_col].sum()
                    else:
                        daily = (
                            heat.groupby([heat["_dt"].dt.date, "_dow_name", "_hour"], as_index=False)[val_col]
                                .sum()
                        )
                        h = daily.groupby(["_dow_name", "_hour"], as_index=False)[val_col].mean()

                    dow_order = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                    h["_dow_name"] = pd.Categorical(h["_dow_name"], categories=dow_order, ordered=True)

                    heat_p = h.pivot(index="_dow_name", columns="_hour", values=val_col).fillna(0)

                    # cap выбросов для понятной палитры
                    if cap_pct != "Без ограничений":
                        p = 95 if cap_pct == "95%" else 99
                        flat = heat_p.to_numpy().ravel()
                        vmax = float(np.quantile(flat, p / 100.0))
                        if vmax > 0:
                            heat_p = heat_p.clip(upper=vmax)

                    # log scale
                    if scale_mode == "Логарифмическая":
                        heat_p = np.log1p(heat_p)
                        color_label = f"{metric_h} (log1p)"
                    else:
                        color_label = metric_h

                    fig_hm = px.imshow(
                        heat_p,
                        aspect="auto",
                        labels=dict(x="Час", y="День недели", color=color_label),
                    )
                    st.plotly_chart(fig_hm, use_container_width=True)

st.divider()

# ----------------------------
# Export
# ----------------------------
st.markdown("### Export")
st.caption("Выгрузка строк продаж с учётом текущих фильтров (до агрегирования).")

csv = f.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "Скачать текущий срез (CSV)",
    data=csv,
    file_name="sales_slice_filtered.csv",
    mime="text/csv"
)
