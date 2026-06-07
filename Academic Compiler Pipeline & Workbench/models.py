from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass(slots=True)
class Token:
    type: str
    symbol: str
    lexeme: str
    line: int
    column: int

    def display(self) -> str:
        return f"{self.symbol}({self.lexeme})"


@dataclass(slots=True)
class Diagnostic:
    phase: str
    level: str
    message: str
    line: int | None = None
    column: int | None = None

    def format(self) -> str:
        location = ""
        if self.line is not None and self.column is not None:
            location = f" (line {self.line}, column {self.column})"
        elif self.line is not None:
            location = f" (line {self.line})"
        return f"[{self.level.upper()}] {self.phase}{location}: {self.message}"


@dataclass(slots=True)
class ASTNode:
    type: str
    value: Any = None
    children: list["ASTNode"] = field(default_factory=list)
    line: int | None = None
    column: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "children": [child.to_dict() for child in self.children],
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.line is not None:
            payload["line"] = self.line
        if self.column is not None:
            payload["column"] = self.column
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload

    def pretty_lines(self, prefix: str = "", is_last: bool = True) -> list[str]:
        connector = "`- " if is_last else "|- "
        label = self.type if self.value is None else f"{self.type}: {self.value}"
        lines = [f"{prefix}{connector}{label}"]
        next_prefix = f"{prefix}{'   ' if is_last else '|  '}"
        for index, child in enumerate(self.children):
            lines.extend(child.pretty_lines(next_prefix, index == len(self.children) - 1))
        return lines

    def pretty(self) -> str:
        return "\n".join(self.pretty_lines(prefix="", is_last=True))


@dataclass(frozen=True, slots=True)
class Production:
    index: int
    head: str
    body: tuple[str, ...]

    def format(self) -> str:
        rhs = " ".join(self.body) if self.body else "epsilon"
        return f"{self.index}. {self.head} -> {rhs}"


@dataclass(slots=True)
class ParseStep:
    step: int
    state_stack: list[int]
    symbol_stack: list[str]
    remaining_input: list[str]
    action: str


@dataclass(slots=True)
class ParseTable:
    action: dict[tuple[int, str], str]
    goto: dict[tuple[int, str], int]
    terminals: list[str]
    nonterminals: list[str]
    states: list[list[str]]
    conflicts: list[str]

    def row_symbols(self) -> list[str]:
        return self.terminals + self.nonterminals


@dataclass(slots=True)
class SymbolEntry:
    name: str
    type: str
    scope: str
    line: int | None = None


@dataclass(slots=True)
class SemanticResult:
    symbols: list[SymbolEntry] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionResult:
    output: str = ""
    waiting_for_input: bool = False
    requested_input: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass(slots=True)
class TACInstruction:
    op: str
    result: str | None = None
    arg1: str | None = None
    arg2: str | None = None
    label: str | None = None
    comment: str | None = None

    def to_text(self) -> str:
        if self.op == "label":
            return f"{self.label}:"
        if self.op == "goto":
            return f"goto {self.label}"
        if self.op == "if_eq_goto":
            return f"if {self.arg1} == {self.arg2} goto {self.label}"
        if self.op == "input":
            return f"cin >> {self.result}"
        if self.op == "print":
            return f"cout << {self.arg1}"
        if self.op == "print_str":
            return f'cout << "{self.arg1}"'
        if self.op == "print_nl":
            return "cout << endl"
        if self.op == "assign":
            return f"{self.result} = {self.arg1}"
        if self.op in {"+", "*"}:
            return f"{self.result} = {self.arg1} {self.op} {self.arg2}"
        if self.op == "decl":
            return f"decl {self.arg1} {self.result}"
        if self.op == "nop":
            return self.comment or "nop"
        return self.comment or self.op

    def defines(self) -> set[str]:
        if self.op in {"assign", "+", "*", "input"} and self.result:
            return {self.result}
        return set()

    def uses(self) -> set[str]:
        values: list[str | None] = []
        if self.op in {"assign", "+", "*", "if_eq_goto", "print"}:
            values.extend([self.arg1, self.arg2])
        used = set()
        for value in values:
            if value and _looks_like_name(value):
                used.add(value)
        return used


@dataclass(slots=True)
class CompilationArtifacts:
    source: str
    tokens: list[Token] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    parse_table: ParseTable | None = None
    parse_steps: list[ParseStep] = field(default_factory=list)
    ast: ASTNode | None = None
    semantic: SemanticResult | None = None
    tac: list[TACInstruction] = field(default_factory=list)
    optimized_tac: list[TACInstruction] = field(default_factory=list)


_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _looks_like_name(value: str) -> bool:
    return bool(_NAME_RE.match(value))
