"""Regression tests for the excerpt verification gate.

    python test_verify.py

The gate has to hold two things at once: a quote the filing really contains is
kept however the model chose to punctuate around the extractor's page-break
debris, and a quote the filing does not contain is dropped. Both directions are
asserted here, because loosening the gate to fix the first is exactly how you
break the second.
"""

import sys

from thesiswatch import (MAX_SEGMENT_GAP, Verdict, build_report, is_verbatim,
                         norm, strip_markup, validate_payload, verify)

# Mimics the real extractor output: a running header and page number stranded
# mid-sentence, which is what broke the gate on Adobe's AI-competition risk
# factor. Written on one line per paragraph, as to_text() produces.
#
# The filler matters. A composite has to be stitched across a realistic
# distance for the gap bound to be under any real test, so the risk factor and
# the MD&A sentence sit thousands of characters apart, as they do in a filing.
FILLER = ("\nOur results of operations may fluctuate for many reasons, including "
          "those described elsewhere in this report. " * 40)

FILING = f"""
Item 1A. Risk Factors

We face increasing competition from companies offering generative and agentic AI
 38

 Table of Contents

 solutions, including but not limited to prompt-based and multi-modal creation and editing, document productivity and understanding, and purpose-built AI agents. Other companies have in the past, and may in the future prevent, limit or interfere with our ability to use third-party models in our solutions.
{FILLER}
Item 2. Management's Discussion and Analysis

Total Adobe ARR grew to $27.10 billion at the end of the second quarter of fiscal 2026, representing 12.5% year-over-year growth.
"""

# Same risk factor, reworded. Used to check that an excerpt labelled `current`
# is actually checked against the current filing.
PRIOR_FILING = """
Item 1A. Risk Factors

We face competition from companies offering generative artificial intelligence
solutions, and expect that competition to intensify over time.

Total Adobe ARR grew to $24.10 billion at the end of the second quarter of fiscal 2025, representing 11.0% year-over-year growth.
"""

SENTENCE = ("We face increasing competition from companies offering generative "
            "and agentic AI")
TAIL = ("solutions, including but not limited to prompt-based and multi-modal "
        "creation and editing")

KEEP = {
    # The three ways a model quotes across a stranded page break. All three are
    # faithful, so all three have to survive.
    "page debris reproduced verbatim": f"{SENTENCE} 38 Table of Contents {TAIL}",
    "page debris silently closed up": f"{SENTENCE} {TAIL}",
    "page debris elided with a unicode ellipsis": f"{SENTENCE} … {TAIL}",
    "page debris elided with three dots": f"{SENTENCE} ... {TAIL}",
    "page debris elided with a bracketed ellipsis": f"{SENTENCE} [...] {TAIL}",
    "page debris elided with a spaced ellipsis": f"{SENTENCE} . . . {TAIL}",
    "ellipsis trimming a tail": "Other companies have in the past, and may in the "
                               "future prevent, limit or interfere…",
    "elision joining two sentences in order": f"{SENTENCE} … Other companies have in "
                                              "the past, and may in the future prevent",
    "quote needing no elision at all": "Total Adobe ARR grew to $27.10 billion at the "
                                       "end of the second quarter of fiscal 2026",
    "fragment stopping short of the page break": SENTENCE,
}

DROP = {
    "wholly fabricated": "We face collapsing demand because generative AI destroyed "
                         "our pricing power.",
    "real opening, fabricated tail after the ellipsis":
        f"{SENTENCE} … and we now expect a material decline in subscription pricing.",
    "real fragments stitched out of order": f"{TAIL} … {SENTENCE}",
    "negation spliced onto a real quote":
        f"{SENTENCE} … solutions, which have not affected us at all.",
    "paraphrase rather than a quote": "The company says it faces growing rivalry from "
                                      "firms selling agentic artificial intelligence.",
    "nothing but connective fragments": "We … AI … is … not … material",
    "a figure the filing does not state": "Total Adobe ARR grew to $31.40 billion at "
                                          "the end of the second quarter of fiscal 2026",
    # The hole the loosened matcher opened: both halves verbatim, both in order,
    # but from different Items, together asserting a sentence the filing does
    # not contain. Order-preservation does not constrain distance.
    "composite stitched across sections":
        f"{SENTENCE} … Total Adobe ARR grew to $27.10 billion",
    "composite reaching backwards across sections":
        "Total Adobe ARR grew to $27.10 billion … in our solutions",
    # A figure altered and then isolated by ellipses so it lands under
    # MIN_SEGMENT. Skipping short segments meant this was never checked at all.
    "altered figure hidden in a sub-minimum segment":
        "Total Adobe ARR grew to … 31.40 … year-over-year growth",
    "altered percentage hidden in a sub-minimum segment":
        "at the end of the second quarter of fiscal 2026, representing … 41.5% … growth",
}


class StubContext:
    """Minimal stand-in for Context; verify() only reads .text."""

    def __init__(self):
        self.text = {"current": FILING, "prior": PRIOR_FILING}


PRIOR_ONLY = ("We face competition from companies offering generative artificial "
              "intelligence solutions, and expect that competition to intensify")


def check_keep(fail) -> int:
    """A quote the filing really contains survives however it was punctuated."""
    hay = norm(FILING)
    for label, excerpt in KEEP.items():
        if not is_verbatim(excerpt, hay):
            fail(f"should have been kept, was dropped: {label}")
    return len(KEEP)


def check_drop(fail) -> int:
    """A quote the filing does not contain is dropped."""
    hay = norm(FILING)
    for label, excerpt in DROP.items():
        if is_verbatim(excerpt, hay):
            fail(f"should have been dropped, was kept: {label}")
    return len(DROP)


def check_labels(fail) -> int:
    """An excerpt is checked against the filing it claims to come from.

    The risk factor is reworded between the two fixtures, so quoting the prior
    wording while labelling it `current` has to be dropped. Identical
    boilerplate cannot be told apart this way, which a real run confirmed --
    every unchanged risk-factor excerpt was present in both filings -- so this
    only bites when the wording actually moved. That is the case that matters.
    """
    cases = [
        ("prior wording, labelled prior", PRIOR_ONLY, "prior", True),
        ("prior wording, labelled current", PRIOR_ONLY, "current", False),
        ("current wording, labelled current", SENTENCE, "current", True),
        ("current wording, labelled prior", SENTENCE, "prior", False),
    ]
    ctx = StubContext()
    for label, text, filing, should_keep in cases:
        v = Verdict("TC-01", "s", excerpts=[{"text": text, "section": "risk_factors",
                                             "filing": filing}])
        kept = bool(verify(v, ctx).excerpts)
        if kept != should_keep:
            fail(f"filing label {'dropped' if should_keep else 'kept'} wrongly: {label}")
    return len(cases)


def check_payloads(fail) -> int:
    """A partial or mis-serialized verdict payload must be refused, not rendered.

    The observed failure came back with stop_reason "tool_use" and every key
    present, while three excerpts had been absorbed into the reasoning string
    and rendered into the report as raw JSON without the gate ever running.
    """
    leaked = ('Growth is healthy.</reasoning>\n<parameter name="excerpts">'
              '[{"filing":"current","text":"Subscription and support $ 10,820"}]')
    cases = [
        ("clean payload accepted",
         {"verdict": "unchanged", "reasoning": "Growth is healthy."}, "tool_use", False),
        ("markup in reasoning refused",
         {"verdict": "unchanged", "reasoning": leaked}, "tool_use", True),
        ("cap truncation refused even with a clean-looking payload",
         {"verdict": "unchanged", "reasoning": "Growth is healthy."}, "max_tokens", True),
    ]
    for label, payload, stop_reason, should_reject in cases:
        rejected = bool(validate_payload(Verdict("TC-01", "s"), payload, stop_reason))
        if rejected != should_reject:
            fail(f"payload {'accepted' if should_reject else 'refused'} "
                 f"wrongly: {label}")

    # Rendering is the last line of defence: leaked markup must never reach the
    # page, and the claim must be flagged rather than read as clean analysis.
    v = Verdict("TC-01", "s", verdict="unchanged", reasoning=leaked)

    class C:
        current = {"form": "10-Q", "filingDate": "d", "accessionNumber": "a",
                   "index_url": "u", "reportDate": "r"}
        prior = dict(current)

    report = build_report(C(), {"ticker": "T", "name": "n"}, [v])
    if "<parameter" in report or "</reasoning>" in report:
        fail("build_report rendered raw tool-call markup")
    if "Subscription and support $ 10,820" in report:
        fail("build_report rendered an unverified excerpt from leaked markup")
    if "never verified" not in report:
        fail("build_report did not flag the claim whose reasoning leaked")
    # The report and the dashboard now share assess_integrity, so they cannot
    # disagree about this. Before they did: the report went on printing
    # "**unchanged**" for a claim the dashboard had already downgraded.
    if "**unchanged**" in report:
        fail("build_report presented a leaked-payload claim under its "
             "recorded verdict")
    if "**insufficient_evidence**" not in report:
        fail("build_report did not downgrade a leaked-payload claim")
    return len(cases) + 5


CHECKS = (check_keep, check_drop, check_labels, check_payloads)


# ------------------------------------------------------ pytest entry points
# This suite predates pytest and still runs standalone. The wrappers exist so
# pytest collects it too: with no test_* name in the file, `pytest` collects
# nothing here and a CI step calling it asserts nothing at all -- the same
# silent no-op as a gate that does not run.
def _under_pytest(check) -> None:
    failures: list[str] = []
    cases = check(failures.append)
    assert cases, f"{check.__name__} ran no cases"
    assert not failures, f"{len(failures)} failed: " + "; ".join(failures)


def test_faithful_quotes_survive():
    _under_pytest(check_keep)


def test_fabricated_quotes_are_dropped():
    _under_pytest(check_drop)


def test_excerpts_are_checked_against_the_filing_they_claim():
    _under_pytest(check_labels)


def test_mis_serialized_payloads_are_refused():
    _under_pytest(check_payloads)


def main() -> int:
    failures: list[str] = []
    total = sum(check(failures.append) for check in CHECKS)
    for f in failures:
        print(f"FAIL  {f}")
    print(f"{total - len(failures)}/{total} gate cases behaved "
          f"(gap bound {MAX_SEGMENT_GAP} chars)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
