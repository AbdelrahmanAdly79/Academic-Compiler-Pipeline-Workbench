from __future__ import annotations

import logging

from models import ASTNode, TACInstruction


LOGGER = logging.getLogger(__name__)


class TACGenerator:
    def __init__(self) -> None:
        self.temp_counter = 0
        self.label_counter = 0
        self.instructions: list[TACInstruction] = []

    def generate(self, ast: ASTNode | None) -> list[TACInstruction]:
        LOGGER.info("Starting TAC generation")
        self.temp_counter = 0
        self.label_counter = 0
        self.instructions = []
        if ast is None:
            return []
        for statement in ast.children:
            self._generate_statement(statement, break_target=None)
        LOGGER.info("Generated %s TAC instruction(s)", len(self.instructions))
        return self.instructions

    def _generate_statement(self, node: ASTNode, break_target: str | None) -> None:
        if node.type == "Declaration":
            self.instructions.append(
                TACInstruction(op="decl", result=node.children[0].value, arg1=node.value)
            )
            if len(node.children) > 1:
                value = self._generate_expression(node.children[1])
                self.instructions.append(
                    TACInstruction(op="assign", result=node.children[0].value, arg1=value)
                )
            return

        if node.type == "Assignment":
            destination = node.children[0].value
            value = self._generate_expression(node.children[1])
            self.instructions.append(TACInstruction(op="assign", result=destination, arg1=value))
            return

        if node.type == "Input":
            for identifier in node.children:
                self.instructions.append(TACInstruction(op="input", result=identifier.value))
            return

        if node.type == "Output":
            for item in node.children:
                if item.type == "String":
                    self.instructions.append(TACInstruction(op="print_str", arg1=str(item.value)))
                    continue
                if item.type == "Endl":
                    self.instructions.append(TACInstruction(op="print_nl"))
                    continue
                value = self._generate_expression(item)
                self.instructions.append(TACInstruction(op="print", arg1=value))
            return

        if node.type == "Switch":
            self._generate_switch(node)
            return

        if node.type == "Break":
            if break_target is None:
                self.instructions.append(
                    TACInstruction(op="nop", comment="invalid break ignored during TAC generation")
                )
            else:
                self.instructions.append(TACInstruction(op="goto", label=break_target))
            return

    def _generate_expression(self, node: ASTNode) -> str:
        if node.type == "Identifier":
            return str(node.value)
        if node.type == "Number":
            return str(node.value)
        if node.type == "BinaryOp":
            left = self._generate_expression(node.children[0])
            right = self._generate_expression(node.children[1])
            temp = self._new_temp()
            self.instructions.append(
                TACInstruction(op=node.value, result=temp, arg1=left, arg2=right)
            )
            return temp
        raise ValueError(f"Unsupported expression node {node.type}")

    def _generate_switch(self, node: ASTNode) -> None:
        switch_identifier = node.children[0].value
        cases_container = next(child for child in node.children if child.type == "Cases")
        default_node = next((child for child in node.children if child.type == "Default"), None)
        end_label = self._new_label("Lend")
        case_labels = [self._new_label("Lcase") for _ in cases_container.children]
        default_label = self._new_label("Ldefault") if default_node is not None else end_label

        for case_node, case_label in zip(cases_container.children, case_labels):
            self.instructions.append(
                TACInstruction(
                    op="if_eq_goto",
                    arg1=switch_identifier,
                    arg2=str(case_node.value),
                    label=case_label,
                )
            )
        self.instructions.append(TACInstruction(op="goto", label=default_label))

        for case_node, case_label in zip(cases_container.children, case_labels):
            self.instructions.append(TACInstruction(op="label", label=case_label))
            for statement in case_node.children:
                self._generate_statement(statement, break_target=end_label)

        if default_node is not None:
            self.instructions.append(TACInstruction(op="label", label=default_label))
            for statement in default_node.children:
                self._generate_statement(statement, break_target=end_label)

        self.instructions.append(TACInstruction(op="label", label=end_label))

    def _new_temp(self) -> str:
        self.temp_counter += 1
        return f"t{self.temp_counter}"

    def _new_label(self, prefix: str) -> str:
        self.label_counter += 1
        return f"{prefix}{self.label_counter}"


def render_instructions(instructions: list[TACInstruction]) -> str:
    if not instructions:
        return "<no code>"
    return "\n".join(instruction.to_text() for instruction in instructions)
