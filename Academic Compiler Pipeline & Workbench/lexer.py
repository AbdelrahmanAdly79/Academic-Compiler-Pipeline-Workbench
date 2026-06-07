from __future__ import annotations

import logging

from models import Diagnostic, Token


LOGGER = logging.getLogger(__name__)


KEYWORDS = {
    "cin": ("CIN", "cin"),
    "cout": ("COUT", "cout"),
    "endl": ("ENDL", "endl"),
    "include": ("INCLUDE", "include"),
    "int": ("INT", "int"),
    "main": ("MAIN", "main"),
    "namespace": ("NAMESPACE", "namespace"),
    "return": ("RETURN", "return"),
    "std": ("STD", "std"),
    "switch": ("SWITCH", "switch"),
    "case": ("CASE", "case"),
    "break": ("BREAK", "break"),
    "default": ("DEFAULT", "default"),
    "using": ("USING", "using"),
}

MULTI_CHAR_SYMBOLS = {
    "::": ("SCOPE", "::"),
    "<<": ("LSHIFT", "<<"),
    ">>": ("RSHIFT", ">>"),
}

SYMBOLS = {
    "#": ("HASH", "#"),
    "<": ("LT", "<"),
    ">": ("GT", ">"),
    "+": ("PLUS", "+"),
    "*": ("STAR", "*"),
    "=": ("ASSIGN", "="),
    ";": ("SEMI", ";"),
    ":": ("COLON", ":"),
    "{": ("LBRACE", "{"),
    "}": ("RBRACE", "}"),
    "(": ("LPAREN", "("),
    ")": ("RPAREN", ")"),
}


class Lexer:
    def tokenize(self, source: str) -> tuple[list[Token], list[Diagnostic]]:
        LOGGER.info("Starting lexical analysis")
        tokens: list[Token] = []
        diagnostics: list[Diagnostic] = []
        index = 0
        line = 1
        column = 1

        while index < len(source):
            current = source[index]

            if current in {" ", "\t", "\r"}:
                index += 1
                column += 1
                continue

            if current == "\n":
                index += 1
                line += 1
                column = 1
                continue

            if current == "/" and index + 1 < len(source):
                next_char = source[index + 1]
                if next_char == "/":
                    index += 2
                    column += 2
                    while index < len(source) and source[index] != "\n":
                        index += 1
                        column += 1
                    continue
                if next_char == "*":
                    start_line = line
                    start_column = column
                    index += 2
                    column += 2
                    while index + 1 < len(source) and source[index : index + 2] != "*/":
                        if source[index] == "\n":
                            line += 1
                            column = 1
                            index += 1
                            continue
                        index += 1
                        column += 1
                    if index + 1 >= len(source):
                        diagnostics.append(
                            Diagnostic(
                                phase="lexer",
                                level="error",
                                message="Unterminated block comment.",
                                line=start_line,
                                column=start_column,
                            )
                        )
                        break
                    index += 2
                    column += 2
                    continue

            matched_symbol = None
            for lexeme, token_data in MULTI_CHAR_SYMBOLS.items():
                if source.startswith(lexeme, index):
                    matched_symbol = (lexeme, token_data)
                    break
            if matched_symbol is not None:
                lexeme, (token_type, symbol) = matched_symbol
                tokens.append(Token(token_type, symbol, lexeme, line, column))
                index += len(lexeme)
                column += len(lexeme)
                continue

            if current == '"':
                start = index
                start_column = column
                index += 1
                column += 1
                escaped = False
                terminated = False
                while index < len(source):
                    char = source[index]
                    if char == "\n":
                        diagnostics.append(
                            Diagnostic(
                                phase="lexer",
                                level="error",
                                message="Unterminated string literal.",
                                line=line,
                                column=start_column,
                            )
                        )
                        terminated = True
                        break
                    index += 1
                    column += 1
                    if escaped:
                        escaped = False
                        continue
                    if char == "\\":
                        escaped = True
                        continue
                    if char == '"':
                        terminated = True
                        break
                if not terminated:
                    diagnostics.append(
                        Diagnostic(
                            phase="lexer",
                            level="error",
                            message="Unterminated string literal.",
                            line=line,
                            column=start_column,
                        )
                    )
                    break
                if source[index - 1] != '"':
                    break
                lexeme = source[start:index]
                tokens.append(Token("STRING", "string", lexeme, line, start_column))
                continue

            if current.isalpha() or current == "_":
                start = index
                start_column = column
                while index < len(source) and (source[index].isalnum() or source[index] == "_"):
                    index += 1
                    column += 1
                lexeme = source[start:index]
                token_type, symbol = KEYWORDS.get(lexeme, ("ID", "id"))
                tokens.append(Token(token_type, symbol, lexeme, line, start_column))
                continue

            if current.isdigit():
                start = index
                start_column = column
                while index < len(source) and source[index].isdigit():
                    index += 1
                    column += 1
                lexeme = source[start:index]
                tokens.append(Token("NUM", "num", lexeme, line, start_column))
                continue

            if current in SYMBOLS:
                token_type, symbol = SYMBOLS[current]
                tokens.append(Token(token_type, symbol, current, line, column))
                index += 1
                column += 1
                continue

            diagnostics.append(
                Diagnostic(
                    phase="lexer",
                    level="error",
                    message=f"Unexpected character {current!r}.",
                    line=line,
                    column=column,
                )
            )
            LOGGER.warning("Unexpected character %r at line %s column %s", current, line, column)
            index += 1
            column += 1

        tokens.append(Token("EOF", "$", "$", line, column))
        LOGGER.info("Lexical analysis completed with %s token(s)", len(tokens))
        return tokens, diagnostics
