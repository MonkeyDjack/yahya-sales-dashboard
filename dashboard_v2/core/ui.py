"""CSS, инсайт-карточки и информационные бейджи."""
from __future__ import annotations

from datetime import date

import streamlit as st

CSS = """
<style>
  .stTabs [data-baseweb="tab-list"] { gap: 2px; flex-wrap: wrap; }
  .stTabs [data-baseweb="tab"] { padding: 6px 12px; font-size: 14px; }
  div[data-testid="stMetric"] {
      background: #FAFBFC !important;
      border: 1px solid #E1E4E8;
      border-radius: 8px;
      padding: 10px 14px;
      color: #1F3864 !important;
  }
  div[data-testid="stMetric"] label,
  div[data-testid="stMetric"] p,
  div[data-testid="stMetric"] span,
  div[data-testid="stMetricLabel"],
  div[data-testid="stMetricLabel"] * { color: #4B6C97 !important; font-weight: 600; }
  div[data-testid="stMetricValue"],
  div[data-testid="stMetricValue"] *,
  div[data-testid="stMetricValue"] div { color: #0B2447 !important; font-weight: 700; }
  div[data-testid="stMetricDelta"] { font-weight: 600; }
  .insight-card {
      background: linear-gradient(135deg, #fafbfd 0%, #f0f4fa 100%) !important;
      border-left: 4px solid #1F4E79;
      border-radius: 6px;
      padding: 10px 14px;
      margin-bottom: 10px;
      color: #1F3864 !important;
  }
  .insight-card.warn   { border-left-color: #E67E22; }
  .insight-card.danger { border-left-color: #C0392B; }
  .insight-card.ok     { border-left-color: #27AE60; }
  .insight-card * { color: inherit !important; }
  .insight-title { font-weight: 700; font-size: 13px; color: #1F3864 !important; margin-bottom: 4px; }
  .insight-body  { font-size: 12px; color: #333 !important; line-height: 1.5; }
  .insight-body b { color: #1F3864 !important; }
  .fresh-badge {
      display: inline-block; border-radius: 14px; padding: 3px 12px;
      font-size: 12.5px; font-weight: 600; margin-bottom: 4px;
  }
  .fresh-green  { background: #E8F8F0; color: #1E8449; }
  .fresh-yellow { background: #FEF5E7; color: #B9770E; }
  .fresh-red    { background: #FDEDEC; color: #A93226; }
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def insight_card(title: str, body: str, kind: str = "") -> None:
    st.markdown(
        f"<div class='insight-card {kind}'>"
        f"<div class='insight-title'>{title}</div>"
        f"<div class='insight-body'>{body}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def freshness_badge(max_data_date: date) -> None:
    """Бейдж свежести: по какую дату данные и сколько дней назад это было."""
    lag = (date.today() - max_data_date).days
    if lag <= 2:
        cls, icon, note = "fresh-green", "🟢", ""
    elif lag <= 7:
        cls, icon, note = "fresh-yellow", "🟡", ""
    else:
        cls, icon, note = "fresh-red", "🔴", " — данные устарели"
    when = "сегодня" if lag == 0 else f"{lag} дн. назад"
    st.markdown(
        f"<span class='fresh-badge {cls}'>{icon} Данные по {max_data_date:%d.%m.%Y} · {when}{note}</span>",
        unsafe_allow_html=True,
    )


def own_period_note() -> None:
    st.caption("📌 Эта страница использует **собственный период** — глобальный период из "
               "sidebar здесь не применяется (фильтры филиалов/категорий применяются).")


def full_history_warning(min_d: date, max_d: date) -> None:
    st.warning(
        f"⚠️ Раздел считается по **всей истории** ({min_d:%d.%m.%Y} – {max_d:%d.%m.%Y}), "
        f"глобальный период не применяется. Месяцы, представленные только одним годом, "
        f"отражают один сезон — сравнивай аккуратно."
    )
