"""Run the pipeline on the synthetic sample with mock hallucinate_id, then fake_quote.

Prints accepted vs rejected flags and checks that the shortlist is byte-identical to a run
with the LLM off. Usage: uv run python scripts/demo_validation_gate.py
"""

import sys

from comps_pipeline.cli import run_demo
from comps_pipeline.logging_setup import setup_logging

if __name__ == "__main__":
    setup_logging("WARNING")
    sys.exit(run_demo())
