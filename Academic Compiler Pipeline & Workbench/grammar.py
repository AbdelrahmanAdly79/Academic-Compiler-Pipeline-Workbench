from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import logging

from models import ParseTable, Production


LOGGER = logging.getLogger(__name__)

EPSILON = "epsilon"
EOF_SYMBOL = "$"


@dataclass(frozen=True, slots=True)
class LRItem:
    production_index: int
    dot: int


class Grammar:
    def __init__(
        self,
        start_symbol: str,
        productions: list[tuple[str, tuple[str, ...]]],
        terminal_order: list[str],
    ) -> None:
        self.start_symbol = start_symbol
        self.augmented_start = f"{start_symbol}'"

        ordered_nonterminals: list[str] = []
        for head, _ in productions:
            if head not in ordered_nonterminals:
                ordered_nonterminals.append(head)
        self.nonterminals = ordered_nonterminals

        self.productions: list[Production] = [
            Production(0, self.augmented_start, (self.start_symbol,))
        ]
        for index, (head, body) in enumerate(productions, start=1):
            self.productions.append(Production(index, head, body))

        self.productions_by_head: dict[str, list[Production]] = defaultdict(list)
        for production in self.productions:
            self.productions_by_head[production.head].append(production)

        body_symbols = {symbol for _, body in productions for symbol in body if symbol}
        self.terminals = [symbol for symbol in terminal_order if symbol in body_symbols]
        self.terminals_for_table = self.terminals + [EOF_SYMBOL]
        self.symbol_order = self.terminals + [EOF_SYMBOL] + self.nonterminals + [self.augmented_start]

        self.first_sets = self._compute_first_sets()
        self.follow_sets = self._compute_follow_sets()
        self.states, self.transitions = self._build_canonical_collection()
        self.parse_table = self._build_parse_table()

    def _compute_first_sets(self) -> dict[str, set[str]]:
        first_sets: dict[str, set[str]] = {symbol: set() for symbol in self.nonterminals + [self.augmented_start]}
        for terminal in self.terminals + [EOF_SYMBOL]:
            first_sets[terminal] = {terminal}

        changed = True
        while changed:
            changed = False
            for production in self.productions:
                target = first_sets[production.head]
                if not production.body:
                    if EPSILON not in target:
                        target.add(EPSILON)
                        changed = True
                    continue

                nullable_prefix = True
                for symbol in production.body:
                    symbol_first = first_sets.get(symbol, {symbol})
                    before = len(target)
                    target.update(symbol_first - {EPSILON})
                    if len(target) != before:
                        changed = True
                    if EPSILON not in symbol_first:
                        nullable_prefix = False
                        break
                if nullable_prefix and EPSILON not in target:
                    target.add(EPSILON)
                    changed = True

        return first_sets

    def _first_of_sequence(self, symbols: tuple[str, ...]) -> set[str]:
        if not symbols:
            return {EPSILON}

        result: set[str] = set()
        for symbol in symbols:
            symbol_first = self.first_sets.get(symbol, {symbol})
            result.update(symbol_first - {EPSILON})
            if EPSILON not in symbol_first:
                return result
        result.add(EPSILON)
        return result

    def _compute_follow_sets(self) -> dict[str, set[str]]:
        follow_sets: dict[str, set[str]] = {symbol: set() for symbol in self.nonterminals + [self.augmented_start]}
        follow_sets[self.start_symbol].add(EOF_SYMBOL)

        changed = True
        while changed:
            changed = False
            for production in self.productions[1:]:
                for index, symbol in enumerate(production.body):
                    if symbol not in follow_sets:
                        continue
                    suffix = production.body[index + 1 :]
                    first_suffix = self._first_of_sequence(suffix)
                    before = len(follow_sets[symbol])
                    follow_sets[symbol].update(first_suffix - {EPSILON})
                    if not suffix or EPSILON in first_suffix:
                        follow_sets[symbol].update(follow_sets[production.head])
                    if len(follow_sets[symbol]) != before:
                        changed = True
        return follow_sets

    def closure(self, items: frozenset[LRItem]) -> frozenset[LRItem]:
        closure_set = set(items)
        changed = True
        while changed:
            changed = False
            for item in list(closure_set):
                production = self.productions[item.production_index]
                if item.dot >= len(production.body):
                    continue
                next_symbol = production.body[item.dot]
                if next_symbol not in self.productions_by_head:
                    continue
                for candidate in self.productions_by_head[next_symbol]:
                    new_item = LRItem(candidate.index, 0)
                    if new_item not in closure_set:
                        closure_set.add(new_item)
                        changed = True
        return frozenset(closure_set)

    def goto(self, items: frozenset[LRItem], symbol: str) -> frozenset[LRItem]:
        moved = {
            LRItem(item.production_index, item.dot + 1)
            for item in items
            if item.dot < len(self.productions[item.production_index].body)
            and self.productions[item.production_index].body[item.dot] == symbol
        }
        if not moved:
            return frozenset()
        return self.closure(frozenset(moved))

    def _build_canonical_collection(self) -> tuple[list[frozenset[LRItem]], dict[tuple[int, str], int]]:
        LOGGER.info("Generating canonical LR(0) item sets")
        start_state = self.closure(frozenset({LRItem(0, 0)}))
        states = [start_state]
        transitions: dict[tuple[int, str], int] = {}
        state_lookup = {start_state: 0}
        queue: deque[frozenset[LRItem]] = deque([start_state])

        while queue:
            state = queue.popleft()
            state_index = state_lookup[state]
            next_symbols = []
            for item in state:
                production = self.productions[item.production_index]
                if item.dot < len(production.body):
                    symbol = production.body[item.dot]
                    if symbol not in next_symbols:
                        next_symbols.append(symbol)
            next_symbols.sort(key=self._symbol_sort_key)

            for symbol in next_symbols:
                target = self.goto(state, symbol)
                if not target:
                    continue
                if target not in state_lookup:
                    state_lookup[target] = len(states)
                    states.append(target)
                    queue.append(target)
                transitions[(state_index, symbol)] = state_lookup[target]

        LOGGER.info("Generated %s LR state(s)", len(states))
        return states, transitions

    def _build_parse_table(self) -> ParseTable:
        action: dict[tuple[int, str], str] = {}
        goto: dict[tuple[int, str], int] = {}
        conflicts: list[str] = []

        for state_index, state in enumerate(self.states):
            for item in state:
                production = self.productions[item.production_index]
                if item.dot < len(production.body):
                    symbol = production.body[item.dot]
                    target = self.transitions.get((state_index, symbol))
                    if target is None:
                        continue
                    if symbol in self.terminals:
                        self._register_action(
                            action,
                            conflicts,
                            state_index,
                            symbol,
                            f"s{target}",
                        )
                    elif symbol in self.nonterminals:
                        goto[(state_index, symbol)] = target
                else:
                    if production.head == self.augmented_start:
                        self._register_action(action, conflicts, state_index, EOF_SYMBOL, "acc")
                        continue
                    for symbol in sorted(self.follow_sets[production.head], key=self._symbol_sort_key):
                        self._register_action(
                            action,
                            conflicts,
                            state_index,
                            symbol,
                            f"r{production.index}",
                        )

        states = [self._format_state(state) for state in self.states]
        if conflicts:
            LOGGER.warning("Grammar produced %s conflict(s)", len(conflicts))
        else:
            LOGGER.info("Grammar is SLR(1) conflict-free")
        return ParseTable(
            action=action,
            goto=goto,
            terminals=self.terminals_for_table,
            nonterminals=self.nonterminals,
            states=states,
            conflicts=conflicts,
        )

    def _register_action(
        self,
        action_table: dict[tuple[int, str], str],
        conflicts: list[str],
        state_index: int,
        symbol: str,
        action_value: str,
    ) -> None:
        key = (state_index, symbol)
        existing = action_table.get(key)
        if existing is None or existing == action_value:
            action_table[key] = action_value
            return
        conflicts.append(
            f"Conflict in state {state_index} on symbol {symbol}: {existing} vs {action_value}"
        )

    def _format_state(self, state: frozenset[LRItem]) -> list[str]:
        lines: list[str] = []
        for item in sorted(state, key=lambda current: (current.production_index, current.dot)):
            production = self.productions[item.production_index]
            body = list(production.body)
            body.insert(item.dot, "•")
            rhs = " ".join(body) if body else "•"
            lines.append(f"{production.head} -> {rhs}")
        return lines

    def _symbol_sort_key(self, symbol: str) -> tuple[int, int]:
        try:
            return (0, self.symbol_order.index(symbol))
        except ValueError:
            return (1, len(self.symbol_order))

    def format_parse_table_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for state_index in range(len(self.states)):
            row = {"State": str(state_index)}
            for terminal in self.terminals_for_table:
                row[terminal] = self.parse_table.action.get((state_index, terminal), "")
            for nonterminal in self.nonterminals:
                value = self.parse_table.goto.get((state_index, nonterminal))
                row[nonterminal] = "" if value is None else str(value)
            rows.append(row)
        return rows


def build_language_grammar() -> Grammar:
    productions = [
        ("Program", ("OptIncludeList", "OptUsingDirective", "MainFunction")),
        ("OptIncludeList", ("IncludeList",)),
        ("OptIncludeList", ()),
        ("IncludeList", ("IncludeList", "Include")),
        ("IncludeList", ("Include",)),
        ("Include", ("#", "include", "<", "id", ">")),
        ("OptUsingDirective", ("UsingDirective",)),
        ("OptUsingDirective", ()),
        ("UsingDirective", ("using", "namespace", "std", ";")),
        ("MainFunction", ("int", "main", "(", ")", "{", "MainBody", "}")),
        ("MainBody", ("StmtList", "ReturnStmt")),
        ("MainBody", ("ReturnStmt",)),
        ("StmtList", ("StmtList", "Stmt")),
        ("StmtList", ("Stmt",)),
        ("Stmt", ("Decl",)),
        ("Stmt", ("Assign",)),
        ("Stmt", ("InputStmt",)),
        ("Stmt", ("OutputStmt",)),
        ("Stmt", ("SwitchStmt",)),
        ("Stmt", ("BreakStmt",)),
        ("Decl", ("int", "id", ";")),
        ("Decl", ("int", "id", "=", "Expr", ";")),
        ("Assign", ("id", "=", "Expr", ";")),
        ("InputStmt", ("InputRef", "InputList", ";")),
        ("InputRef", ("cin",)),
        ("InputRef", ("std", "::", "cin")),
        ("InputList", ("InputList", ">>", "id")),
        ("InputList", (">>", "id")),
        ("OutputStmt", ("OutputRef", "OutputList", ";")),
        ("OutputRef", ("cout",)),
        ("OutputRef", ("std", "::", "cout")),
        ("OutputList", ("OutputList", "<<", "OutputItem")),
        ("OutputList", ("<<", "OutputItem")),
        ("OutputItem", ("Expr",)),
        ("OutputItem", ("string",)),
        ("OutputItem", ("EndlRef",)),
        ("EndlRef", ("endl",)),
        ("EndlRef", ("std", "::", "endl")),
        ("Expr", ("Expr", "+", "Term")),
        ("Expr", ("Term",)),
        ("Term", ("Term", "*", "Factor")),
        ("Term", ("Factor",)),
        ("Factor", ("id",)),
        ("Factor", ("num",)),
        ("Factor", ("(", "Expr", ")")),
        ("SwitchStmt", ("switch", "(", "id", ")", "{", "CaseList", "OptDefault", "}")),
        ("CaseList", ("CaseList", "Case")),
        ("CaseList", ("Case",)),
        ("Case", ("case", "num", ":", "StmtList")),
        ("OptDefault", ("DefaultCase",)),
        ("OptDefault", ()),
        ("DefaultCase", ("default", ":", "StmtList")),
        ("BreakStmt", ("break", ";")),
        ("ReturnStmt", ("return", "num", ";")),
    ]

    terminal_order = [
        "#",
        "include",
        "<",
        ">",
        "using",
        "namespace",
        "std",
        "int",
        "main",
        "return",
        "switch",
        "case",
        "break",
        "default",
        "cin",
        "cout",
        "endl",
        "id",
        "num",
        "string",
        "+",
        "*",
        "=",
        "::",
        "<<",
        ">>",
        ";",
        ":",
        "{",
        "}",
        "(",
        ")",
    ]
    return Grammar("Program", productions, terminal_order)
