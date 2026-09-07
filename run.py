"""Run ThesisWatch against a company's two most recent 10-Q filings.

    python run.py            # uses DEFAULT_TICKER below
    python run.py MSFT       # needs theses/MSFT.yaml

Analyst-support tool. Does not produce buy/sell recommendations.
"""

import argparse
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import thesiswatch
from thesiswatch import (Context, Edgar, build_report, evaluate_claim,
                         load_thesis, save_run)

DEFAULT_TICKER = "CRM"
FORM = "10-Q"
OUT = Path(__file__).parent / "report.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ticker", nargs="?", default=DEFAULT_TICKER,
                        help=f"ticker with a thesis in theses/ (default: {DEFAULT_TICKER})")
    ticker = parser.parse_args().ticker.upper()

    load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-ant-REPLACE_ME"):
        print("ANTHROPIC_API_KEY is missing. Add a real key to .env.", file=sys.stderr)
        return 1

    email = os.getenv("SEC_UA_EMAIL", "").strip()
    if not email:
        print("SEC_UA_EMAIL is missing. EDGAR rejects requests without a contact "
              "address. Add it to .env.", file=sys.stderr)
        return 1

    thesiswatch.SEC_UA = f"ThesisWatch research/0.1 ({email})"
    thesiswatch.MODEL = os.getenv("THESISWATCH_MODEL", "").strip() or thesiswatch.MODEL

    try:
        thesis = load_thesis(ticker)
    except (FileNotFoundError, ValueError) as e:
        print(e, file=sys.stderr)
        return 1

    edgar = Edgar(thesiswatch.SEC_UA)
    cik = edgar.cik(ticker)
    filings = edgar.filings(cik, FORM, limit=2)
    if len(filings) < 2:
        print(f"Need two {FORM} filings to diff; EDGAR returned {len(filings)} "
              f"for {ticker}.", file=sys.stderr)
        return 1

    current, prior = filings[0], filings[1]
    print(f"{ticker} CIK {cik}")
    print(f"  current: {FORM} filed {current['filingDate']} (period {current['reportDate']})")
    print(f"  prior:   {FORM} filed {prior['filingDate']} (period {prior['reportDate']})")

    print("Downloading and sectioning filings…")
    ctx = Context(edgar, cik, current, prior)
    for which, sections in ctx.sections.items():
        print(f"  {which}: {sorted(sections)}")

    client = anthropic.Anthropic(api_key=api_key)

    verdicts = []
    for claim in thesis["claims"]:
        print(f"Evaluating {claim['id']} with {thesiswatch.MODEL}…")
        v = evaluate_claim(client, ctx, claim)
        print(f"  {v.verdict} (confidence {v.confidence}, {v.tool_calls} tool calls)")
        verdicts.append(v)

    OUT.write_text(build_report(ctx, thesis, verdicts))
    print(f"Wrote {OUT}")
    print(f"Wrote {save_run(ticker, thesis, ctx, verdicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
