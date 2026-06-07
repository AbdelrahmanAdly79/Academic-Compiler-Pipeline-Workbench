from __future__ import annotations

import copy
import logging
import re

from models import TACInstruction


LOGGER = logging.getLogger(__name__)

_TEMP_RE = re.compile(r"^t\d+$")


class Optimizer:
    def optimize(self, instructions: list[TACInstruction]) -> tuple[list[TACInstruction], list[str]]:
        LOGGER.info("Starting optimization passes")
        notes: list[str] = []
        current = copy.deepcopy(instructions)
        current = self._constant_fold(current, notes)
        current = self._eliminate_unreachable(current, notes)
        current = self._eliminate_dead_temporaries(current, notes)
        LOGGER.info("Optimization completed with %s note(s)", len(notes))
        return current, notes

    def _constant_fold(
        self,
        instructions: list[TACInstruction],
        notes: list[str],
    ) -> list[TACInstruction]:
        env: dict[str, str | None] = {}
        optimized: list[TACInstruction] = []

        for instruction in instructions:
            if instruction.op in {"label", "goto"}:
                env.clear()
                optimized.append(copy.deepcopy(instruction))
                continue

            if instruction.op == "if_eq_goto":
                arg1 = self._resolve(instruction.arg1, env)
                arg2 = self._resolve(instruction.arg2, env)
                optimized.append(
                    TACInstruction(
                        op="if_eq_goto",
                        arg1=arg1,
                        arg2=arg2,
                        label=instruction.label,
                    )
                )
                env.clear()
                continue

            if instruction.op == "input":
                optimized.append(copy.deepcopy(instruction))
                if instruction.result is not None:
                    env[instruction.result] = None
                continue

            if instruction.op == "print":
                value = self._resolve(instruction.arg1, env)
                optimized.append(TACInstruction(op="print", arg1=value))
                if value != instruction.arg1:
                    notes.append("Propagated constant into output statement.")
                continue

            if instruction.op == "assign":
                value = self._resolve(instruction.arg1, env)
                optimized.append(
                    TACInstruction(op="assign", result=instruction.result, arg1=value)
                )
                env[instruction.result] = value if self._is_number(value) else None
                if value != instruction.arg1:
                    notes.append(f"Propagated constant into assignment of {instruction.result}.")
                continue

            if instruction.op in {"+", "*"}:
                left = self._resolve(instruction.arg1, env)
                right = self._resolve(instruction.arg2, env)
                if self._is_number(left) and self._is_number(right):
                    folded = str(self._evaluate(instruction.op, int(left), int(right)))
                    optimized.append(
                        TACInstruction(op="assign", result=instruction.result, arg1=folded)
                    )
                    env[instruction.result] = folded
                    notes.append(
                        f"Constant folded {instruction.result} = {left} {instruction.op} {right}."
                    )
                else:
                    optimized.append(
                        TACInstruction(
                            op=instruction.op,
                            result=instruction.result,
                            arg1=left,
                            arg2=right,
                        )
                    )
                    env[instruction.result] = None
                continue

            optimized.append(copy.deepcopy(instruction))

        return optimized

    def _eliminate_unreachable(
        self,
        instructions: list[TACInstruction],
        notes: list[str],
    ) -> list[TACInstruction]:
        optimized: list[TACInstruction] = []
        unreachable = False
        for instruction in instructions:
            if instruction.op == "label":
                unreachable = False
                optimized.append(copy.deepcopy(instruction))
                continue
            if unreachable:
                notes.append(f"Removed unreachable instruction: {instruction.to_text()}")
                continue
            optimized.append(copy.deepcopy(instruction))
            if instruction.op == "goto":
                unreachable = True
        return optimized

    def _eliminate_dead_temporaries(
        self,
        instructions: list[TACInstruction],
        notes: list[str],
    ) -> list[TACInstruction]:
        live: set[str] = set()
        kept: list[TACInstruction] = []

        for instruction in reversed(instructions):
            defines = instruction.defines()
            uses = instruction.uses()

            if defines and all(_TEMP_RE.match(name) for name in defines) and not (defines & live):
                notes.append(f"Removed dead temporary assignment: {instruction.to_text()}")
                live.update(uses)
                continue

            kept.append(copy.deepcopy(instruction))
            live.difference_update(defines)
            live.update(uses)

        kept.reverse()
        return kept

    def _resolve(self, operand: str | None, env: dict[str, str | None]) -> str | None:
        if operand is None:
            return None
        if operand in env and env[operand] is not None:
            return env[operand]
        return operand

    def _evaluate(self, op: str, left: int, right: int) -> int:
        if op == "+":
            return left + right
        if op == "*":
            return left * right
        raise ValueError(f"Unsupported operation {op}")

    def _is_number(self, value: str | None) -> bool:
        return value is not None and value.lstrip("-").isdigit()
