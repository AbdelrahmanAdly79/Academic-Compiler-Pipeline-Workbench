from __future__ import annotations

import logging

from grammar import build_language_grammar
from lexer import Lexer
from models import CompilationArtifacts, Diagnostic
from optimizer import Optimizer
from parser import SLRParser
from semantic import SemanticAnalyzer
from tac import TACGenerator


LOGGER = logging.getLogger(__name__)


class CompilerPipeline:
    def __init__(self) -> None:
        grammar = build_language_grammar()
        self.lexer = Lexer()
        self.parser = SLRParser(grammar)
        self.semantic = SemanticAnalyzer()
        self.tac_generator = TACGenerator()
        self.optimizer = Optimizer()

    def compile(self, source: str) -> CompilationArtifacts:
        LOGGER.info("Compiler pipeline started")
        artifacts = CompilationArtifacts(source=source, parse_table=self.parser.grammar.parse_table)

        tokens, lexer_diagnostics = self.lexer.tokenize(source)
        artifacts.tokens = tokens
        artifacts.diagnostics.extend(lexer_diagnostics)
        if self._has_errors(lexer_diagnostics):
            LOGGER.info("Stopping after lexical analysis because of errors")
            return artifacts

        ast, parse_steps, parser_diagnostics = self.parser.parse(tokens)
        artifacts.parse_steps = parse_steps
        artifacts.ast = ast
        artifacts.diagnostics.extend(parser_diagnostics)
        if self._has_errors(parser_diagnostics):
            LOGGER.info("Stopping after parsing because of errors")
            return artifacts

        semantic_result = self.semantic.analyze(ast)
        artifacts.semantic = semantic_result
        artifacts.diagnostics.extend(semantic_result.diagnostics)
        if self._has_errors(semantic_result.diagnostics):
            LOGGER.info("Stopping after semantic analysis because of errors")
            return artifacts

        artifacts.tac = self.tac_generator.generate(ast)
        artifacts.optimized_tac, notes = self.optimizer.optimize(artifacts.tac)
        artifacts.diagnostics.extend(
            Diagnostic(phase="optimizer", level="info", message=note) for note in notes
        )

        LOGGER.info("Compiler pipeline finished successfully")
        return artifacts

    def _has_errors(self, diagnostics: list[Diagnostic]) -> bool:
        return any(diagnostic.level == "error" for diagnostic in diagnostics)
