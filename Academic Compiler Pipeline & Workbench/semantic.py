from __future__ import annotations

from dataclasses import dataclass, field
import logging

from models import ASTNode, Diagnostic, SemanticResult, SymbolEntry


LOGGER = logging.getLogger(__name__)


@dataclass
class Scope:
    name: str
    parent: "Scope | None" = None
    symbols: dict[str, SymbolEntry] = field(default_factory=dict)
    children: list["Scope"] = field(default_factory=list)

    def declare(self, entry: SymbolEntry) -> bool:
        if entry.name in self.symbols:
            return False
        self.symbols[entry.name] = entry
        return True

    def resolve(self, name: str) -> SymbolEntry | None:
        current: Scope | None = self
        while current is not None:
            if name in current.symbols:
                return current.symbols[name]
            current = current.parent
        return None


class SemanticAnalyzer:
    def __init__(self) -> None:
        self.scope_counter = 0
        self.using_namespace_std = False
        self.included_headers: set[str] = set()

    def analyze(self, ast: ASTNode | None) -> SemanticResult:
        LOGGER.info("Starting semantic analysis")
        self.scope_counter = 0
        self.using_namespace_std = False
        self.included_headers = set()
        result = SemanticResult()
        if ast is None:
            result.diagnostics.append(
                Diagnostic(phase="semantic", level="error", message="No AST available for semantic analysis.")
            )
            return result

        self.using_namespace_std = ast.metadata.get("namespace") == "std"
        self.included_headers = set(ast.metadata.get("headers", []))
        global_scope = Scope("global")
        self._visit_statements(ast.children, global_scope, result, switch_depth=0)
        result.symbols.extend(self._collect_symbols(global_scope))
        LOGGER.info("Semantic analysis completed with %s diagnostic(s)", len(result.diagnostics))
        return result

    def _visit_statements(
        self,
        statements: list[ASTNode],
        scope: Scope,
        result: SemanticResult,
        switch_depth: int,
    ) -> None:
        encountered_break = False
        for statement in statements:
            if encountered_break:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="warning",
                        message="Statement is unreachable because it appears after a break.",
                        line=statement.line,
                        column=statement.column,
                    )
                )
            self._visit_statement(statement, scope, result, switch_depth)
            if statement.type == "Break":
                encountered_break = True

    def _visit_statement(
        self,
        statement: ASTNode,
        scope: Scope,
        result: SemanticResult,
        switch_depth: int,
    ) -> None:
        if statement.type == "Declaration":
            self._visit_declaration(statement, scope, result)
            return
        if statement.type == "Assignment":
            self._visit_assignment(statement, scope, result)
            return
        if statement.type == "Input":
            self._visit_input(statement, scope, result)
            return
        if statement.type == "Output":
            self._visit_output(statement, scope, result)
            return
        if statement.type == "Switch":
            self._visit_switch(statement, scope, result, switch_depth)
            return
        if statement.type == "Break":
            if switch_depth == 0:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message="Break statement is only valid inside a switch case.",
                        line=statement.line,
                        column=statement.column,
                    )
                )
            return
        result.diagnostics.append(
            Diagnostic(
                phase="semantic",
                level="warning",
                message=f"Unhandled AST node {statement.type}.",
                line=statement.line,
                column=statement.column,
            )
        )

    def _visit_declaration(self, node: ASTNode, scope: Scope, result: SemanticResult) -> None:
        identifier = node.children[0]
        if scope.resolve(identifier.value) is not None:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="error",
                    message=f"Duplicate declaration for variable {identifier.value}.",
                    line=identifier.line,
                    column=identifier.column,
                )
            )
            return
        entry = SymbolEntry(name=identifier.value, type=node.value, scope=scope.name, line=identifier.line)
        scope.declare(entry)
        if len(node.children) > 1:
            expression_type = self._infer_expression_type(node.children[1], scope, result)
            if expression_type is not None and expression_type != node.value:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message=f"Type mismatch: cannot initialize {node.value} with {expression_type}.",
                        line=node.line,
                        column=node.column,
                    )
                )

    def _visit_assignment(self, node: ASTNode, scope: Scope, result: SemanticResult) -> None:
        target = node.children[0]
        symbol = scope.resolve(target.value)
        if symbol is None:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="error",
                    message=f"Undeclared variable {target.value}.",
                    line=target.line,
                    column=target.column,
                )
            )
        expression_type = self._infer_expression_type(node.children[1], scope, result)
        if symbol is not None and expression_type is not None and symbol.type != expression_type:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="error",
                    message=f"Type mismatch: cannot assign {expression_type} to {symbol.type}.",
                    line=node.line,
                    column=node.column,
                )
            )

    def _visit_input(self, node: ASTNode, scope: Scope, result: SemanticResult) -> None:
        self._validate_stream_access(node, "cin", result)
        for identifier in node.children:
            symbol = scope.resolve(identifier.value)
            if symbol is None:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message=f"Undeclared variable {identifier.value}.",
                        line=identifier.line,
                        column=identifier.column,
                    )
                )
                continue
            if symbol.type != "int":
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message=f"Input statement only supports int variables, not {symbol.type}.",
                        line=identifier.line,
                        column=identifier.column,
                    )
                )

    def _visit_output(self, node: ASTNode, scope: Scope, result: SemanticResult) -> None:
        self._validate_stream_access(node, "cout", result)
        for item in node.children:
            if item.type == "String":
                continue
            if item.type == "Endl":
                self._validate_stream_access(item, "endl", result)
                continue
            self._infer_expression_type(item, scope, result)

    def _visit_switch(
        self,
        node: ASTNode,
        scope: Scope,
        result: SemanticResult,
        switch_depth: int,
    ) -> None:
        switch_identifier = node.children[0]
        if scope.resolve(switch_identifier.value) is None:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="error",
                    message=f"Switch variable {switch_identifier.value} is undeclared.",
                    line=switch_identifier.line,
                    column=switch_identifier.column,
                )
            )

        switch_scope = Scope(self._next_scope_name("switch"), parent=scope)
        scope.children.append(switch_scope)
        cases_container = next(child for child in node.children if child.type == "Cases")
        default_node = next((child for child in node.children if child.type == "Default"), None)
        seen_case_values: set[int] = set()

        for index, case_node in enumerate(cases_container.children, start=1):
            if case_node.value in seen_case_values:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message=f"Duplicate case value {case_node.value}.",
                        line=case_node.line,
                        column=case_node.column,
                    )
                )
            else:
                seen_case_values.add(case_node.value)

            case_scope = Scope(f"{switch_scope.name}.case_{index}", parent=switch_scope)
            switch_scope.children.append(case_scope)
            self._visit_statements(case_node.children, case_scope, result, switch_depth + 1)
            if not case_node.children or case_node.children[-1].type != "Break":
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="warning",
                        message=f"Case {case_node.value} falls through because it does not end with break.",
                        line=case_node.line,
                        column=case_node.column,
                    )
                )

        if default_node is None:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="warning",
                    message="Switch statement does not provide a default case.",
                    line=node.line,
                    column=node.column,
                )
            )
        else:
            default_scope = Scope(f"{switch_scope.name}.default", parent=switch_scope)
            switch_scope.children.append(default_scope)
            self._visit_statements(default_node.children, default_scope, result, switch_depth + 1)

    def _infer_expression_type(
        self,
        node: ASTNode,
        scope: Scope,
        result: SemanticResult,
    ) -> str | None:
        if node.type == "Number":
            return "int"
        if node.type == "Identifier":
            symbol = scope.resolve(node.value)
            if symbol is None:
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message=f"Undeclared variable {node.value}.",
                        line=node.line,
                        column=node.column,
                    )
                )
                return None
            return symbol.type
        if node.type == "BinaryOp":
            left_type = self._infer_expression_type(node.children[0], scope, result)
            right_type = self._infer_expression_type(node.children[1], scope, result)
            if left_type != "int" or right_type != "int":
                result.diagnostics.append(
                    Diagnostic(
                        phase="semantic",
                        level="error",
                        message="Arithmetic expressions require integer operands.",
                        line=node.line,
                        column=node.column,
                    )
                )
                return None
            return "int"
        return None

    def _validate_stream_access(self, node: ASTNode, stream_name: str, result: SemanticResult) -> None:
        if "iostream" not in self.included_headers:
            result.diagnostics.append(
                Diagnostic(
                    phase="semantic",
                    level="error",
                    message=f"{stream_name} requires #include <iostream>.",
                    line=node.line,
                    column=node.column,
                )
            )

        if node.metadata.get("qualified"):
            return
        if self.using_namespace_std:
            return
        result.diagnostics.append(
            Diagnostic(
                phase="semantic",
                level="error",
                message=f"Use std::{stream_name} or declare using namespace std; before using {stream_name}.",
                line=node.line,
                column=node.column,
            )
        )

    def _collect_symbols(self, scope: Scope) -> list[SymbolEntry]:
        symbols = list(scope.symbols.values())
        for child in scope.children:
            symbols.extend(self._collect_symbols(child))
        return sorted(symbols, key=lambda entry: (entry.scope, entry.name))

    def _next_scope_name(self, prefix: str) -> str:
        self.scope_counter += 1
        return f"{prefix}_{self.scope_counter}"
