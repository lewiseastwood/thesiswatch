"""Regression tests for the excerpt verification gate.

    python test_verify.py

The gate has to hold two things at once: a quote the filing really contains is
kept however the model chose to punctuate around the extractor's page-break
debris, and a quote the filing does not contain is dropped. Both directions are
asserted here, because loosening the gate to fix the first is exactly how you
break the second.
"""

import sys

from thesiswatch import is_verbatim, norm

# Mimics the real extractor output: a running header and page number stranded
# mid-sentence, which is what broke the gate on Adobe's AI-competition risk
# factor. Written on one line per paragraph, as to_text() produces.
FILING = """
Item 1A. Risk Factors

We face increasing competition from companies offering generative and agentic AI
 38

 Table of Contents

 solutions, including but not limited to prompt-based and multi-modal creation and editing, document productivity and understanding, and purpose-built AI agents. Other companies have in the past, and may in the future prevent, limit or interfere with our ability to use third-party models in our solutions.

Total Adobe ARR grew to $27.10 billion at the end of the second quarter of fiscal 2026, representing 12.5% year-over-year growth.
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
}


def main() -> int:
    hay = norm(FILING)
    failures = []

    for label, excerpt in KEEP.items():
        if not is_verbatim(excerpt, hay):
            failures.append(f"should have been kept, was dropped: {label}")
    for label, excerpt in DROP.items():
        if is_verbatim(excerpt, hay):
            failures.append(f"should have been dropped, was kept: {label}")

    total = len(KEEP) + len(DROP)
    for f in failures:
        print(f"FAIL  {f}")
    print(f"{total - len(failures)}/{total} verification-gate cases behaved")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
