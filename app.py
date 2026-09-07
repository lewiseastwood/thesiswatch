"""ThesisWatch dashboard.

    streamlit run app.py

Reads persisted runs from runs/ and theses from theses/. All analysis, EDGAR
access and verification lives in thesiswatch.py — this module only presents it.

Analyst-support tool. Does not produce buy/sell recommendations.
"""

import os
import sys

import anthropic
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import thesiswatch
from thesiswatch import (BAND_LABELS, Context, Edgar, available_tickers,
                         band_pct, evaluate_claim, load_runs, load_thesis,
                         quarterly_yoy, save_run, tidy_excerpt)

FORM = "10-Q"

# Muted, and deliberately not a red/green judgement on the company: the colour
# tracks whether the filing moved the claim, which is what the verdict means.
VERDICT_COLOR = {
    "weakened": "#a4453b",
    "strengthened": "#3f6b52",
    "unchanged": "#4a5568",
    "insufficient_evidence": "#8a8a8a",
}
INK = "#2f3437"
MUTED = "#6b7280"
RULE = "#d9dcdf"
MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"

st.set_page_config(page_title="ThesisWatch", layout="wide")
st.markdown(f"""
<style>
  .block-container {{ padding-top: 2.2rem; max-width: 1200px; }}
  .tw-card {{ border: 1px solid {RULE}; border-left: 3px solid var(--vc);
              padding: .7rem .9rem; height: 100%; }}
  .tw-card .id {{ font-family: {MONO}; font-size: .72rem; color: {MUTED};
                  letter-spacing: .06em; }}
  .tw-card .verdict {{ font-size: 1.05rem; font-weight: 600; color: var(--vc);
                       margin: .15rem 0 .35rem; }}
  .tw-card .meta {{ font-family: {MONO}; font-size: .74rem; color: {MUTED};
                    line-height: 1.5; }}
  .tw-head {{ font-family: {MONO}; font-size: .78rem; color: {MUTED}; }}
  .tw-head a {{ color: {MUTED}; }}
  .tw-quote {{ border-left: 2px solid {RULE}; padding: .1rem 0 .1rem .8rem;
               margin: .5rem 0 .2rem; color: {INK}; }}
  .tw-src {{ font-family: {MONO}; font-size: .72rem; color: {MUTED};
             padding-left: .8rem; }}
  .tw-badge {{ font-family: {MONO}; font-size: .72rem; border: 1px solid {RULE};
               padding: .05rem .4rem; color: {MUTED}; }}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------- data
@st.cache_resource
def edgar() -> Edgar:
    load_dotenv()
    email = os.getenv("SEC_UA_EMAIL", "").strip()
    if not email:
        st.error("SEC_UA_EMAIL is missing from .env. EDGAR rejects requests "
                 "without a contact address.")
        st.stop()
    thesiswatch.SEC_UA = f"ThesisWatch research/0.1 ({email})"
    return Edgar(thesiswatch.SEC_UA)


@st.cache_data(show_spinner=False)
def metric_history(ticker: str, tag: str) -> list[dict]:
    """Full tagged history for one concept, as quarterly YoY points."""
    e = edgar()
    return quarterly_yoy(e.concept(e.cik(ticker), tag))


def bound_metrics(thesis: dict) -> list[tuple[str, dict]]:
    """Every (tag, bands) pair the thesis binds."""
    return [(b["tag"], b.get("bands") or {})
            for c in thesis.get("claims", []) for b in c.get("bindings", [])]


# ---------------------------------------------------------------- panes
def header(run: dict) -> None:
    f = run["filings"]
    st.markdown(f"## {run['ticker']} · {run.get('thesis_name', '')}")
    cur, pri = f["current"], f["prior"]
    st.markdown(
        f"<div class='tw-head'>"
        f"{run.get('form', FORM)} &nbsp;·&nbsp; current filed {cur['filingDate']} "
        f"(period {cur['reportDate']}) "
        f"<a href='{cur['index_url']}'>{cur['accessionNumber']}</a>"
        f" &nbsp;·&nbsp; prior filed {pri['filingDate']} "
        f"(period {pri['reportDate']}) "
        f"<a href='{pri['index_url']}'>{pri['accessionNumber']}</a>"
        f" &nbsp;·&nbsp; run {run.get('run_at', 'unknown')}</div>",
        unsafe_allow_html=True)


def review_queue(claims: list[dict]) -> None:
    """Pinned near the top: the things a threshold check would never surface."""
    flags = [(c["claim_id"], n) for c in claims for n in c.get("needs_review", [])]
    st.markdown(
        f"#### Requires analyst review "
        f"<span class='tw-badge'>{len(flags)}</span>", unsafe_allow_html=True)
    if not flags:
        st.markdown(f"<div class='tw-head'>No automated flags raised on this run. "
                    f"That is not a clean bill of health — verify figures against "
                    f"the filing.</div>", unsafe_allow_html=True)
        return
    for cid, note in flags:
        st.markdown(f"- <span class='tw-badge'>{cid}</span> {note}",
                    unsafe_allow_html=True)


def summary_strip(claims: list[dict]) -> None:
    for col, c in zip(st.columns(len(claims)), claims):
        colour = VERDICT_COLOR.get(c["verdict"], MUTED)
        band = BAND_LABELS.get(c.get("band", "not_applicable"), "—").replace("*", "")
        n_ex, n_me = len(c.get("excerpts", [])), len(c.get("metrics", []))
        col.markdown(
            f"<div class='tw-card' style='--vc:{colour}'>"
            f"<div class='id'>{c['claim_id']}</div>"
            f"<div class='verdict'>{c['verdict'].replace('_', ' ')}</div>"
            f"<div class='meta'>band &nbsp;{band}<br>"
            f"confidence &nbsp;{c.get('confidence', '—')}<br>"
            f"evidence &nbsp;{n_ex} excerpt{'s' * (n_ex != 1)}, "
            f"{n_me} metric{'s' * (n_me != 1)}</div></div>",
            unsafe_allow_html=True)


def trend_chart(ticker: str, thesis: dict) -> None:
    """YoY growth per quarter against the claim's bands.

    The bands are the point of the chart: a single threshold looks fine until
    the quarter it does not, and a line approaching the watch level is the
    thing a verdict of "unchanged" will not tell you.
    """
    bindings = bound_metrics(thesis)
    if not bindings:
        st.markdown(f"<div class='tw-head'>This thesis binds no XBRL metric, so "
                    f"there is no series to plot.</div>", unsafe_allow_html=True)
        return

    for tag, bands in bindings:
        points = [p for p in metric_history(ticker, tag) if p["yoy"] is not None]
        if not points:
            st.markdown(f"<div class='tw-head'>No quarterly YoY series available "
                        f"for <code>{tag}</code>.</div>", unsafe_allow_html=True)
            continue

        window = points[-24:]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=[p["end"] for p in window], y=[p["yoy"] for p in window],
            mode="lines+markers", name="YoY growth",
            line={"color": INK, "width": 1.6},
            marker={"size": 5, "color": INK},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f}%<extra></extra>"))

        for level, colour, dash in (("watch", VERDICT_COLOR["weakened"], "dot"),
                                    ("falsified", "#7a2f28", "dash")):
            pct = band_pct(bands.get(level))
            if pct is None:
                continue
            fig.add_hline(
                y=pct, line={"color": colour, "width": 1.2, "dash": dash},
                annotation={"text": f"{level} {pct:g}%", "font": {"size": 10,
                            "color": colour, "family": MONO},
                            "bgcolor": "rgba(255,255,255,.75)"},
                annotation_position="top left")

        latest = window[-1]
        fig.update_layout(
            height=340, margin={"l": 8, "r": 8, "t": 28, "b": 8},
            plot_bgcolor="white", paper_bgcolor="white", showlegend=False,
            title={"text": f"{tag} — YoY growth by quarter "
                           f"(latest {latest['yoy']:.2f}%)",
                   "font": {"size": 13, "color": INK, "family": MONO}},
            font={"family": MONO, "size": 11, "color": MUTED},
            xaxis={"showgrid": False, "linecolor": RULE, "ticks": "outside"},
            yaxis={"ticksuffix": "%", "gridcolor": "#eef0f2", "zeroline": True,
                   "zerolinecolor": RULE, "linecolor": RULE})
        st.plotly_chart(fig, width="stretch")


def claim_panel(c: dict) -> None:
    band = BAND_LABELS.get(c.get("band", "not_applicable"), "—").replace("*", "")
    label = (f"{c['claim_id']} — {c['verdict'].replace('_', ' ')}"
             f"{'' if band == '—' else f' · band {band}'} — {c['statement']}")
    with st.expander(label):
        st.markdown(c.get("reasoning", "") or "_No reasoning recorded._")

        metrics = c.get("metrics", [])
        if metrics:
            st.markdown("**Metrics**")
            st.dataframe(
                [{"tag": m.get("tag"), "period": m.get("period"),
                  "value": f"{m.get('value', 0):,.0f}", "note": m.get("note", "")}
                 for m in metrics],
                hide_index=True, width="stretch")

        # Only verified excerpts are persisted, but the check is repeated here
        # rather than assumed. Rendering an unverified quote as evidence is the
        # exact failure this gate exists to prevent.
        shown = [e for e in c.get("excerpts", []) if e.get("verified")]
        if shown:
            st.markdown(f"**Verified excerpts** "
                        f"<span class='tw-badge'>{len(shown)}</span>",
                        unsafe_allow_html=True)
        for e in shown:
            st.markdown(
                f"<div class='tw-quote'>{tidy_excerpt(e.get('text', ''))}</div>"
                f"<div class='tw-src'>✓ verified &nbsp;·&nbsp; "
                f"{e.get('filing', '?')} filing &nbsp;·&nbsp; "
                f"{e.get('section', '?')}</div>", unsafe_allow_html=True)
        if not shown:
            st.markdown(f"<div class='tw-head'>No excerpt passed verification for "
                        f"this claim.</div>", unsafe_allow_html=True)


# ------------------------------------------------------------ live run
def execute_run(ticker: str) -> dict | None:
    """Run the existing pipeline, streaming each tool call as it happens."""
    load_dotenv()
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key or key.startswith("sk-ant-REPLACE_ME"):
        st.error("ANTHROPIC_API_KEY is missing. Add a real key to .env.")
        return None

    thesiswatch.MODEL = os.getenv("THESISWATCH_MODEL", "").strip() or thesiswatch.MODEL
    try:
        thesis = load_thesis(ticker)
    except (FileNotFoundError, ValueError) as e:
        st.error(str(e))
        return None

    e = edgar()
    with st.status(f"Fetching {FORM} filings for {ticker}", expanded=True) as s:
        cik = e.cik(ticker)
        filings = e.filings(cik, FORM, limit=2)
        if len(filings) < 2:
            s.update(label=f"Need two {FORM} filings to diff; EDGAR returned "
                           f"{len(filings)}", state="error")
            return None
        current, prior = filings[0], filings[1]
        st.write(f"current {current['filingDate']} · prior {prior['filingDate']}")
        ctx = Context(e, cik, current, prior)
        st.write("sections: " + ", ".join(sorted(ctx.sections["current"])))
        s.update(label=f"{ticker} filings loaded", state="complete")

    verdicts = []
    for claim in thesis["claims"]:
        with st.status(f"{claim['id']} — investigating", expanded=True) as s:
            def show(name: str, args: dict, _s=s) -> None:
                if name == "submit_verdict":
                    _s.write("**submit_verdict** — recording judgement")
                    return
                detail = ", ".join(f"{k}={str(val)[:60]}" for k, val in args.items())
                _s.write(f"`{name}` &nbsp; {detail}")

            v = evaluate_claim(client(key), ctx, claim, on_tool=show)
            verdicts.append(v)
            s.update(label=f"{claim['id']} — {v.verdict.replace('_', ' ')} "
                           f"({v.tool_calls} tool calls, "
                           f"{len(v.excerpts)} verified excerpts)",
                     state="complete")

    save_run(ticker, thesis, ctx, verdicts)
    st.cache_data.clear()
    return {"ticker": ticker}


@st.cache_resource
def client(key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=key)


# --------------------------------------------------------------- layout
def main() -> None:
    tickers = available_tickers()
    if not tickers:
        st.error("No theses found in theses/. Add a {TICKER}.yaml first.")
        return

    with st.sidebar:
        st.markdown("### ThesisWatch")
        # Open on whatever was run most recently, so the first screen has
        # something on it rather than an empty state for whichever ticker
        # happens to sort first.
        recent = load_runs()
        start = (tickers.index(recent[0]["ticker"])
                 if recent and recent[0]["ticker"] in tickers else 0)
        ticker = st.selectbox("Ticker", tickers, index=start)

        runs = load_runs(ticker)
        labels = [f"{r.get('run_at', '?')}" for r in runs]
        choice = st.selectbox(
            "Run", labels,
            help="Persisted runs for this ticker, newest first.") if runs else None

        st.divider()
        try:
            thesis = load_thesis(ticker)
            st.markdown(f"<div class='tw-head'>{thesis.get('name','')}</div>",
                        unsafe_allow_html=True)
            for c in thesis.get("claims", []):
                st.markdown(f"<div class='tw-head'>{c['id']} · "
                            f"{c.get('type','')}</div>", unsafe_allow_html=True)
        except (FileNotFoundError, ValueError) as e:
            st.error(str(e))
            return

        st.divider()
        if st.button("Run analysis", width="stretch"):
            st.session_state["run_now"] = ticker
        st.caption("Analyst-support tool. Not investment advice.")

    if st.session_state.pop("run_now", None) == ticker:
        if execute_run(ticker):
            st.rerun()

    if not runs:
        st.markdown(f"## {ticker}")
        st.info(f"No persisted runs for {ticker} yet. Use **Run analysis** in the "
                f"sidebar, or run `python run.py {ticker}` from the CLI.")
        return

    run = runs[labels.index(choice)] if choice in labels else runs[0]
    claims = run.get("claims", [])

    header(run)
    st.divider()
    review_queue(claims)
    st.divider()
    summary_strip(claims)
    st.markdown("")
    trend_chart(ticker, thesis)
    st.divider()
    st.markdown("#### Claim detail")
    for c in claims:
        claim_panel(c)


if __name__ == "__main__":
    main()
