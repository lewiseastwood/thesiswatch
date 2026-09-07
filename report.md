# ThesisWatch — CRM

**Analyst-support tool. Not investment advice. No buy/sell recommendation is produced or implied.**

- Thesis: Salesforce — subscription growth / AI competition thesis
- Current filing: 10-Q · filed 2026-08-27 · [0001108524-26-000190](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000190/0001108524-26-000190-index.htm)
- Prior filing: 10-Q · filed 2026-05-28 · [0001108524-26-000127](https://www.sec.gov/Archives/edgar/data/1108524/000110852426000127/0001108524-26-000127-index.htm)

## Summary

| Claim | Verdict | Band | Confidence | Evidence | Tool calls |
|---|---|---|---|---|---|
| TC-01 | **unchanged** | above watch | medium | 3 excerpt(s), 2 metric(s) | 11 |
| TC-02 | **unchanged** | — | medium | 5 excerpt(s), 0 metric(s) | 10 |

## Claim detail

### TC-01 — Subscription and support revenue growth remains healthy year over year, and subscription — not professional services — is what carries the total

**unchanged** · confidence medium · band above watch

Total revenue growth (the only XBRL-tagged figure) was 10.83% YoY in the current quarter (Q2 FY27: $11,345M vs $10,236M) versus 13.27% YoY in the prior quarter (Q1 FY27: $11,133M vs $9,829M). Both remain above the 10% watch threshold and well clear of the 8% falsified level, so the metric stays in the same "above_watch" band; the ~2.4pp deceleration is the only quarter-over-quarter change and is not large enough, on its own, to call the claim's core assertion weakened.

More importantly for the qualitative half of the claim (subscription vs. professional services), the MD&A revenue tables show subscription and support revenue growing 12% YoY in the current quarter ($10,820M vs $9,690M) versus 14% in the prior quarter ($10,593M vs $9,297M) — still healthy double-digit growth — while professional services and other revenue swung from +2% YoY in the prior quarter to -4% YoY in the current quarter. This means professional services is now an outright drag, not a contributor, which if anything reinforces (rather than undermines) the claim that subscription — not professional services — carries the total. None of the stated falsifiers (total revenue below 8% for two consecutive quarters, subscription decelerating while professional services carries the total, or management guidance below the falsified band) are met; no forward revenue guidance was found in this 10-Q's MD&A or risk factors. Given the modest total-revenue deceleration is offset by a clearer confirmation of the subscription-driven composition, and the metric stays within the same band with no falsifier triggered, I assess this as unchanged rather than weakened, though the deceleration is noted for analyst attention.

Note: the subscription vs. professional services revenue split and their individual YoY growth rates are text-sourced from the MD&A revenue tables, not from an XBRL tag, per the claim's own caveat.

- `RevenueFromContractWithCustomerExcludingAssessedTax` Q2 FY2027 (three months ended 2026-07-31): 11,345,000,000 — vs $10,236M in Q2 FY2026, ~10.83% YoY growth
- `RevenueFromContractWithCustomerExcludingAssessedTax` Q1 FY2027 (three months ended 2026-04-30): 11,133,000,000 — vs $9,829M in Q1 FY2026, ~13.27% YoY growth

> Subscription and support $ 10,820 $ 9,690 $ 1,130 12 % Professional services and other 525 546 (21) (4) Total revenues $ 11,345 $ 10,236 $ 1,109 11 %

  — current filing, mda

> Subscription and support $ 10,593 $ 9,297 $ 1,296 14 % Professional services and other 540 532 8 2 Total revenues $ 11,133 $ 9,829 $ 1,304 13 %

  — prior filing, mda

> The decrease in professional services and other revenues for the three and six months ended July 31, 2026 was primarily due to less demand for larger, multi-year transformation engagements, which may continue in the near term.

  — current filing, mda

### TC-02 — Competitive and AI-related risk language has not materially expanded relative to the prior filing

**unchanged** · confidence medium

Comparing the current 10-Q (period ended 7/31/2026) to the prior 10-Q (period ended 4/30/2026), the risk-factor and MD&A language on AI-related competition is materially the same. The "AI-native companies and emerging startups that leverage generative AI and large language models" competitor bullet is verbatim identical in both filings. The paragraph describing competitors incorporating AI more efficiently and customers choosing "competitive products and services in lieu of purchasing our products and services" is also verbatim identical (only the page number changed, 53→55). The diff_section tool for risk_factors shows large blocks marked ADDED/REMOVED that are near-identical in wording (differences are boilerplate: 'Annual Report' vs 'Quarterly Report' framing text carried over from incorporation-by-reference boilerplate, minor punctuation like "Data360" vs "Data 360", and formatting), not new substantive risk content. MD&A shows the attrition rate held flat at approximately eight percent in both periods, and management did not attribute pricing pressure, longer sales cycles, or attrition to AI competitors — attrition commentary and competitive dynamics discussion are unchanged. No new risk factor naming AI competitors or agentic AI substitutes was found, and no management commentary tied competitive/financial pressure specifically to AI competition. The claim's falsifiers were not triggered, and disclosure volume/substance is essentially the same as the prior quarter.


> AI-native companies and emerging startups that leverage generative AI and large language models as the core foundation of their architecture, offering highly specialized, autonomous, or automated solutions that may bypass traditional business process workflows or displace established user interfaces

  — current filing, risk_factors

> AI-native companies and emerging startups that leverage generative AI and large language models as the core foundation of their architecture, offering highly specialized, autonomous, or automated solutions that may bypass traditional business process workflows or displace established user interfaces

  — prior filing, risk_factors

> Even if our products and services are more effective than the products and services that our competitors offer, potential customers might select competitive … products and services in lieu of purchasing our products and services.

  — current filing, risk_factors

> As of July 31, 2026, our attrition rate, excluding Slack self-service, Informatica, and current year acquisitions, was approximately eight percent.

  — current filing, mda

> As of April 30, 2026, our attrition rate, excluding Slack self-service, Informatica, and current year acquisitions, was approximately eight percent.

  — prior filing, mda

## Requires analyst review

- **TC-01** — Total revenue YoY growth decelerated from ~13.3% to ~10.8% between the two quarters, a larger-than-trivial move within the same 'above_watch' band; an analyst focused purely on trajectory might read this as early weakening even though no band or falsifier threshold was crossed.
- **TC-01** — Subscription and support revenue growth (12% vs 14% prior quarter) and professional services growth (-4% vs +2% prior quarter) are read from the MD&A revenue variance table, not from a dedicated XBRL tag, so these figures are text-sourced rather than XBRL-verified.
- **TC-01** — No explicit forward revenue guidance language was found in this 10-Q's MD&A or risk factors sections to assess the 'management guides below falsified band' falsifier; Salesforce typically issues guidance via separate earnings materials not captured here.
- **TC-02** — Risk-factor diff tool flagged large ADDED/REMOVED blocks that are substantively boilerplate rewording (page-number and section-title differences); verified manually via search_filing that the AI-competitor bullet and AI-driven pricing-pressure sentence are verbatim identical across filings.

Verify all figures against the source filing before acting on them.