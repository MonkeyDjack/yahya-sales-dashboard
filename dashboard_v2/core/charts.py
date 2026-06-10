"""Plotly-графики в единой теме дашборда."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from core.config import COLORS, A_THR, B_THR

COLORWAY = [COLORS["primary"], COLORS["accent"], COLORS["teal"], COLORS["violet"],
            COLORS["danger"], COLORS["ok"], "#7F8C8D", "#D35400"]


def apply_theme(fig: go.Figure, title: str | None = None, height: int | None = None) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        colorway=COLORWAY,
        font=dict(size=12),
        hovermode="x unified",
        separators=". ",  # десятичная точка, пробел между тысячами
        margin=dict(l=10, r=10, t=46 if title else 16, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    if title:
        fig.update_layout(title=dict(text=title, font=dict(size=14, color=COLORS["primary"])))
    if height:
        fig.update_layout(height=height)
    return fig


def line_ts(df: pd.DataFrame, x: str, y: str, color: str | None = None,
            area: bool = False, title: str = "", y_title: str = "") -> go.Figure:
    """Простой временной ряд; color — колонка для разбивки на серии."""
    fig = go.Figure()
    if color:
        for i, (name, grp) in enumerate(df.groupby(color, sort=False, observed=True)):
            fig.add_trace(go.Scatter(
                x=grp[x], y=grp[y], name=str(name), mode="lines+markers",
                marker=dict(size=5), line=dict(width=1.8),
            ))
    else:
        fig.add_trace(go.Scatter(
            x=df[x], y=df[y], name=y_title or y, mode="lines+markers",
            marker=dict(size=5), line=dict(width=2, color=COLORS["primary"]),
            fill="tozeroy" if area else None,
            fillcolor="rgba(31,78,121,0.12)" if area else None,
        ))
    fig.update_yaxes(title=y_title or None, rangemode="tozero")
    return apply_theme(fig, title)


def compare_ts(cur: pd.Series, refs: dict[str, pd.Series],
               cur_label: str = "Текущий", y_title: str = "") -> go.Figure:
    """Текущий ряд (сплошной + заливка) и базовые ряды (пунктир).
    Индексы refs должны быть уже выровнены на текущий период."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=cur.index, y=cur.values, name=cur_label, mode="lines+markers",
        marker=dict(size=5), line=dict(width=2.2, color=COLORS["primary"]),
        fill="tozeroy", fillcolor="rgba(31,78,121,0.10)",
    ))
    palette = [COLORS["accent"], COLORS["teal"], COLORS["violet"], COLORS["danger"]]
    for i, (label, s) in enumerate(refs.items()):
        if s is None or s.empty:
            continue
        fig.add_trace(go.Scatter(
            x=s.index, y=s.values, name=label, mode="lines",
            line=dict(width=1.5, dash="dash", color=palette[i % len(palette)]),
        ))
    fig.update_yaxes(title=y_title or None, rangemode="tozero")
    return apply_theme(fig)


def pareto(df: pd.DataFrame, label_col: str, value_col: str, cum_col: str,
           title: str = "") -> go.Figure:
    """Pareto: бары + кумулятивная доля на второй оси + пороги A/B."""
    labels = df[label_col].astype(str).tolist()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=df[value_col], name=value_col,
        marker_color=COLORS["primary"], opacity=0.85,
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=df[cum_col], name="Кум. доля", yaxis="y2",
        mode="lines+markers", marker=dict(size=5), line=dict(color=COLORS["danger"], width=1.8),
    ))
    fig.update_layout(
        yaxis=dict(title=value_col),
        yaxis2=dict(overlaying="y", side="right", range=[0, 1.05],
                    tickformat=".0%", showgrid=False),
        xaxis=dict(tickangle=-60, tickfont=dict(size=9)),
    )
    fig.add_hline(y=A_THR, yref="y2", line_dash="dash", line_color=COLORS["ok"],
                  annotation_text="A: 80%", annotation_position="right")
    fig.add_hline(y=B_THR, yref="y2", line_dash="dash", line_color=COLORS["accent"],
                  annotation_text="B: 95%", annotation_position="right")
    fig = apply_theme(fig, title, height=460)
    fig.update_layout(hovermode="x")
    return fig


def heatmap(pv: pd.DataFrame, colorscale: str = "YlOrRd",
            text_fmt: str | None = None, text_min: float = 0.0,
            hover_fmt: str = ",.0f", title: str = "",
            height: int | None = None) -> go.Figure:
    """Heatmap из сводной таблицы (index=строки, columns=колонки).
    text_fmt — формат подписи ячейки, text_min — порог значения для подписи."""
    text = None
    if text_fmt:
        text = [[text_fmt.format(v) if v and v >= text_min else "" for v in row]
                for row in pv.values]
    fig = go.Figure(go.Heatmap(
        z=pv.values, x=[str(c) for c in pv.columns], y=[str(i) for i in pv.index],
        colorscale=colorscale, text=text,
        texttemplate="%{text}" if text else None,
        textfont=dict(size=9),
        hovertemplate="%{y} · %{x}: %{z:" + hover_fmt + "}<extra></extra>",
        colorbar=dict(thickness=12),
    ))
    fig.update_yaxes(autorange="reversed")
    fig = apply_theme(fig, title, height=height or max(300, 28 * len(pv) + 80))
    fig.update_layout(hovermode="closest")
    return fig


def stacked_bar(df: pd.DataFrame, x: str, y: str, color: str,
                title: str = "", y_title: str = "") -> go.Figure:
    """Stacked bar: x — категории, color — слои стека."""
    fig = go.Figure()
    for name, grp in df.groupby(color, sort=False, observed=True):
        fig.add_trace(go.Bar(
            x=grp[x], y=grp[y], name=str(name),
            hovertemplate="%{x} · " + str(name) + ": %{y:,.0f}<extra></extra>",
        ))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title=y_title or None)
    return apply_theme(fig, title)


def barh_top(df: pd.DataFrame, label_col: str, value_col: str, n: int = 10,
             title: str = "", color: str | None = None) -> go.Figure:
    d = df.head(n).iloc[::-1]
    fig = go.Figure(go.Bar(
        x=d[value_col], y=d[label_col].astype(str), orientation="h",
        marker_color=color or COLORS["primary"],
        hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
    ))
    fig = apply_theme(fig, title, height=max(240, 32 * len(d) + 70))
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title=value_col)
    return fig
