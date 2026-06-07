# Academic Mini Compiler Project

This project is a full mini-compiler pipeline for a small C++-style subset with:

- optional `#include <...>`
- optional `using namespace std;`
- `int main() { ... return <num>; }`
- integer declarations and assignments
- arithmetic expressions with `+`, `*`, and parentheses
- `cin` / `cout` with `std::` qualification rules
- `switch / case / break / default`

The compiler implements:

1. lexical analysis
2. table-driven SLR parsing
3. AST generation during reductions
4. semantic analysis
5. three-address code generation
6. optimization

The desktop workbench is implemented with `PySide6` and provides a modern multi-tab interface over the same backend used by CLI mode and tests.

## Architecture

The project is split into small modules with clear responsibilities:

- `lexer.py`: tokenization with line and column tracking
- `grammar.py`: grammar definition, FIRST/FOLLOW, LR(0) states, ACTION/GOTO tables
- `parser.py`: shift/reduce engine and reduction-driven AST construction
- `semantic.py`: symbol table construction and semantic checks
- `tac.py`: three-address code generation
- `optimizer.py`: constant folding and dead code elimination
- `runtime.py`: minimal AST-based execution for the GUI console
- `pipeline.py`: orchestration of the full compiler pipeline
- `gui.py`: modern PySide6 workbench with a custom editor, syntax highlighting, and phase views
- `main.py`: CLI and GUI entrypoint
- `models.py`: shared dataclasses used by every phase

## Grammar

The parser is generated from the grammar in `grammar.py`. The supported syntax is intentionally limited to a C++-style wrapper plus declarations, assignments, arithmetic expressions, `cin` / `cout`, and `switch` statements. Loops and `if` statements are intentionally excluded.

Core nonterminals:

- `Program`
- `OptIncludeList`, `IncludeList`, `Include`
- `OptUsingDirective`, `UsingDirective`
- `MainFunction`, `MainBody`, `ReturnStmt`
- `StmtList`
- `Stmt`
- `Decl`
- `Assign`
- `InputStmt`, `OutputStmt`
- `Expr`, `Term`, `Factor`
- `SwitchStmt`
- `CaseList`, `Case`
- `OptDefault`, `DefaultCase`
- `BreakStmt`

The parser is not recursive descent. It uses:

- grammar augmentation
- canonical LR(0) items
- `closure` and `goto`
- canonical collection construction
- SLR ACTION and GOTO tables
- a shift/reduce engine

## Running

CLI mode:

```bash
python3 main.py --cli samples/valid_switch_case.txt
```

Tests:

```bash
python3 -m unittest discover -s tests -v
```

GUI mode:

```bash
python3 main.py
```

The primary GUI stack is PySide6. The current workspace has PySide6 available and the workbench has been smoke-tested in offscreen mode.
The Source Code tab also includes a minimal console pane beside diagnostics. Compile a valid program, then supply `cin` values through the console input box when execution pauses for input.

## Sample Programs

- `samples/valid_switch_case.txt`
- `samples/cin_cout_switch.txt`
- `samples/invalid_syntax.txt`
- `samples/semantic_errors.txt`

Example:

```cpp
using namespace std;

int main() {
    int x = 2 + (3 * 4);
    int y = 0;

    cout << "x = " << x << endl;

    switch (x) {
    case 1:
        y = x + 1;
        break;
    default:
        y = 0;
    }

    cout << "y = " << y << endl;
    return 0;
}
```

Without `using namespace std;`, write `std::cin`, `std::cout`, and `std::endl` explicitly.

## Output Artifacts

Each compile run can produce:

- token stream
- LR parse steps
- AST as JSON
- symbol table
- semantic diagnostics
- TAC
- optimized TAC

## Logging

The entrypoint writes logs to `compiler.log` and also mirrors them to stdout.
