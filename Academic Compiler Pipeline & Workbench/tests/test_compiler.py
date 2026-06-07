from __future__ import annotations

import unittest
from pathlib import Path

from pipeline import CompilerPipeline
from runtime import RuntimeExecutor
from tac import render_instructions


ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT_DIR / "samples"


class CompilerPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = CompilerPipeline()
        cls.runtime = RuntimeExecutor()

    def _compile_sample(self, name: str):
        source = (SAMPLES_DIR / name).read_text(encoding="utf-8")
        return self.pipeline.compile(source)

    def test_valid_program_runs_full_pipeline(self) -> None:
        artifacts = self._compile_sample("valid_switch_case.txt")
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertFalse(errors)
        self.assertIsNotNone(artifacts.ast)
        self.assertTrue(artifacts.tac)
        self.assertTrue(artifacts.optimized_tac)
        self.assertIn("x = 14", render_instructions(artifacts.optimized_tac))

    def test_invalid_syntax_is_reported(self) -> None:
        artifacts = self._compile_sample("invalid_syntax.txt")
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertTrue(errors)
        self.assertIn("Unexpected token", errors[0].message)
        self.assertFalse(artifacts.tac)

    def test_semantic_errors_stop_code_generation(self) -> None:
        artifacts = self._compile_sample("semantic_errors.txt")
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertTrue(errors)
        self.assertIn("Duplicate declaration", errors[0].message)
        self.assertFalse(artifacts.tac)

    def test_parse_table_is_conflict_free(self) -> None:
        self.assertFalse(self.pipeline.parser.grammar.parse_table.conflicts)

    def test_unqualified_io_requires_using_namespace_std(self) -> None:
        source = """
#include <iostream>

int main() {
    int x = 1;
    cout << x << endl;
    return 0;
}
"""
        artifacts = self.pipeline.compile(source)
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertTrue(errors)
        self.assertIn("using namespace std", errors[0].message)

    def test_iostream_is_required_for_io_symbols(self) -> None:
        source = """
using namespace std;

int main() {
    int x = 1;
    cout << x << endl;
    return 0;
}
"""
        artifacts = self.pipeline.compile(source)
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertTrue(errors)
        self.assertIn("#include <iostream>", errors[0].message)

    def test_qualified_io_is_valid_without_using_namespace_std(self) -> None:
        source = """
#include <iostream>

int main() {
    int x = 1;
    std::cout << "x=" << x << std::endl;
    return 0;
}
"""
        artifacts = self.pipeline.compile(source)
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertFalse(errors)
        self.assertIn('cout << "x="', render_instructions(artifacts.tac))

    def test_runtime_executor_handles_cin_cout_and_switch(self) -> None:
        source = """
#include <iostream>

int main() {
    int x;
    int y = 0;
    std::cin >> x;
    switch (x) {
    case 1:
        y = 10;
        break;
    default:
        y = 20;
    }
    std::cout << "y=" << y << std::endl;
    return 0;
}
"""
        artifacts = self.pipeline.compile(source)
        errors = [diagnostic for diagnostic in artifacts.diagnostics if diagnostic.level == "error"]
        self.assertFalse(errors)

        waiting = self.runtime.execute(artifacts.ast, [])
        self.assertTrue(waiting.waiting_for_input)
        self.assertEqual(waiting.requested_input, "x")

        executed = self.runtime.execute(artifacts.ast, ["1"])
        self.assertFalse(executed.waiting_for_input)
        self.assertEqual(executed.output, "y=10\n")


if __name__ == "__main__":
    unittest.main()
