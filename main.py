import argparse

from src.pipeline.base import Pipeline
from src.pipeline.steps import Ingest, LLMProcess, SaveOutput


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["gemini", "groq"], default=None)
    p.add_argument("--input", default=None)
    args = p.parse_args()

    ctx = {"input": args.input} if args.input else {}
    result = Pipeline([Ingest(), LLMProcess(provider=args.provider), SaveOutput()]).run(ctx)
    print(result["output"])


if __name__ == "__main__":
    main()
