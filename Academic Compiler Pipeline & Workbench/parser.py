from __future__ import annotations

import logging

from grammar import EOF_SYMBOL, Grammar, build_language_grammar
from models import ASTNode, Diagnostic, ParseStep, Token


LOGGER = logging.getLogger(__name__)


class SLRParser:
    def __init__(self, grammar: Grammar | None = None) -> None:
        self.grammar = grammar or build_language_grammar()

    def parse(self, tokens: list[Token]) -> tuple[ASTNode | None, list[ParseStep], list[Diagnostic]]:
        LOGGER.info("Starting SLR parsing")
        diagnostics: list[Diagnostic] = []
        for conflict in self.grammar.parse_table.conflicts:
            diagnostics.append(
                Diagnostic(
                    phase="parser",
                    level="error",
                    message=conflict,
                )
            )
        if any(diagnostic.level == "error" for diagnostic in diagnostics):
            return None, [], diagnostics

        state_stack = [0]
        symbol_stack: list[str] = []
        value_stack: list[object] = []
        steps: list[ParseStep] = []
        index = 0
        step_number = 1

        while True:
            state = state_stack[-1]
            lookahead = tokens[index]
            lookahead_symbol = self._token_symbol(lookahead)
            action = self.grammar.parse_table.action.get((state, lookahead_symbol))
            stack_snapshot = state_stack.copy()
            symbol_snapshot = symbol_stack.copy()
            remaining_input = [token.display() for token in tokens[index:]]

            if action is None:
                expected = sorted(
                    {
                        symbol
                        for (row_state, symbol), value in self.grammar.parse_table.action.items()
                        if row_state == state and value
                    }
                )
                diagnostics.append(
                    Diagnostic(
                        phase="parser",
                        level="error",
                        message=(
                            f"Unexpected token {lookahead.display()}. "
                            f"Expected one of: {', '.join(expected) if expected else 'no valid continuation'}."
                        ),
                        line=lookahead.line,
                        column=lookahead.column,
                    )
                )
                steps.append(
                    ParseStep(
                        step=step_number,
                        state_stack=stack_snapshot,
                        symbol_stack=symbol_snapshot,
                        remaining_input=remaining_input,
                        action="error",
                    )
                )
                LOGGER.error("Parsing failed at line %s column %s", lookahead.line, lookahead.column)
                return None, steps, diagnostics

            steps.append(
                ParseStep(
                    step=step_number,
                    state_stack=stack_snapshot,
                    symbol_stack=symbol_snapshot,
                    remaining_input=remaining_input,
                    action=self._describe_action(action),
                )
            )
            step_number += 1

            if action == "acc":
                LOGGER.info("Parsing completed successfully")
                if not value_stack:
                    diagnostics.append(
                        Diagnostic(phase="parser", level="error", message="Parser accepted without producing an AST.")
                    )
                    return None, steps, diagnostics
                root = value_stack[-1]
                return root if isinstance(root, ASTNode) else None, steps, diagnostics

            if action.startswith("s"):
                target_state = int(action[1:])
                state_stack.append(target_state)
                symbol_stack.append(lookahead_symbol)
                value_stack.append(lookahead)
                index += 1
                continue

            if action.startswith("r"):
                production = self.grammar.productions[int(action[1:])]
                pop_count = len(production.body)
                rhs_values = value_stack[-pop_count:] if pop_count else []
                if pop_count:
                    del value_stack[-pop_count:]
                    del symbol_stack[-pop_count:]
                    del state_stack[-pop_count:]

                reduced_value = self._apply_semantic_action(production.head, production.body, rhs_values)
                goto_state = self.grammar.parse_table.goto.get((state_stack[-1], production.head))
                if goto_state is None:
                    diagnostics.append(
                        Diagnostic(
                            phase="parser",
                            level="error",
                            message=f"Missing goto transition for {production.head}.",
                        )
                    )
                    return None, steps, diagnostics
                symbol_stack.append(production.head)
                state_stack.append(goto_state)
                value_stack.append(reduced_value)
                continue

            diagnostics.append(
                Diagnostic(phase="parser", level="error", message=f"Unknown parser action {action}.")
            )
            return None, steps, diagnostics

    def _token_symbol(self, token: Token) -> str:
        return EOF_SYMBOL if token.type == "EOF" else token.symbol

    def _describe_action(self, action: str) -> str:
        if action == "acc":
            return "accept"
        if action.startswith("s"):
            return f"shift {action[1:]}"
        if action.startswith("r"):
            production = self.grammar.productions[int(action[1:])]
            rhs = " ".join(production.body) if production.body else "epsilon"
            return f"reduce {production.head} -> {rhs}"
        return action

    def _apply_semantic_action(
        self,
        head: str,
        body: tuple[str, ...],
        values: list[object],
    ) -> object:
        if head == "Program":
            main_function = values[2]
            line = main_function["line"]
            return ASTNode(
                "Program",
                children=main_function["statements"],
                line=line,
                metadata={
                    "headers": values[0],
                    "namespace": values[1],
                    "function": main_function["name"],
                    "return": main_function["return"],
                },
            )

        if head == "OptIncludeList" and body == ("IncludeList",):
            return values[0]
        if head == "OptIncludeList" and not body:
            return []
        if head == "IncludeList" and body == ("IncludeList", "Include"):
            return [*values[0], values[1]]
        if head == "IncludeList" and body == ("Include",):
            return [values[0]]
        if head == "Include":
            header_token = values[3]
            return header_token.lexeme

        if head == "OptUsingDirective" and body == ("UsingDirective",):
            return values[0]
        if head == "OptUsingDirective" and not body:
            return None
        if head == "UsingDirective":
            return "std"

        if head == "MainFunction":
            int_token = values[0]
            name_token = values[1]
            body_payload = values[5]
            return {
                "name": name_token.lexeme,
                "line": int_token.line,
                "statements": body_payload["statements"],
                "return": body_payload["return"],
            }

        if head == "MainBody" and body == ("StmtList", "ReturnStmt"):
            return {"statements": values[0], "return": values[1]}
        if head == "MainBody" and body == ("ReturnStmt",):
            return {"statements": [], "return": values[0]}

        if head == "StmtList" and body == ("StmtList", "Stmt"):
            return [*values[0], values[1]]
        if head == "StmtList" and body == ("Stmt",):
            return [values[0]]
        if head == "Stmt":
            return values[0]

        if head == "Decl":
            int_token = values[0]
            id_token = values[1]
            identifier = ASTNode(
                "Identifier",
                value=id_token.lexeme,
                line=id_token.line,
                column=id_token.column,
            )
            return ASTNode(
                "Declaration",
                value="int",
                children=[identifier] if body == ("int", "id", ";") else [identifier, values[3]],
                line=int_token.line,
                column=int_token.column,
            )

        if head == "Assign":
            id_token = values[0]
            identifier = ASTNode(
                "Identifier",
                value=id_token.lexeme,
                line=id_token.line,
                column=id_token.column,
            )
            return ASTNode(
                "Assignment",
                children=[identifier, values[2]],
                line=id_token.line,
                column=id_token.column,
            )

        if head == "InputRef" and body == ("cin",):
            token = values[0]
            return {"qualified": False, "line": token.line, "column": token.column}
        if head == "InputRef" and body == ("std", "::", "cin"):
            token = values[2]
            return {"qualified": True, "line": token.line, "column": token.column}
        if head == "InputList" and body == ("InputList", ">>", "id"):
            id_token = values[2]
            return [
                *values[0],
                ASTNode("Identifier", value=id_token.lexeme, line=id_token.line, column=id_token.column),
            ]
        if head == "InputList" and body == (">>", "id"):
            id_token = values[1]
            return [ASTNode("Identifier", value=id_token.lexeme, line=id_token.line, column=id_token.column)]
        if head == "InputStmt":
            stream_ref = values[0]
            return ASTNode(
                "Input",
                children=values[1],
                line=stream_ref["line"],
                column=stream_ref["column"],
                metadata={"qualified": stream_ref["qualified"]},
            )

        if head == "OutputRef" and body == ("cout",):
            token = values[0]
            return {"qualified": False, "line": token.line, "column": token.column}
        if head == "OutputRef" and body == ("std", "::", "cout"):
            token = values[2]
            return {"qualified": True, "line": token.line, "column": token.column}
        if head == "OutputList" and body == ("OutputList", "<<", "OutputItem"):
            return [*values[0], values[2]]
        if head == "OutputList" and body == ("<<", "OutputItem"):
            return [values[1]]
        if head == "OutputItem" and body == ("Expr",):
            return values[0]
        if head == "OutputItem" and body == ("string",):
            token = values[0]
            return ASTNode(
                "String",
                value=self._decode_string_literal(token.lexeme),
                line=token.line,
                column=token.column,
            )
        if head == "OutputItem" and body == ("EndlRef",):
            return values[0]
        if head == "EndlRef" and body == ("endl",):
            token = values[0]
            return ASTNode(
                "Endl",
                line=token.line,
                column=token.column,
                metadata={"qualified": False},
            )
        if head == "EndlRef" and body == ("std", "::", "endl"):
            token = values[2]
            return ASTNode(
                "Endl",
                line=token.line,
                column=token.column,
                metadata={"qualified": True},
            )
        if head == "OutputStmt":
            stream_ref = values[0]
            return ASTNode(
                "Output",
                children=values[1],
                line=stream_ref["line"],
                column=stream_ref["column"],
                metadata={"qualified": stream_ref["qualified"]},
            )

        if head == "Expr" and body == ("Expr", "+", "Term"):
            return ASTNode(
                "BinaryOp",
                value="+",
                children=[values[0], values[2]],
                line=values[0].line,
                column=values[0].column,
            )
        if head == "Expr" and body == ("Term",):
            return values[0]

        if head == "Term" and body == ("Term", "*", "Factor"):
            return ASTNode(
                "BinaryOp",
                value="*",
                children=[values[0], values[2]],
                line=values[0].line,
                column=values[0].column,
            )
        if head == "Term" and body == ("Factor",):
            return values[0]

        if head == "Factor" and body == ("id",):
            token = values[0]
            return ASTNode("Identifier", value=token.lexeme, line=token.line, column=token.column)
        if head == "Factor" and body == ("num",):
            token = values[0]
            return ASTNode("Number", value=int(token.lexeme), line=token.line, column=token.column)
        if head == "Factor" and body == ("(", "Expr", ")"):
            return values[1]

        if head == "SwitchStmt":
            switch_token = values[0]
            id_token = values[2]
            cases = ASTNode("Cases", children=values[5])
            children = [
                ASTNode("Identifier", value=id_token.lexeme, line=id_token.line, column=id_token.column),
                cases,
            ]
            if values[6] is not None:
                children.append(values[6])
            return ASTNode(
                "Switch",
                children=children,
                line=switch_token.line,
                column=switch_token.column,
            )

        if head == "CaseList" and body == ("CaseList", "Case"):
            return [*values[0], values[1]]
        if head == "CaseList" and body == ("Case",):
            return [values[0]]

        if head == "Case":
            case_token = values[0]
            number_token = values[1]
            return ASTNode(
                "Case",
                value=int(number_token.lexeme),
                children=values[3],
                line=case_token.line,
                column=case_token.column,
            )

        if head == "OptDefault" and body == ("DefaultCase",):
            return values[0]
        if head == "OptDefault" and not body:
            return None

        if head == "DefaultCase":
            default_token = values[0]
            return ASTNode(
                "Default",
                children=values[2],
                line=default_token.line,
                column=default_token.column,
            )

        if head == "BreakStmt":
            break_token = values[0]
            return ASTNode("Break", line=break_token.line, column=break_token.column)

        if head == "ReturnStmt":
            number_token = values[1]
            return int(number_token.lexeme)

        raise ValueError(f"No semantic action defined for production {head} -> {' '.join(body) if body else 'epsilon'}")

    def _decode_string_literal(self, lexeme: str) -> str:
        content = lexeme[1:-1]
        return bytes(content, "utf-8").decode("unicode_escape")
