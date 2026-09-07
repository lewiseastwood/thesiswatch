# Notes

## The characteristic failure: a check that exists and never runs

Four bugs so far, and all four are the same bug. Not "the check was wrong" — in every
case the check was correct and would have caught the problem had it been handed the
data. What failed was upstream of it.

1. **The tool call was mis-serialized.** Three excerpts were absorbed into the
   reasoning string and never became `excerpts`, so `verify()` was never called on
   them. They reached the report as raw JSON inside the prose: quotes presented as
   analysis with no gate applied.
2. **The view rendered reasoning without stripping it.** `build_report` ran
   `strip_markup`; the dashboard didn't. Same leaked structure, same unverified
   quotes, now on a web page rather than in a markdown file.
3. **The dashboard trusted the persisted record.** The summary card counted every
   excerpt in the file instead of the verified ones, so a card could read "3
   excerpts" above one rendered quote. And with the judgement implemented twice, the
   report kept printing `**unchanged**` for a claim the dashboard had downgraded.
4. **pytest collected nothing.** 58 assertions across two files, none named `test_*`,
   so `pytest` exited having run none of them. The suite that catches items 1–3 would
   not have run in CI.

The shape they share is that all four fail in the reassuring direction. A gate that
does not run raises no flags, which is indistinguishable from a gate that ran and
found nothing. A runner that collects nothing prints no failures. Silence is the same
output as success, so the system reports health at exactly the moment it stops
checking.

### The defence is counting

The answer isn't more checks. It's asserting that work *happened*, not merely that
nothing failed. The cleanest statement of it here is two lines:

```python
cases = check(failures.append)
assert cases, f"{check.__name__} ran no cases"
assert not failures, ...
```

The second assertion is the one everyone writes. The first is the one that matters: a
check that stopped asserting and a check that passed are indistinguishable from
outside unless you count. The same principle now sits wherever this system could go
quiet.

- CI runs both suites a second time as scripts, because their output states `33/33`
  and `25/25`. A single-step job is tidier, but the case count in the log is the
  specific thing that would catch a fifth recurrence, and the job takes under two
  seconds.
- `assess_integrity` reports how many excerpts it dropped rather than dropping them
  quietly.
- The summary card counts what is actually rendered beneath it, so the card and the
  body cannot disagree.
- `verify()` names the excerpt it rejected. The first version appended an
  unconditional ellipsis, which read as though the excerpt itself ended in one —
  which is how §2 stayed hidden as long as it did.

### Verifying that the tests have teeth

A test that has never failed is a claim, not evidence. So each assertion was checked
by breaking the thing it defends and confirming the suite goes red: every fix
reverted in turn on scratch copies of the source, plus `is_verbatim` mutated to
`return True`, which reduces the verification gate to a pass-through. Seven of the
eight tests have now been observed failing under a mutation aimed at what they
defend. The eighth pins a known limit rather than a defence — see §3 — so there is
nothing to break in it.

The harness then produced the pattern a fifth time, one level up. Its first run
reported four of six reverts as MISSED, and the reverts were correct: `thesiswatch`
was already in `sys.modules`, so editing the file on disk changed nothing and the
code under test was the unmodified code. A mutation check that fails to mutate looks
exactly like a suite with holes in it, and it too fails in the reassuring direction.
Each variant now runs in a fresh interpreter.

---

The three entries below are the individual cases. The first two went wrong on ADBE;
the third is about how the tests for all of it are built.

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

## 3. Fixtures the pipeline cannot produce

Building fixtures only out of what the pipeline currently emits makes the test
conditional on the code already being correct. If `save_run` filters unverified
excerpts, then every run file on disk is clean, so a suite fed real run files can
never tell whether the *reader* checks anything — it passes either way, and it
passes for the wrong reason. The assertion you wanted to make was "the view refuses
bad input"; what you actually asserted was "the writer doesn't produce bad input".
Those come apart the moment anything else writes a record: an older version, a hand
edit, a second producer, a migration.

So `test_dashboard.py` hand-builds records the pipeline cannot write — an excerpt
with `verified` absent, one with it `false`, a reasoning string with tool-call markup
mid-sentence — and renders `app.py` against them with Streamlit's `AppTest`. Those
inputs are unreachable through the real code path today, which is exactly why they
are worth asserting: they are what a run persisted before a fix, or edited after it
was written, actually looks like. This generalizes past this project. Fixtures should
be drawn from what the *format* permits, not from what the current writer happens to
emit, or the test inherits the bug it was written to catch.

Doing that immediately found two holes on the reading side. The summary card counted
`len(claim["excerpts"])` — every excerpt in the record — while the panel below it
rendered only the verified ones, so a card could read "3 excerpts" above one quote.
That is the same card-versus-body mismatch that let the mis-serialized CRM payload
pass for finished analysis. Worse, `claim_panel` rendered the reasoning string raw:
`build_report` had been running `strip_markup` on it since the CRM fix, but the
dashboard never did, so leaked structure and the unverified quotes inside it would
have gone straight to the page with no gate, no marking and no flag.

The other half is that an assertion which passes the first time it runs is
decoration. Each one was checked by reverting its fix on a scratch copy of the source
and confirming the suite fails:

| reverted behaviour | first suite to fail | on |
|---|---|---|
| view skips the integrity pass | `test_dashboard` | unverified excerpt rendered |
| review section hidden when empty | `test_dashboard` | no explicit "nothing found" |
| reasoning not cut at the leak | `test_dashboard` | leaked quote rendered |
| leaked payload keeps its recorded verdict | `test_dashboard` | shown as `unchanged` |
| unverified excerpts not filtered | `test_dashboard` | unverified excerpt rendered |
| unverified excerpts dropped with no flag | `test_dashboard` | drop not reported |

Worth noting the harness bug that nearly hid this: the first pass ran the reverts
in-process, and `thesiswatch` was already in `sys.modules`, so four of the six edits
were never loaded and reported as MISSED. A mutation check that silently fails to
mutate looks exactly like a test suite with holes in it. Each variant now runs in a
fresh interpreter against copies, and the tracked files are never touched.

### Where the check belongs

By this point the same judgement lived in two places — `build_report` stripping and
flagging, `app.py` doing its own version — and they had already drifted: the report
went on printing `**unchanged**` for a claim the dashboard had downgraded to
insufficient evidence. Two implementations of "is this claim trustworthy" will
diverge, and the one that diverges is the one nobody is currently looking at.

That is now three appearances of one bug, each a layer further out: the payload
(`validate_payload`), the markdown report (`strip_markup` in `build_report`), the
dashboard. A check that has to be re-remembered at every consumer is in the wrong
place, not repeatedly forgotten. Both now call `assess_integrity(claim)`, which
returns the claim as it may be presented plus the flags that must accompany it, so a
fourth consumer — a CSV export, an API — inherits it instead of becoming the next
place the gate silently doesn't run. The report rebuilds byte-identical from the
persisted ADBE run, so collapsing the two changed no output.

Two judgements live there. Leaked markup means a field boundary was lost, so the
text is cut at the leak *and* the verdict is downgraded — a partial parse cannot
support `unchanged` any more than it can support `weakened`, so rendering the
recorded verdict is rendering an artefact of the truncation. And an excerpt with no
`verified` marker is dropped, with the drop reported rather than done quietly, which
is the direct lesson of §2.

### A limit worth naming

None of this defends against a forged `verified: true`. Re-deriving that marker
needs the filing text, which a consumer reading `runs/*.json` does not have. The
trust boundary is `verify()`, and `save_run` is the last point at which a forged
marker could be caught; every reader downstream can require only that the marker is
present, never that it was earned. So the test asserts the honest thing — a hand-set
marker *does* render — and pins the half that is enforceable where it lives, that
`save_run` will not write an unmarked excerpt. Better written down as a known limit
than discovered later as a surprise.
