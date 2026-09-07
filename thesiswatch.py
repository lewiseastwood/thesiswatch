"""ThesisWatch — agentic SEC filing vs. investment thesis monitor.

Fallback to the notebook. Upload to the Colab file browser, then:

    from thesiswatch import *
    import thesiswatch
    thesiswatch.SEC_UA = "ThesisWatch research/0.1 (your.email@gmail.com)"
    edgar = Edgar(thesiswatch.SEC_UA)

Analyst-support tool. Does not produce buy/sell recommendations.
"""

import json, re, time, html, difflib, hashlib
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any, Callable

import requests
import yaml

SEC_UA = "ThesisWatch research/0.1 (you@example.com)"
MODEL = "claude-sonnet-5"

# Thinking is on by default for this model generation and draws on the same
# budget: a run capped at 700 spent the entire allowance on a thinking block and
# never emitted a tool call. 4000 left so little room for a long verdict that
# submit_verdict payloads came back mis-serialized. Raising this lowers the odds
# but is not the safeguard -- validate_payload is.
MAX_TOKENS = 8000

# There is no sampling knob to pin here: the API rejects both `temperature` and
# `top_k` for this model generation as "deprecated for this model", and neither
# appears in the SDK. Run-to-run verdict stability therefore has to come from
# leaving the model no room to choose, which is what the rubric in SYSTEM does.


# ---------------------------------------------------------------- EDGAR
class Edgar:
    """Rate-limited EDGAR client. SEC caps at 10 req/s and requires a UA."""

    def __init__(self, user_agent: str, min_interval: float = 0.15):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.min_interval = min_interval
        self._last = 0.0
        self._ticker_map: dict[str, str] | None = None

    def _get(self, url: str) -> requests.Response:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = self.s.get(url, timeout=30)
        self._last = time.time()
        r.raise_for_status()
        return r

    def cik(self, ticker: str) -> str:
        if self._ticker_map is None:
            data = self._get("https://www.sec.gov/files/company_tickers.json").json()
            self._ticker_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                                for v in data.values()}
        key = ticker.upper()
        if key not in self._ticker_map:
            raise KeyError(f"Unknown ticker {ticker!r}")
        return self._ticker_map[key]

    def filings(self, cik: str, form: str, limit: int = 4) -> list[dict]:
        j = self._get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
        rec = j["filings"]["recent"]
        cols = ["accessionNumber", "form", "filingDate", "reportDate",
                "primaryDocument", "primaryDocDescription"]
        rows = [dict(zip(cols, vals)) for vals in zip(*[rec[c] for c in cols])]
        out = [r for r in rows if r["form"] == form][:limit]
        for r in out:
            acc = r["accessionNumber"].replace("-", "")
            r["cik"] = cik
            r["url"] = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{acc}/{r['primaryDocument']}")
            r["index_url"] = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                              f"{acc}/{r['accessionNumber']}-index.htm")
        return out

    def concept(self, cik: str, tag: str, taxonomy: str = "us-gaap") -> list[dict]:
        """Tagged XBRL values. Use this for numbers — never parse them from HTML."""
        url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
               f"CIK{cik}/{taxonomy}/{tag}.json")
        try:
            j = self._get(url).json()
        except requests.HTTPError:
            return []
        rows = []
        for unit, vals in j.get("units", {}).items():
            for v in vals:
                rows.append({"tag": tag, "unit": unit, "val": v.get("val"),
                             "start": v.get("start"), "end": v.get("end"),
                             "fy": v.get("fy"), "fp": v.get("fp"),
                             "form": v.get("form"), "frame": v.get("frame"),
                             "accn": v.get("accn")})
        rows.sort(key=lambda r: (r["end"] or ""))
        return rows

    def document(self, url: str) -> str:
        return self._get(url).text


# ------------------------------------------------------- text + sections
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\xa0]+")


def to_text(raw_html: str) -> str:
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw_html)
    t = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", t)
    t = re.sub(r"(?i)<br[^>]*>", "\n", t)
    t = TAG_RE.sub(" ", t)
    t = html.unescape(t)
    t = WS_RE.sub(" ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


ITEM_MAPS = {
    # Anchored on item number AND title text. Item numbers alone are ambiguous:
    # a 10-Q has "Item 2" in both Part I (MD&A) and Part II (equity sales).
    "10-K": {
        "business":     r"Item\s*1[\.\s:\-\u2013\u2014]{0,6}Business",
        "risk_factors": r"Item\s*1A[\.\s:\-\u2013\u2014]{0,6}Risk\s*Factors",
        "mda":          r"Item\s*7[\.\s:\-\u2013\u2014]{0,6}Management",
        "market_risk":  r"Item\s*7A[\.\s:\-\u2013\u2014]{0,6}Quantitative",
        "financials":   r"Item\s*8[\.\s:\-\u2013\u2014]{0,6}(?:Financial|Consolidated)",
        "controls":     r"Item\s*9A[\.\s:\-\u2013\u2014]{0,6}Controls",
    },
    "10-Q": {
        # Filers interpose adjectives: "Item 1. Condensed Consolidated Financial
        # Statements". Match the first title word, as the 10-K map does.
        "financials":   r"Item\s*1[\.\s:\-\u2013\u2014]{0,6}(?:Condensed|Consolidated|Financial)",
        "mda":          r"Item\s*2[\.\s:\-\u2013\u2014]{0,6}Management",
        "market_risk":  r"Item\s*3[\.\s:\-\u2013\u2014]{0,6}Quantitative",
        "controls":     r"Item\s*4[\.\s:\-\u2013\u2014]{0,6}Controls",
        "legal":        r"Item\s*1[\.\s:\-\u2013\u2014]{0,6}Legal\s*Proceedings",
        "risk_factors": r"Item\s*1A[\.\s:\-\u2013\u2014]{0,6}Risk\s*Factors",
    },
}


def split_sections(text: str, form: str = "10-K") -> dict[str, str]:
    """Locate Item headers for the given form type.

    Takes the LAST match of each pattern, which skips the table of contents.
    Title anchoring (not just the number) disambiguates Part I from Part II.
    Always eyeball the result on a new filer before trusting a run.
    """
    items = ITEM_MAPS.get(form.upper(), ITEM_MAPS["10-K"])
    hits = []
    for name, pat in items.items():
        ms = list(re.finditer(pat, text, re.I))
        if ms:
            hits.append((ms[-1].start(), name))
    hits.sort()
    out = {}
    for i, (pos, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        body = text[pos:end].strip()
        if len(body) > 500:
            out[name] = body
    return out


def slice_words(body: str, start: int, end: int) -> str:
    """Slice `body`, moving each cut end to a word boundary and marking it.

    A raw character slice leaves a half-word at the edge, the model copies it
    into an excerpt verbatim, and the quote verifies but renders as "…displace
    established user inte". Trimming to a boundary and marking the cut with an
    ellipsis keeps quotes readable, and the gate already understands an ellipsis
    as elision, so nothing is loosened to allow it.
    """
    lo, hi = max(0, start), min(len(body), end)
    cut_head, cut_tail = lo > 0, hi < len(body)
    if cut_head:
        nxt = body.find(" ", lo)
        if 0 <= nxt < hi:
            lo = nxt + 1
    if cut_tail:
        prev = body.rfind(" ", lo, hi)
        if prev > lo:
            hi = prev
    out = body[lo:hi].strip()
    return ("… " if cut_head else "") + out + (" …" if cut_tail else "")


def diff_summary(old: str, new: str, max_blocks: int = 40) -> str:
    """Paragraph-level diff. Boilerplate churn is noise; this surfaces real edits."""
    a = [p.strip() for p in old.split("\n") if len(p.strip()) > 80]
    b = [p.strip() for p in new.split("\n") if len(p.strip()) > 80]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    parts = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op in ("insert", "replace"):
            for p in b[j1:j2][:5]:
                parts.append("[ADDED] " + p[:900])
        if op in ("delete", "replace"):
            for p in a[i1:i2][:5]:
                parts.append("[REMOVED] " + p[:900])
        if len(parts) >= max_blocks:
            break
    return "\n\n".join(parts[:max_blocks]) or "(no paragraph-level changes detected)"


# ------------------------------------------------------------- thesis
THESES_DIR = Path(__file__).parent / "theses"
RUNS_DIR = Path(__file__).parent / "runs"


def available_tickers() -> list[str]:
    """Tickers with a thesis on disk."""
    return sorted(p.stem for p in THESES_DIR.glob("*.yaml"))


def load_thesis(ticker: str) -> dict:
    """Load the thesis for one ticker from theses/{TICKER}.yaml."""
    path = THESES_DIR / f"{ticker.upper()}.yaml"
    if not path.is_file():
        available = sorted(p.stem for p in THESES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"No thesis for {ticker.upper()!r} at {path}. "
            f"Available: {', '.join(available) or '(none)'}"
        )
    thesis = yaml.safe_load(path.read_text())
    for claim in thesis.get("claims", []):
        for b in claim.get("bindings", []):
            missing = {"watch", "falsified"} - set(b.get("bands") or {})
            if missing:
                raise ValueError(
                    f"{path.name}, claim {claim.get('id')}: binding on "
                    f"{b.get('tag')!r} declares no {'/'.join(sorted(missing))} band. "
                    f"A bound metric needs both levels, or the claim can only "
                    f"report pass/fail and will read green until it breaks."
                )
    return thesis


@dataclass
class Verdict:
    claim_id: str
    statement: str
    verdict: str = "insufficient_evidence"
    # Where the metric stands against the claim's bands, which is a separate
    # question from whether this filing moved it. A claim can be unchanged and
    # sitting in the watch band, and that pairing is the whole point: a single
    # bound reads green every quarter until it breaks all at once.
    band: str = "not_applicable"
    reasoning: str = ""
    excerpts: list[dict] = field(default_factory=list)
    metrics: list[dict] = field(default_factory=list)
    confidence: str = "low"
    needs_review: list[str] = field(default_factory=list)
    tool_calls: int = 0


# ------------------------------------------------------- persisted runs
def save_run(ticker: str, thesis: dict, ctx: "Context",
             verdicts: list[Verdict]) -> Path:
    """Write one run to runs/ as structured data and return the path.

    The markdown report is for reading; this is for querying. Only excerpts
    that passed the gate are stored, and each keeps its `verified` marker, so a
    consumer cannot accidentally display an unverified quote — that mistake has
    already been made once by rendering straight from a model payload.
    """
    RUNS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    payload = {
        "ticker": ticker,
        "thesis_name": thesis.get("name", ""),
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "form": ctx.current["form"],
        "filings": {
            which: {k: f[k] for k in ("filingDate", "reportDate",
                                      "accessionNumber", "index_url", "url")}
            for which, f in (("current", ctx.current), ("prior", ctx.prior))
        },
        "claims": [dict(asdict(v),
                        excerpts=[e for e in v.excerpts if e.get("verified")])
                   for v in verdicts],
    }
    path = RUNS_DIR / f"{ticker.upper()}-{stamp}.json"
    path.write_text(json.dumps(payload, indent=1))
    return path


def load_runs(ticker: str | None = None) -> list[dict]:
    """Every persisted run, newest first, optionally for one ticker."""
    pattern = f"{ticker.upper()}-*.json" if ticker else "*.json"
    runs = []
    for p in sorted(RUNS_DIR.glob(pattern), reverse=True):
        try:
            run = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        run["_path"] = str(p)
        runs.append(run)
    return runs


# --------------------------------------------------- metric time series
def band_pct(band: str | None) -> float | None:
    """Pull the number out of a band written like ">= 8% YoY" or "10% YoY"."""
    if not band:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(band))
    return float(m.group()) if m else None


def quarterly_yoy(rows: list[dict]) -> list[dict]:
    """Deduplicated quarterly points, oldest first, with YoY growth where computable.

    XBRL returns the same period once per filing that reported it, so points are
    keyed by their date range and the latest report of each wins. A quarter is
    matched to the one a year earlier by date rather than by index, because a
    filer's history has gaps and a 52/53-week calendar drifts a few days.
    """
    by_period: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r.get("unit") != "USD" or not (r.get("start") and r.get("end")):
            continue
        try:
            start = date.fromisoformat(r["start"])
            end = date.fromisoformat(r["end"])
        except ValueError:
            continue
        if not 80 <= (end - start).days <= 100:  # one quarter, not a YTD roll-up
            continue
        by_period[(r["start"], r["end"])] = {"start": start, "end": end,
                                             "val": r["val"], "tag": r["tag"]}

    points = sorted(by_period.values(), key=lambda p: p["end"])
    for p in points:
        prior = next((q for q in points
                      if 330 <= (p["end"] - q["end"]).days <= 400), None)
        p["yoy"] = (round((p["val"] / prior["val"] - 1) * 100, 2)
                    if prior and prior["val"] else None)
    return points


# -------------------------------------------------------------- tools
TOOLS = [
    {
        "name": "get_metric",
        "description": (
            "Fetch tagged XBRL values for one us-gaap concept, oldest first. "
            "Use for any numeric claim. Common tags: Revenues, "
            "RevenueFromContractWithCustomerExcludingAssessedTax, GrossProfit, "
            "OperatingIncomeLoss, NetIncomeLoss, ResearchAndDevelopmentExpense."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "us-gaap concept name"},
                "limit": {"type": "integer", "description": "most recent N points, default 8"},
            },
            "required": ["tag"],
        },
    },
    {
        "name": "read_section",
        "description": (
            "Return text of one section from the current or prior filing. "
            "10-K sections: business, risk_factors, mda, market_risk, financials, controls. "
            "10-Q sections: financials, mda, market_risk, controls, legal, risk_factors. "
            "If a section is missing the tool tells you which are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "filing": {"type": "string", "enum": ["current", "prior"]},
                "offset": {"type": "integer", "description": "char offset, default 0"},
            },
            "required": ["section", "filing"],
        },
    },
    {
        "name": "diff_section",
        "description": "Paragraph-level added/removed text for a section, prior vs current.",
        "input_schema": {
            "type": "object",
            "properties": {"section": {"type": "string"}},
            "required": ["section"],
        },
    },
    {
        "name": "search_filing",
        "description": "Case-insensitive keyword search in the current filing. Returns snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filing": {"type": "string", "enum": ["current", "prior"]},
            },
            "required": ["query"],
        },
    },
    {
        "name": "submit_verdict",
        "description": (
            "Record the final judgement for this claim. Every excerpt must be copied "
            "VERBATIM from tool output — it is checked against the source and the claim "
            "is downgraded if it does not match. Filing text often has a page number and "
            "'Table of Contents' interposed mid-sentence; write an ellipsis (…) where you "
            "skip such material instead of paraphrasing across it. Text on either side of "
            "an ellipsis is still checked verbatim."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["strengthened", "weakened", "unchanged", "insufficient_evidence"],
                },
                "band": {
                    "type": "string",
                    "description": (
                        "For a claim whose bindings declare bands, where the metric now "
                        "sits: above_watch (clear of both levels), watch_band (past the "
                        "watch level but not the falsified level — deteriorating and "
                        "worth attention), below_falsified (the falsified level is "
                        "breached). Use not_applicable when the claim declares no bands. "
                        "This is independent of the verdict: report the level you "
                        "measured, not whether it moved."
                    ),
                    "enum": ["above_watch", "watch_band", "below_falsified",
                             "not_applicable"],
                },
                "reasoning": {"type": "string"},
                "excerpts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "section": {"type": "string"},
                            "filing": {"type": "string"},
                        },
                        "required": ["text", "section", "filing"],
                    },
                },
                "metrics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tag": {"type": "string"},
                            "period": {"type": "string"},
                            "value": {"type": "number"},
                            "note": {"type": "string"},
                        },
                        "required": ["tag", "period", "value"],
                    },
                },
                "needs_review": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "reasoning"],
        },
    },
]


class Context:
    """Everything one run needs. Tool dispatch closes over this."""

    def __init__(self, edgar: Edgar, cik: str, current: dict, prior: dict):
        self.edgar, self.cik = edgar, cik
        self.current, self.prior = current, prior
        self.text = {
            "current": to_text(edgar.document(current["url"])),
            "prior": to_text(edgar.document(prior["url"])),
        }
        self.form = current["form"]
        self.sections = {k: split_sections(v, self.form) for k, v in self.text.items()}

    def dispatch(self, name: str, inp: dict) -> str:
        if name == "get_metric":
            rows = self.edgar.concept(self.cik, inp["tag"])
            if not rows:
                return f"No XBRL data for tag {inp['tag']!r}. Try another concept name."
            return json.dumps(rows[-int(inp.get("limit", 8)):], indent=1)

        if name == "read_section":
            body = self.sections[inp["filing"]].get(inp["section"], "")
            if not body:
                have = list(self.sections[inp["filing"]])
                return f"Section not extracted. Available: {have}"
            off = int(inp.get("offset", 0))
            chunk = slice_words(body, off, off + 12000)
            more = "" if off + 12000 >= len(body) else \
                f"\n\n[truncated — {len(body) - off - 12000} chars remain, use offset={off + 12000}]"
            return chunk + more

        if name == "diff_section":
            s = inp["section"]
            return diff_summary(self.sections["prior"].get(s, ""),
                                self.sections["current"].get(s, ""))

        if name == "search_filing":
            body = self.text[inp.get("filing", "current")]
            q = re.escape(inp["query"])
            hits = [slice_words(body, m.start() - 400, m.start() + 600)
                    for m in re.finditer(q, body, re.I)][:6]
            return "\n\n---\n\n".join(hits) or "No matches."

        return f"Unknown tool {name}"


# ---------------------------------------------------- verification gate
# "…", "...", ". . .", "[...]" — the forms a model uses to mark elided text.
ELLIPSIS_RE = re.compile(r"\[?\s*(?:\u2026|(?:\.\s*){3,})\s*\]?")

# Running headers/footers the extractor leaves sitting mid-sentence.
PAGE_FURNITURE_RE = re.compile(
    r"\s*(?:\d{1,4}\s+)?Table\s+of\s+Contents\b(?:\s+\d{1,4}\b)?\s*", re.I)


def norm(s: str) -> str:
    """Fold text to the form the verification gate compares on.

    Page furniture is dropped from both sides of the comparison. The extractor
    strands a running header mid-sentence, so whether a quote reproduces that
    header, elides it with an ellipsis, or just closes the gap is a stylistic
    choice, and it should not decide whether the quote counts as verbatim.
    """
    return re.sub(r"\s+", " ", PAGE_FURNITURE_RE.sub(" ", s)).strip().lower()


def tidy_excerpt(text: str) -> str:
    """Collapse interposed page furniture into an ellipsis, for display only.

    Verification runs on the excerpt exactly as submitted, so the ellipsis here
    stands for characters that really were in the filing at that point — it is
    shortening a quote, not papering over a mismatch.
    """
    return " ".join(PAGE_FURNITURE_RE.sub(" … ", text).split())

# Segments shorter than this are a few words of connective tissue and carry no
# evidentiary weight, so they are not matched. An excerpt made only of such
# fragments verifies nothing and is rejected.
MIN_SEGMENT = 12

# How far a quote may jump between two elided segments.
#
# Order alone does not constrain distance, so without this a composite stitched
# from fragments in different Items passes: "we face increasing competition"
# from the risk factors joined to "pricing pressure" from MD&A, each verbatim,
# each in order, together asserting a sentence the filing never contains. A
# quote fabricated by omission is the exact thing this gate exists to catch.
#
# 400 is set from measurement, not taste: instrumenting a full ADBE and CRM run
# showed every accepted excerpt matching as one contiguous run, max hop 0,
# because folding page furniture out of both sides already closes the
# page-break case. So this only needs to leave room for eliding a clause or two
# inside a single passage, and anything reaching across sections is rejected.
MAX_SEGMENT_GAP = 400


def is_verbatim(text: str, hay: str) -> bool:
    """True if every substantive run of `text` appears in `hay`, in order.

    Quotes are checked segment by segment rather than whole, because a filing
    sentence often has a page footer interposed mid-sentence by the extractor,
    and the honest way to quote it is to elide with an ellipsis. Requiring the
    segments in left-to-right, non-overlapping order keeps the guarantee that
    matters: no words the filing does not contain, in the order it contains
    them. Fabricated text still fails.
    """
    pos, matched, anchored = 0, 0, False
    for seg in ELLIPSIS_RE.split(norm(text)[:300]):
        seg = seg.strip()
        if not seg:
            continue
        short = len(seg) < MIN_SEGMENT
        # A short run is normally connective tissue and goes unmatched. A short
        # run holding a figure does not: "… 41.5% …" is small enough to hide in,
        # and a number nobody checked is the one thing this gate cannot pass.
        if short and not any(c.isdigit() for c in seg):
            continue
        at = hay.find(seg, pos)
        if at < 0:
            return False
        if anchored and at - pos > MAX_SEGMENT_GAP:
            return False
        pos = at + len(seg)
        anchored = True
        if not short:
            matched += 1
    return matched > 0


def verify(v: Verdict, ctx: Context) -> Verdict:
    """Hard gate: an excerpt that isn't verbatim in the source doesn't count."""
    kept = []
    for ex in v.excerpts:
        hay = norm(ctx.text.get(ex.get("filing", "current"), ""))
        if is_verbatim(ex["text"], hay):
            ex["verified"] = True
            kept.append(ex)
        else:
            # Quote enough to tell a fabrication from a near-miss, and only
            # mark truncation when it happened — an unconditional "…" here read
            # as if the excerpt itself ended in one, which hid this bug.
            shown = " ".join(ex["text"].split())
            clipped = shown[:240] + ("…" if len(shown) > 240 else "")
            v.needs_review.append(f"Unverifiable excerpt dropped: {clipped}")
    v.excerpts = kept
    if v.verdict in ("strengthened", "weakened") and not (kept or v.metrics):
        v.verdict = "insufficient_evidence"
        v.needs_review.append("Directional verdict had no verified evidence; downgraded.")
    return v


# Tool-call serialization that has no business inside a string field. When a
# submit_verdict payload comes back mis-serialized, the trailing structure gets
# absorbed into whichever field was mid-write, so this markup appearing in a
# text field means other fields were silently lost.
MARKUP_RE = re.compile(
    r"</?\s*(?:antml:)?(?:reasoning|parameter|invoke|function_calls|"
    r"function_results|thinking)\b[^>]*>", re.I)


def strip_markup(text: str) -> tuple[str, bool]:
    """Return `text` cut at the first leaked tool-call tag, and whether it leaked."""
    if not text:
        return "", False
    hit = MARKUP_RE.search(text)
    if not hit:
        return text, False
    return text[:hit.start()].rstrip(), True


def validate_payload(v: Verdict, payload: dict, stop_reason: str | None) -> str:
    """Return a rejection reason if this verdict rests on a partial payload.

    A truncated or mis-serialized tool call does not announce itself. The
    observed failure arrived with stop_reason "tool_use" and all five keys
    present, while needs_review had been swallowed into reasoning and three
    excerpts never became excerpts at all -- they rendered into the report as
    raw JSON inside the prose, with the verification gate never running on
    them. So the payload is checked for the markup that proves a field boundary
    was lost, not just for the stop reason.
    """
    if stop_reason == "max_tokens":
        return (f"Model output hit the {MAX_TOKENS}-token cap, so the verdict "
                f"payload was cut off mid-serialization and any fields after the "
                f"cut are missing. Verdict discarded rather than reported from a "
                f"partial response.")
    leaked = sorted({k for k, val in payload.items()
                     if isinstance(val, str) and MARKUP_RE.search(val)})
    if leaked:
        return (f"Verdict payload was mis-serialized: raw tool-call markup appeared "
                f"inside {', '.join(leaked)}, which means at least one later field "
                f"was absorbed into an earlier one and never parsed. Any excerpts "
                f"lost this way would bypass the verification gate entirely, so the "
                f"verdict is discarded rather than reported from a partial payload.")
    return ""


def score_confidence(v: Verdict) -> str:
    n = len(v.excerpts) + len(v.metrics)
    if v.verdict == "insufficient_evidence" or n == 0:
        return "low"
    if n >= 3 and not v.needs_review:
        return "high"
    return "medium"


# ----------------------------------------------------------- agent loop
SYSTEM = """You are an equity research assistant evaluating one thesis claim \
against a company's newest SEC filing versus the prior comparable filing.

Rules:
- Investigate with the tools before judging. Do not answer from prior knowledge.
- Numbers come from get_metric only. Never state a figure you did not retrieve.
- A figure read out of filing prose or a table is not tagged data, even when the
  excerpt around it verifies. If a claim lists unverifiable_from_xbrl, or you find
  yourself reading a number off a table because no binding supplies it, say so in
  the reasoning and add a needs_review entry naming that figure as text-sourced.
- Take fiscal-period labels from the filing itself. A non-calendar year end makes
  the fiscal year differ from the calendar year, and mislabelling which quarter
  you compared makes the whole comparison unreadable.
- Excerpts must be copied verbatim from tool output, under 60 words each. Use an
  ellipsis (…) to mark text you skip inside a quote, including page-break debris
  like "38 Table of Contents" sitting mid-sentence. Never paraphrase inside a quote.
- Boilerplate rewording is not a change. Only flag substantive shifts.
- Prefer insufficient_evidence over a guess.
- You are supporting an analyst. Never recommend buying or selling.

Verdict rubric. Judge what THIS FILING CHANGED relative to the prior filing. The
question is never "is the claim true?" — a claim can be comfortably true and still
be unchanged, because nothing new was disclosed.
- strengthened: this filing moves the claim measurably further from its falsifiers
  than the prior filing did.
- weakened: this filing moves the claim measurably toward a falsifier, or a
  falsifier is now met.
- unchanged: the two filings support the claim about equally — the disclosure is
  the same in substance, or a bound metric moved without changing which band it
  sits in.
- insufficient_evidence: the tools did not establish where the claim stands.
For a bound metric, "measurably" means the margin against the bands moved by more
than ordinary quarter-to-quarter variation; a metric that stays in the same band
with a similar margin is unchanged.
If two verdicts look equally defensible, return unchanged and put the tension in
needs_review. Do not resolve a genuine ambiguity by picking the more interesting
verdict — a verdict has to mean the filing moved, or it tells the analyst nothing.

Bands are a separate axis from the verdict, and you report both. The verdict says
whether the filing moved; the band says what level the metric is at now. Report
the band you measured even when the verdict is unchanged — a metric drifting
through the watch band while each single quarter looks unremarkable is exactly
what the band exists to surface. Compute it from get_metric values against the
`bands` in the claim's bindings, and say in your reasoning which YoY figures you
compared. If a claim declares no bands, the band is not_applicable.
Finish by calling submit_verdict exactly once."""


def evaluate_claim(client, ctx: Context, claim: dict, max_turns: int = 12,
                   on_tool: Callable[[str, dict], None] | None = None) -> Verdict:
    """Run one claim to a verdict.

    `on_tool` is called with (tool_name, arguments) as each call is made, so a
    caller can show the investigation as it happens. It is optional and the CLI
    does not pass it.
    """
    v = Verdict(claim_id=claim["id"], statement=claim["statement"])
    prompt = (
        f"Claim {claim['id']}: {claim['statement']}\n"
        f"Type: {claim.get('type')}\n"
        f"Would be falsified by: {claim.get('falsifiers', [])}\n"
        f"Cannot be sourced from XBRL (flag as text-sourced if you rely on it): "
        f"{claim.get('unverifiable_from_xbrl', [])}\n"
        f"Suggested sections: {claim.get('sections', [])}\n"
        f"Metric bindings: {claim.get('bindings', [])}\n\n"
        f"Current filing: {ctx.current['form']} filed {ctx.current['filingDate']} "
        f"(period {ctx.current['reportDate']})\n"
        f"Prior filing: {ctx.prior['form']} filed {ctx.prior['filingDate']} "
        f"(period {ctx.prior['reportDate']})"
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    for _turn in range(max_turns):
        resp = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            tools=TOOLS, messages=messages,
        )
        # Bail before any block from a capped turn is read. Whatever was being
        # written when the cap hit is incomplete, so dispatching its tool calls
        # would act on half-serialized arguments.
        if resp.stop_reason == "max_tokens":
            v.verdict = "insufficient_evidence"
            v.confidence = "low"
            v.needs_review.append(
                f"Model output hit the {MAX_TOKENS}-token cap on turn {_turn} "
                f"before a verdict was submitted, so the response was cut "
                f"mid-serialization and was discarded.")
            return v
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break

        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            v.tool_calls += 1
            if on_tool:
                on_tool(block.name, block.input or {})
            if block.name == "submit_verdict":
                i = block.input
                bad = validate_payload(v, i, resp.stop_reason)
                if bad:
                    v.verdict = "insufficient_evidence"
                    v.confidence = "low"
                    v.needs_review.append(bad)
                    return v
                v.verdict = i.get("verdict", v.verdict)
                v.band = i.get("band", "not_applicable")
                v.reasoning = i.get("reasoning", "")
                v.excerpts = i.get("excerpts", [])
                v.metrics = i.get("metrics", [])
                v.needs_review = i.get("needs_review", [])
                v = verify(v, ctx)
                v.confidence = score_confidence(v)
                return v
            try:
                out = ctx.dispatch(block.name, block.input)
            except Exception as e:
                out = f"Tool error: {type(e).__name__}: {e}"
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": out[:60000]})
        if not results:
            break
        messages.append({"role": "user", "content": results})

    v.needs_review.append("Agent did not submit a verdict within the turn budget.")
    return v


# ------------------------------------------------------------- report
BAND_LABELS = {
    "above_watch": "above watch",
    "watch_band": "**watch band**",
    "below_falsified": "**falsified level breached**",
    "not_applicable": "—",
}


def build_report(ctx: Context, thesis: dict, verdicts: list[Verdict]) -> str:
    L = [f"# ThesisWatch — {thesis['ticker']}",
         "",
         "**Analyst-support tool. Not investment advice. No buy/sell recommendation "
         "is produced or implied.**",
         "",
         f"- Thesis: {thesis['name']}",
         f"- Current filing: {ctx.current['form']} · filed {ctx.current['filingDate']} "
         f"· [{ctx.current['accessionNumber']}]({ctx.current['index_url']})",
         f"- Prior filing: {ctx.prior['form']} · filed {ctx.prior['filingDate']} "
         f"· [{ctx.prior['accessionNumber']}]({ctx.prior['index_url']})",
         "",
         "## Summary", "",
         "| Claim | Verdict | Band | Confidence | Evidence | Tool calls |",
         "|---|---|---|---|---|---|"]
    for v in verdicts:
        L.append(f"| {v.claim_id} | **{v.verdict}** | "
                 f"{BAND_LABELS.get(v.band, v.band)} | {v.confidence} | "
                 f"{len(v.excerpts)} excerpt(s), {len(v.metrics)} metric(s) | {v.tool_calls} |")

    # A verdict of "unchanged" says the filing did not move. It does not say the
    # metric is comfortable, so the level gets its own line rather than being
    # left for the reader to infer from a green-looking table.
    banded = [v for v in verdicts if v.band in ("watch_band", "below_falsified")]
    if banded:
        L += ["", "Level alert — unchanged does not mean comfortable:"]
        L += [f"- **{v.claim_id}** is {BAND_LABELS[v.band]} (verdict: {v.verdict})"
              for v in banded]

    # Rendering is the last place this can be caught, so it does not trust the
    # reasoning string even if the payload check upstream passed it. Leaked
    # markup means the prose after it is serialized tool arguments, which would
    # show a reader quotes that never went through the verification gate.
    render_flags = []
    for v in verdicts:
        _, leaked = strip_markup(v.reasoning)
        if leaked:
            render_flags.append(
                (v.claim_id, "Reasoning contained raw tool-call markup and was "
                             "truncated at the leak. Any quotes past that point were "
                             "never verified and are not shown; re-run this claim."))

    L += ["", "## Claim detail", ""]
    for v in verdicts:
        band = (f" · band {BAND_LABELS.get(v.band, v.band)}"
                if v.band != "not_applicable" else "")
        reasoning, _ = strip_markup(v.reasoning)
        L += [f"### {v.claim_id} — {v.statement}", "",
              f"**{v.verdict}** · confidence {v.confidence}{band}", "", reasoning, ""]
        for m in v.metrics:
            L.append(f"- `{m['tag']}` {m['period']}: {m['value']:,} "
                     f"{('— ' + m['note']) if m.get('note') else ''}")
        for ex in v.excerpts:
            L += ["", f"> {tidy_excerpt(ex['text'])}", "",
                  f"  — {ex['filing']} filing, {ex['section']}"]
        L.append("")

    flags = [(v.claim_id, n) for v in verdicts for n in v.needs_review] + render_flags
    L += ["## Requires analyst review", ""]
    L += [f"- **{cid}** — {n}" for cid, n in flags] or ["- No automated flags raised."]
    L += ["", "Verify all figures against the source filing before acting on them."]
    return "\n".join(L)
