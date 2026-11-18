"""PumpFun Launch Intelligence Streamlit dashboard (research only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Allow `streamlit run pumpfun_intel/dashboard/app.py`
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pumpfun_intel.dashboard.data_access import (
    cached_analysis_bundle,
    clear_analysis_cache,
    db_path,
    load_coverage,
    load_events,
    load_launches,
    load_participants,
)
from pumpfun_intel.reporting.final_report import generate_final_report
from pumpfun_intel.dashboard.data_access import get_db
from pumpfun_intel.config import PROJECT_ROOT

st.set_page_config(
    page_title="PumpFun Launch Intelligence",
    page_icon="📈",
    layout="wide",
)

st.title("PumpFun Launch Intelligence")
st.caption("Research / analytics only. No trading, signing, or execution.")
st.sidebar.caption(f"DB: {db_path().name}")


def _filters(launches: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filters")
    if launches.empty:
        st.sidebar.warning("No launches in database yet. Run collect + analyze first.")
        return launches

    min_dt = launches["create_dt"].min()
    max_dt = launches["create_dt"].max()
    date_range = st.sidebar.date_input(
        "Date range (UTC)",
        value=(min_dt.date(), max_dt.date()),
    )
    symbols = sorted({s for s in launches["symbol"].dropna().astype(str).tolist()})
    symbol_sel = st.sidebar.multiselect("Token symbol", options=symbols, default=[])
    mint_q = st.sidebar.text_input("Mint contains")

    df = launches.copy()
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
        df = df[
            (df["create_dt"].dt.date >= start) & (df["create_dt"].dt.date <= end)
        ]
    if symbol_sel:
        df = df[df["symbol"].isin(symbol_sel)]
    if mint_q:
        df = df[df["mint"].astype(str).str.contains(mint_q, case=False, na=False)]
    st.sidebar.write(f"Filtered launches: **{len(df)}** / {len(launches)}")
    if st.sidebar.button("Refresh derived analytics cache"):
        clear_analysis_cache()
        st.sidebar.success("Cache cleared")
    return df


def page_overview(launches: pd.DataFrame, creator: str) -> None:
    st.subheader("1. Target wallet overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Target wallet", creator[:8] + "…")
    c2.metric("Launches", len(launches))
    if not launches.empty:
        sols = launches["initial_buy_sol"].dropna()
        c3.metric("Median open SOL", f"{sols.median():.3f}" if len(sols) else "n/a")
        c4.metric("Sell-seen rate", f"{(launches['sell_count']>0).mean():.0%}")
        fig = px.histogram(
            launches.dropna(subset=["initial_buy_sol"]),
            x="initial_buy_sol",
            nbins=40,
            title="Initial buy SOL distribution",
        )
        st.plotly_chart(fig, use_container_width=True)
        daily = (
            launches.dropna(subset=["create_dt"])
            .assign(day=lambda d: d["create_dt"].dt.floor("D"))
            .groupby("day")
            .size()
            .reset_index(name="launches")
        )
        st.plotly_chart(
            px.bar(daily, x="day", y="launches", title="Launches per day (UTC)"),
            use_container_width=True,
        )


def page_history(launches: pd.DataFrame) -> None:
    st.subheader("2. Token launch history")
    cols = [
        c
        for c in [
            "create_dt",
            "symbol",
            "name",
            "mint",
            "initial_buy_sol",
            "early_buyer_count",
            "sell_count",
            "migrated",
            "create_signature",
        ]
        if c in launches.columns
    ]
    st.dataframe(launches[cols], use_container_width=True, height=480)


def page_launch_detail(launches: pd.DataFrame) -> None:
    st.subheader("3. Individual launch analysis")
    if launches.empty:
        st.info("No launches")
        return
    labels = [
        f"{r.create_dt} | {r.symbol or '?'} | {r.mint[:8]}…"
        for r in launches.itertuples()
    ]
    choice = st.selectbox("Select launch", options=list(range(len(labels))), format_func=lambda i: labels[i])
    row = launches.iloc[choice]
    st.write(row)
    ev = load_events(str(row["mint"]))
    parts = load_participants()
    parts = parts[parts["mint"] == row["mint"]] if not parts.empty else parts
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Participants**")
        st.dataframe(parts, use_container_width=True)
    with c2:
        st.markdown("**Classified events**")
        st.dataframe(ev, use_container_width=True)
    if not ev.empty and "block_dt" in ev.columns:
        timeline = ev[ev["event_type"].isin(["buy", "sell", "pumpswap_buy", "pumpswap_sell", "create"])]
        if not timeline.empty:
            fig = px.scatter(
                timeline,
                x="block_dt",
                y="sol_amount",
                color="event_type",
                hover_data=["wallet", "signature"],
                title="Buy/sell timeline (observed)",
            )
            st.plotly_chart(fig, use_container_width=True)


def page_relationships(bundle: dict) -> None:
    st.subheader("4. Wallet relationship graph")
    st.caption("Evidence levels do **not** prove shared control.")
    df = bundle["relations_df"]
    if df.empty:
        st.warning("No relationships with current thresholds")
        return
    level = st.multiselect(
        "Evidence level",
        ["strong", "moderate", "weak"],
        default=["strong", "moderate", "weak"],
    )
    view = df[df["evidence_level"].isin(level)].head(100)
    st.dataframe(view, use_container_width=True)

    # Simple force-style plot via Plotly scatter edges (node positions by degree)
    nodes = sorted(set(view["wallet_a"]) | set(view["wallet_b"]))
    idx = {n: i for i, n in enumerate(nodes)}
    # circular layout
    import math

    pos = {
        n: (math.cos(2 * math.pi * i / max(len(nodes), 1)), math.sin(2 * math.pi * i / max(len(nodes), 1)))
        for i, n in enumerate(nodes)
    }
    edge_x, edge_y = [], []
    for r in view.itertuples():
        x0, y0 = pos[r.wallet_a]
        x1, y1 = pos[r.wallet_b]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", line=dict(width=0.5, color="#888"), hoverinfo="none"))
    fig.add_trace(
        go.Scatter(
            x=[pos[n][0] for n in nodes],
            y=[pos[n][1] for n in nodes],
            mode="markers+text",
            text=[n[:4] + "…" for n in nodes],
            textposition="top center",
            marker=dict(size=10),
            hovertext=nodes,
        )
    )
    fig.update_layout(title="Relationship graph (top edges)", showlegend=False, height=560)
    st.plotly_chart(fig, use_container_width=True)


def page_funding(bundle: dict) -> None:
    st.subheader("5. Funding flow analysis")
    st.info(
        "Direct creator funding was weak/absent in parsed SOL transfers. "
        "Relationships below highlight funding-related reasons when present."
    )
    df = bundle["relations_df"]
    if df.empty:
        return
    funded = df[df["reasons"].str.contains("SOL transfer", case=False, na=False)]
    st.dataframe(funded if not funded.empty else df.head(30), use_container_width=True)


def page_initial_buy(launches: pd.DataFrame) -> None:
    st.subheader("6. Initial buy distribution")
    if launches.empty:
        return
    fig = px.box(launches, y="initial_buy_sol", points="all", title="Initial buy SOL")
    st.plotly_chart(fig, use_container_width=True)
    buckets = pd.cut(
        launches["initial_buy_sol"],
        bins=[-0.01, 0.05, 1, 3.5, 4.5, 5.5, 1000],
        labels=["dust", "small", "~3", "~4", "~5", "other"],
    )
    st.bar_chart(buckets.value_counts().sort_index())


def page_timeline(launches: pd.DataFrame) -> None:
    st.subheader("7. Buy/sell timeline")
    if launches.empty:
        return
    mint = st.selectbox("Mint", launches["mint"].tolist())
    ev = load_events(mint)
    if ev.empty:
        st.warning("No events for mint")
        return
    fig = px.scatter(
        ev,
        x="block_dt",
        y="sol_amount",
        color="event_type",
        hover_data=["wallet", "signature"],
    )
    st.plotly_chart(fig, use_container_width=True)


def page_performance(bundle: dict, launches: pd.DataFrame) -> None:
    st.subheader("8. Token performance comparison")
    perf = bundle["performance"]
    if perf is None or perf.empty:
        st.warning("No performance windows computed")
        return
    window = st.selectbox("Window", ["30s", "1m", "5m", "15m", "30m", "1h"], index=2)
    view = perf[perf["window"] == window]
    if not launches.empty:
        view = view[view["mint"].isin(set(launches["mint"]))]
    st.caption("Proxy metrics from observed events only, not full-market PnL.")
    st.dataframe(view, use_container_width=True, height=420)
    if not view.empty:
        st.plotly_chart(
            px.scatter(
                view,
                x="buy_sol_volume",
                y="unique_buyers",
                hover_data=["symbol", "mint"],
                title=f"{window}: volume vs unique buyers (observed)",
            ),
            use_container_width=True,
        )


def page_discovery(bundle: dict) -> None:
    st.subheader("9. Pattern discovery report")
    d = bundle["discovery"]
    st.markdown("### Consistent patterns")
    for x in d.get("consistent_patterns", []):
        st.success(x)
    st.markdown("### Observations (not causation)")
    for x in d.get("observations", []):
        st.write(f"- {x}")
    st.markdown("### Not sufficiently supported")
    for x in d.get("unsupported", []):
        st.warning(x)
    tables = d.get("tables") or {}
    for name, t in tables.items():
        st.markdown(f"**{name}**")
        st.dataframe(t, use_container_width=True)


def page_coverage(launches: pd.DataFrame) -> None:
    st.subheader("10. Data coverage & confidence")
    cov = load_coverage()
    st.dataframe(cov, use_container_width=True)
    st.markdown(
        """
        **Confidence notes**
        - Classification uses program IDs + instruction discriminators
        - Creator-wallet history undercounts external bundler buys until mint probes
        - Performance prices/volumes are proxies from decoded legs
        - Missing txs are recorded; never fabricated
        """
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Launches in view", len(launches))
    c2.metric("Coverage rows", len(cov))
    c3.metric("DB", str(get_db().db_path.name))


def page_export() -> None:
    st.subheader("Export final report")
    if st.button("Generate Markdown + CSV final report"):
        db = get_db()
        try:
            paths = generate_final_report(db, PROJECT_ROOT / "data" / "reports")
            st.success("Report generated")
            for k, p in paths.items():
                st.write(f"{k}: `{p}`")
                if p.suffix == ".md":
                    st.download_button(
                        "Download Markdown",
                        data=p.read_text(encoding="utf-8"),
                        file_name=p.name,
                        mime="text/markdown",
                    )
                elif p.suffix == ".csv" and k == "launches":
                    st.download_button(
                        "Download launches CSV",
                        data=p.read_bytes(),
                        file_name=p.name,
                        mime="text/csv",
                    )
        finally:
            db.close()


def main() -> None:
    launches_all = load_launches()
    filtered = _filters(launches_all)
    with st.spinner("Computing analytics bundle…"):
        bundle = cached_analysis_bundle()
    creator = bundle["creator"]

    page = st.sidebar.radio(
        "Views",
        [
            "Overview",
            "Launch history",
            "Launch detail",
            "Relationships",
            "Funding",
            "Initial buys",
            "Buy/sell timeline",
            "Performance",
            "Pattern discovery",
            "Coverage",
            "Export report",
        ],
    )
    if page == "Overview":
        page_overview(filtered, creator)
    elif page == "Launch history":
        page_history(filtered)
    elif page == "Launch detail":
        page_launch_detail(filtered)
    elif page == "Relationships":
        page_relationships(bundle)
    elif page == "Funding":
        page_funding(bundle)
    elif page == "Initial buys":
        page_initial_buy(filtered)
    elif page == "Buy/sell timeline":
        page_timeline(filtered)
    elif page == "Performance":
        page_performance(bundle, filtered)
    elif page == "Pattern discovery":
        page_discovery(bundle)
    elif page == "Coverage":
        page_coverage(filtered)
    else:
        page_export()


if __name__ == "__main__":
    main()
