"""Rendering invariants for the dashboard.

    python test_dashboard.py

The gate in thesiswatch.py decides what counts as evidence. This file asserts
the dashboard cannot undo that decision, because the view is the last thing
between a model payload and an analyst reading it as fact. It renders app.py
against hand-built run files, including ones the pipeline would never write, so
the assertions hold even for a run persisted by an older version or edited by
hand.

The fixture thesis binds no XBRL metric, so the trend chart short-circuits and
nothing here touches the network.
"""

import json
import shutil
import tempfile
from pathlib import Path

import thesiswatch
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent / "app.py"

THESIS = """ticker: TEST
name: Test — dashboard rendering invariants
claims:
  - id: TC-01
    statement: A qualitative claim, so there is no binding and no network call.
    type: qualitative
    falsifiers: ["a falsifier"]
    sections: [risk_factors]
  - id: TC-02
    statement: A second qualitative claim.
    type: qualitative
    falsifiers: ["another falsifier"]
    sections: [mda]
"""

FILING = {"filingDate": "2026-01-01", "reportDate": "2025-12-31",
          "accessionNumber": "0000000000-26-000001",
          "index_url": "https://example.invalid/index.htm",
          "url": "https://example.invalid/doc.htm"}

# What a mis-serialized payload leaves behind: the trailing structure absorbed
# into the reasoning string, carrying quotes that never reached the gate.
LEAKED = ('Growth remains healthy and nothing material changed.</reasoning>\n'
          '<parameter name="excerpts">[{"filing":"current","section":"mda",'
          '"text":"LEAKED_QUOTE_NEVER_VERIFIED"}]')


class StubCtx:
    """Minimal stand-in for Context; save_run only reads the filing dicts."""

    current = dict(FILING, form="10-Q")
    prior = dict(FILING, form="10-Q")


def claim(**over) -> dict:
    base = {
        "claim_id": "TC-01",
        "statement": "A qualitative claim, so there is no binding and no network call.",
        "verdict": "unchanged",
        "band": "not_applicable",
        "reasoning": "Nothing material changed between the two filings.",
        "excerpts": [],
        "metrics": [],
        "confidence": "high",
        "needs_review": [],
        "tool_calls": 4,
    }
    return base | over


def render(claims: list[dict]) -> str:
    """Render app.py against one hand-built run and return everything it drew."""
    root = Path(tempfile.mkdtemp(prefix="thesiswatch-dash-"))
    theses, runs = root / "theses", root / "runs"
    theses.mkdir()
    runs.mkdir()
    (theses / "TEST.yaml").write_text(THESIS)
    (runs / "TEST-20260101T000000.json").write_text(json.dumps({
        "ticker": "TEST",
        "thesis_name": "Test — dashboard rendering invariants",
        "run_at": "2026-01-01 00:00:00 UTC",
        "form": "10-Q",
        "filings": {"current": FILING, "prior": FILING},
        "claims": claims,
    }))

    keep = (thesiswatch.THESES_DIR, thesiswatch.RUNS_DIR)
    thesiswatch.THESES_DIR, thesiswatch.RUNS_DIR = theses, runs
    try:
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()
        if at.exception:
            raise AssertionError(
                "app.py raised while rendering: "
                + "; ".join(str(e.value)[:300] for e in at.exception))
        drawn = [m.value for m in at.markdown]
        drawn += [e.label for e in at.expander]
        drawn += [i.value for i in at.info]
        drawn += [e.value for e in at.error]
        return "\n".join(str(d) for d in drawn)
    finally:
        thesiswatch.THESES_DIR, thesiswatch.RUNS_DIR = keep
        shutil.rmtree(root, ignore_errors=True)


def check_excerpt_verification(fail) -> int:
    """Only an excerpt carrying verified=True may appear on the page.

    The three cases are the ones that actually occur: a clean verified excerpt,
    one whose flag is missing because it never went through verify(), and one
    explicitly marked False.
    """
    out = render([claim(excerpts=[
        {"text": "KEPT_QUOTE_IS_VERIFIED", "section": "mda",
         "filing": "current", "verified": True},
        {"text": "DROPPED_QUOTE_FLAG_ABSENT", "section": "mda",
         "filing": "current"},
        {"text": "DROPPED_QUOTE_FLAG_FALSE", "section": "risk_factors",
         "filing": "prior", "verified": False},
    ])])

    if "KEPT_QUOTE_IS_VERIFIED" not in out:
        fail("a verified excerpt was not rendered")
    for label in ("DROPPED_QUOTE_FLAG_ABSENT", "DROPPED_QUOTE_FLAG_FALSE"):
        if label in out:
            fail(f"rendered an unverified excerpt: {label}")

    # The count on the summary card has to agree with what is shown below it.
    # A card reading "3 excerpts" over one rendered quote is the same
    # inconsistency that hid the mis-serialized payload in the markdown report.
    if "1 excerpt," not in out:
        fail("summary card counted unverified excerpts instead of verified ones")

    # Dropping evidence quietly is the failure the gate exists to prevent, so
    # the drop is itself a review item.
    if "2 excerpt(s) carried no verification marker" not in out:
        fail("dropped unverified excerpts without saying so")

    # A claim with nothing verified must say so rather than render an empty gap.
    empty = render([claim(excerpts=[
        {"text": "DROPPED_ONLY_QUOTE", "section": "mda", "filing": "current"},
    ])])
    if "DROPPED_ONLY_QUOTE" in empty:
        fail("rendered an unverified excerpt when it was the only one")
    if "No excerpt passed verification" not in empty:
        fail("did not state that no excerpt passed verification")
    return 7


def check_truncated_verdict(fail) -> int:
    """A verdict assembled from a mis-serialized payload is not presentable.

    Upstream, validate_payload refuses these and the verdict never gets built.
    This asserts the view does not present one anyway if it finds one on disk:
    the leaked structure must not reach the page, the quotes carried inside it
    must not be shown as evidence, and the claim must be flagged rather than
    read as finished analysis.
    """
    out = render([claim(reasoning=LEAKED)])

    if "LEAKED_QUOTE_NEVER_VERIFIED" in out:
        fail("rendered a quote carried inside leaked tool-call markup")
    for token in ("</reasoning>", "<parameter", "<invoke"):
        if token in out:
            fail(f"rendered raw tool-call markup: {token}")
    if "never verified" not in out:
        fail("did not flag the claim whose reasoning shows a truncated payload")

    # The prose written before the leak is real and may stay; what must not
    # survive is anything from the cut onwards.
    if "Growth remains healthy" not in out:
        fail("discarded the reasoning written before the leak")

    # The recorded verdict was "unchanged", but a payload that lost a field
    # boundary cannot support any verdict, so it must not be shown as one.
    if "unchanged" in out:
        fail("presented a leaked-payload claim under its recorded verdict")
    if "insufficient evidence" not in out:
        fail("did not downgrade a leaked-payload claim to insufficient evidence")

    # The refusal upstream sets this verdict and flag; both belong on the page.
    refused = render([claim(
        verdict="insufficient_evidence", confidence="low",
        reasoning="",
        needs_review=["Verdict payload was mis-serialized: raw tool-call markup "
                      "appeared inside reasoning."])])
    if "insufficient evidence" not in refused.lower():
        fail("did not surface the refused verdict")
    if "mis-serialized" not in refused:
        fail("did not surface the refusal reason in the review queue")
    return 9


def check_forged_marker_limit(fail) -> int:
    """A forged verified marker is out of the view's reach; save_run is the line.

    verified=True cannot be re-derived without the filing text, which a consumer
    reading runs/*.json does not have. So the view renders it, and this asserts
    that plainly rather than implying a defence that is not there. The half that
    can be enforced is asserted where it lives: save_run must not write an
    unmarked excerpt in the first place.
    """
    out = render([claim(excerpts=[
        {"text": "FORGED_MARKER_QUOTE", "section": "mda",
         "filing": "current", "verified": True},
    ])])
    if "FORGED_MARKER_QUOTE" not in out:
        fail("known limit has changed: a hand-set verified marker is now refused, "
             "so this test and the note in assess_integrity need rewriting")

    root = Path(tempfile.mkdtemp(prefix="thesiswatch-save-"))
    keep = thesiswatch.RUNS_DIR
    thesiswatch.RUNS_DIR = root
    try:
        v = thesiswatch.Verdict("TC-01", "s", verdict="unchanged", excerpts=[
            {"text": "MARKED_AND_KEPT", "section": "mda", "filing": "current",
             "verified": True},
            {"text": "UNMARKED_NEVER_PERSISTED", "section": "mda",
             "filing": "current"},
        ])
        written = thesiswatch.save_run("TEST", {"name": "n"}, StubCtx(), [v]).read_text()
        if "UNMARKED_NEVER_PERSISTED" in written:
            fail("save_run persisted an excerpt carrying no verification marker")
        if "MARKED_AND_KEPT" not in written:
            fail("save_run dropped a verified excerpt")
    finally:
        thesiswatch.RUNS_DIR = keep
        shutil.rmtree(root, ignore_errors=True)
    return 3


def check_empty_review_queue(fail) -> int:
    """The review section renders even with nothing in it.

    An absent section reads as "not checked". A present section with a zero
    count reads as "checked, nothing found", and those are different claims.
    """
    out = render([claim(needs_review=[]), claim(claim_id="TC-02", needs_review=[])])

    if "Requires analyst review" not in out:
        fail("review section vanished when the queue was empty")
    if "'>0</span>" not in out.replace('"', "'"):
        fail("empty review section did not show a zero count badge")
    if "No automated flags raised" not in out:
        fail("empty review section did not say so explicitly")
    if "not a clean bill of health" not in out:
        fail("empty review section implied the run was clean")

    # And it still renders, with a real count, when the queue is not empty.
    full = render([claim(needs_review=["first concern", "second concern"])])
    if "Requires analyst review" not in full or "first concern" not in full:
        fail("review section did not render its entries")
    if "'>2</span>" not in full.replace('"', "'"):
        fail("review section miscounted its entries")
    return 6


CHECKS = (check_excerpt_verification, check_truncated_verdict,
          check_forged_marker_limit, check_empty_review_queue)


# ------------------------------------------------------ pytest entry points
# See the note in test_verify.py: without a test_* name pytest collects nothing
# from this file, so a CI step running pytest would pass having rendered nothing.
def _under_pytest(check) -> None:
    failures: list[str] = []
    cases = check(failures.append)
    assert cases, f"{check.__name__} ran no cases"
    assert not failures, f"{len(failures)} failed: " + "; ".join(failures)


def test_only_verified_excerpts_are_rendered():
    _under_pytest(check_excerpt_verification)


def test_truncated_verdict_is_not_presentable():
    _under_pytest(check_truncated_verdict)


def test_forged_verification_marker_is_a_known_limit():
    _under_pytest(check_forged_marker_limit)


def test_review_queue_renders_when_empty():
    _under_pytest(check_empty_review_queue)


def main() -> int:
    failures: list[str] = []
    total = 0
    for check in CHECKS:
        before = len(failures)
        total += check(failures.append)
        status = "ok  " if len(failures) == before else "FAIL"
        print(f"{status} {check.__doc__.splitlines()[0]}")

    for f in failures:
        print(f"FAIL  {f}")
    print(f"{total - len(failures)}/{total} dashboard invariants held")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
