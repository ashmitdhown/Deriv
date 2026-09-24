"""Run the ticket pipeline: python main.py [--tickets PATH] [--kb PATH] [--out-dir DIR]"""
import argparse
import sys
from pathlib import Path

from src.config import PROJECT_DIR, settings
from src.pipeline import Pipeline, PipelineError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Process support tickets into grounded reply drafts.")
    p.add_argument("--tickets", type=Path, default=settings.tickets_path)
    p.add_argument("--kb", type=Path, default=settings.kb_path)
    p.add_argument("--out-dir", type=Path, default=PROJECT_DIR)
    args = p.parse_args(argv)
    try:
        out = Pipeline().run(args.tickets, args.kb, args.out_dir / "results.json", args.out_dir / "debug_report.json")
    except PipelineError as e:
        print(f"ERROR: {e}. No results were written.", file=sys.stderr)
        return 1
    s = out.debug["summary"]
    print(f"Processed {s['tickets_processed']} ticket(s), rejected {s['tickets_rejected']}, "
          f"escalated {s['escalated']}. Wrote results.json and debug_report.json to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
