from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from pipeline import CompilerPipeline
from tac import render_instructions


ROOT_DIR = Path(__file__).resolve().parent
LOG_FILE = ROOT_DIR / "compiler.log"


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_cli(path: Path) -> int:
    pipeline = CompilerPipeline()
    artifacts = pipeline.compile(path.read_text(encoding="utf-8"))

    print("=== Diagnostics ===")
    if artifacts.diagnostics:
        for diagnostic in artifacts.diagnostics:
            print(diagnostic.format())
    else:
        print("No diagnostics.")

    print("\n=== Tokens ===")
    for token in artifacts.tokens:
        print(f"{token.type:<10} {token.lexeme:<12} line={token.line} col={token.column}")

    print("\n=== Parse Steps ===")
    for step in artifacts.parse_steps:
        stack = [str(step.state_stack[0])]
        for symbol, state in zip(step.symbol_stack, step.state_stack[1:]):
            stack.extend([symbol, str(state)])
        print(f"{step.step:>3}: {' '.join(stack)} | {' '.join(step.remaining_input)} | {step.action}")

    print("\n=== AST JSON ===")
    if artifacts.ast is not None:
        print(json.dumps(artifacts.ast.to_dict(), indent=2))
    else:
        print("<no AST>")

    print("\n=== TAC ===")
    print(render_instructions(artifacts.tac))

    print("\n=== Optimized TAC ===")
    print(render_instructions(artifacts.optimized_tac))

    return 1 if any(diagnostic.level == "error" for diagnostic in artifacts.diagnostics) else 0


def main() -> int:
    configure_logging()

    arg_parser = argparse.ArgumentParser(description="Academic mini compiler workbench")
    arg_parser.add_argument("--cli", type=Path, help="Compile a source file in CLI mode instead of launching the GUI.")
    args = arg_parser.parse_args()

    if args.cli is not None:
        return run_cli(args.cli)

    try:
        from gui import launch_gui

        launch_gui()
        return 0
    except ModuleNotFoundError as exc:
        logging.getLogger(__name__).error("GUI toolkit is unavailable: %s", exc)
        print(
            "GUI launch failed because this Python environment does not include the required PySide6 runtime.\n"
            "Use CLI mode for now, or run the project in a Python installation with PySide6 available."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
