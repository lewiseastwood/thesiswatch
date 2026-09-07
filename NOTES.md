# Notes

Two things went wrong on ADBE that were worth more than the time it took to fix them.

## 1. The same filings produced two different verdicts

Two runs over the identical pair of 10-Qs disagreed on TC-01 — one said
`strengthened`, the other `unchanged` — off the same two numbers, 11.97% and 12.69%
YoY revenue growth against a 9% threshold. Both runs were internally consistent.
One argued growth accelerated, so the claim is stronger. The other argued growth
stayed well clear of the threshold with a similar margin, so nothing moved.

My first instinct was to pin the temperature and make the run reproducible. That
turned out to be impossible — the API rejects `temperature` and `top_k` as
"deprecated for this model", and neither appears in the SDK — and chasing it was
the more useful outcome, because the flip was not really a sampling problem. The
prompt never said what a verdict is measured against: the change between the two
filings, or the claim's standing against its own threshold. Those are different
questions, both reasonable readings of "strengthened", and the model was picking
one per run. Temperature 0 would have frozen one arbitrary reading and left me
believing the ambiguity was gone.

The fix was to answer the question in the prompt instead: verdicts now judge the
filing-over-filing delta explicitly, a metric that stays on the same side of its
threshold with a similar margin is `unchanged`, and a genuine tie resolves to
`unchanged` with the tension written into `needs_review`. Four consecutive runs now
agree. The tie-break is deliberately the boring direction — a verdict has to mean
the filing moved, or it tells an analyst nothing.

Still open: this makes runs *agree*, which is not the same as making them *right*.
The rubric encodes my judgement that +0.7pp is noise. That is a defensible call, not
a fact, and it is the kind of threshold I would want an analyst to set, not me.

## 2. The verification gate was throwing away true evidence

The gate that keeps the model from inventing quotes was rejecting real ones. TC-02
came back with one excerpt and two flagged as `Unverifiable excerpt dropped`, which
reads like the model fabricated them. It hadn't.

Adobe's AI-competition risk factor has a page break in the middle of the sentence,
and the extractor leaves it inline:

```
We face increasing competition from companies offering generative and agentic AI
 38
 Table of Contents
 solutions, including but not limited to prompt-based and multi-modal creation...
```

`verify()` required each excerpt to be one contiguous substring of the filing, so
every faithful way to quote that sentence failed — eliding the header with an
ellipsis, closing the gap, or reproducing the header verbatim. The only excerpt that
survived was a fragment stopping dead at the page break, which is exactly the
truncated quote that had been sitting in the report all along without my noticing.

Excerpts are now checked segment by segment, split on ellipses and required in
order, with page furniture folded out of both sides of the comparison. Verified
excerpts went from 3 to 6–7 per run, with no dropped-excerpt flags.

The part I want to be careful about: loosening a gate to admit more evidence is
exactly how you break the thing the gate was for. So `test_verify.py` pins both
directions — ten faithful quotes that must survive, seven fabricated, reordered, or
paraphrased ones that must not. The old gate false-rejects 7 of the 10. The property
being defended is narrow and worth stating precisely: no words the filing does not
contain, in the order it contains them.

Two things I'd flag about how this bug hid. It cost confidence, not just evidence —
the dropped excerpts pushed TC-02 from `high` to `medium`, so the tool understated
what it actually knew. And the error message pointed at the model rather than the
extractor, so the report blamed the one component that was behaving.
