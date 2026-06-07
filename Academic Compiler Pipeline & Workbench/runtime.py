from __future__ import annotations

from dataclasses import dataclass
import logging

from models import ASTNode, Diagnostic, ExecutionResult


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _InputRequired(Exception):
    variable: str


class _BreakSignal(Exception):
    pass


@dataclass(slots=True)
class _RuntimeFailure(Exception):
    diagnostic: Diagnostic


class RuntimeExecutor:
    def __init__(self) -> None:
        self.environment: dict[str, int] = {}
        self.inputs: list[str] = []
        self.input_index = 0
        self.output_parts: list[str] = []

    def execute(self, ast: ASTNode | None, inputs: list[str] | None = None) -> ExecutionResult:
        LOGGER.info("Starting runtime execution")
        self.environment = {}
        self.inputs = inputs or []
        self.input_index = 0
        self.output_parts = []

        if ast is None:
            return ExecutionResult(
                diagnostics=[Diagnostic(phase="runtime", level="error", message="No AST available to execute.")]
            )

        try:
            self._execute_statements(ast.children)
        except _InputRequired as request:
            LOGGER.info("Runtime paused for input %s", request.variable)
            return ExecutionResult(
                output="".join(self.output_parts),
                waiting_for_input=True,
                requested_input=request.variable,
            )
        except _RuntimeFailure as failure:
            LOGGER.error("Runtime execution failed: %s", failure.diagnostic.message)
            return ExecutionResult(output="".join(self.output_parts), diagnostics=[failure.diagnostic])
        except _BreakSignal:
            return ExecutionResult(
                output="".join(self.output_parts),
                diagnostics=[
                    Diagnostic(
                        phase="runtime",
                        level="error",
                        message="Break statement reached outside of a switch.",
                    )
                ],
            )

        LOGGER.info("Runtime execution completed")
        return ExecutionResult(output="".join(self.output_parts))

    def _execute_statements(self, statements: list[ASTNode]) -> None:
        for statement in statements:
            self._execute_statement(statement)

    def _execute_statement(self, node: ASTNode) -> None:
        if node.type == "Declaration":
            name = node.children[0].value
            value = 0 if len(node.children) == 1 else self._evaluate_expression(node.children[1])
            self.environment[name] = value
            return

        if node.type == "Assignment":
            name = node.children[0].value
            self._ensure_declared(name, node.children[0].line, node.children[0].column)
            self.environment[name] = self._evaluate_expression(node.children[1])
            return

        if node.type == "Input":
            for identifier in node.children:
                if self.input_index >= len(self.inputs):
                    raise _InputRequired(identifier.value)
                self._ensure_declared(identifier.value, identifier.line, identifier.column)
                raw_value = self.inputs[self.input_index]
                self.input_index += 1
                try:
                    self.environment[identifier.value] = int(raw_value)
                except ValueError as exc:
                    raise _RuntimeFailure(
                        Diagnostic(
                            phase="runtime",
                            level="error",
                            message=f"Input for {identifier.value} must be an integer, got {raw_value!r}.",
                            line=identifier.line,
                            column=identifier.column,
                        )
                    ) from exc
            return

        if node.type == "Output":
            for item in node.children:
                if item.type == "String":
                    self.output_parts.append(str(item.value))
                    continue
                if item.type == "Endl":
                    self.output_parts.append("\n")
                    continue
                self.output_parts.append(str(self._evaluate_expression(item)))
            return

        if node.type == "Switch":
            self._execute_switch(node)
            return

        if node.type == "Break":
            raise _BreakSignal()

        raise _RuntimeFailure(
            Diagnostic(
                phase="runtime",
                level="error",
                message=f"Unsupported runtime node {node.type}.",
                line=node.line,
                column=node.column,
            )
        )

    def _execute_switch(self, node: ASTNode) -> None:
        switch_identifier = node.children[0]
        self._ensure_declared(switch_identifier.value, switch_identifier.line, switch_identifier.column)
        switch_value = self.environment[switch_identifier.value]
        cases_container = next(child for child in node.children if child.type == "Cases")
        default_node = next((child for child in node.children if child.type == "Default"), None)

        matched_case = False
        fallthrough = False
        for case_node in cases_container.children:
            if fallthrough or case_node.value == switch_value:
                matched_case = True
                fallthrough = True
                try:
                    self._execute_statements(case_node.children)
                except _BreakSignal:
                    return

        if default_node is not None and (fallthrough or not matched_case):
            try:
                self._execute_statements(default_node.children)
            except _BreakSignal:
                return

    def _evaluate_expression(self, node: ASTNode) -> int:
        if node.type == "Number":
            return int(node.value)
        if node.type == "Identifier":
            self._ensure_declared(node.value, node.line, node.column)
            return self.environment[node.value]
        if node.type == "BinaryOp":
            left = self._evaluate_expression(node.children[0])
            right = self._evaluate_expression(node.children[1])
            if node.value == "+":
                return left + right
            if node.value == "*":
                return left * right
        raise _RuntimeFailure(
            Diagnostic(
                phase="runtime",
                level="error",
                message=f"Unsupported expression node {node.type}.",
                line=node.line,
                column=node.column,
            )
        )

    def _ensure_declared(self, name: str, line: int | None, column: int | None) -> None:
        if name in self.environment:
            return
        raise _RuntimeFailure(
            Diagnostic(
                phase="runtime",
                level="error",
                message=f"Variable {name} is not available at runtime.",
                line=line,
                column=column,
            )
        )
