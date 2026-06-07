# ⚙️ Academic Mini Compiler Project (Python & PySide6)

This repository contains a full compiler compilation pipeline for a subset of C++ supporting variables, arithmetic expressions, `cin` / `cout` stream operations, and `switch` flow control. The system includes both a Command Line Interface (CLI) compiler and a modern desktop workbench interface built with **PySide6**.

---

## 📂 Project Structure

```text
system pograming project/
├── compiler_report (1).docx                     # Full technical academic report describing SLR table generation and semantic checks
├── System programming 12th project_Instructions.pdf # Assignment specification sheet
└── system-prog/                                 # Implementation directory
    ├── README.md                                # Detailed implementation README (modules & grammar)
    ├── main.py                                  # CLI and GUI application entrypoint
    ├── gui.py                                   # PySide6 graphical workbench with IDE-like tab views
    ├── lexer.py                                 # Tokenizer with line & column diagnostic trackers
    ├── grammar.py                               # SLR(1) Grammar, LR(0) states, Action/Goto matrix definitions
    ├── parser.py                                # SLR shift-reduce parser and Abstract Syntax Tree (AST) generator
    ├── semantic.py                              # Symbol table manager and type checkers
    ├── tac.py                                   # Three-Address Intermediate Code generator
    ├── optimizer.py                             # Optimization phase (constant folding, dead code elimination)
    ├── runtime.py                               # Minimal AST interpreter console runtime
    ├── pipeline.py                              # Core compiler orchestrator pipeline
    ├── models.py                                # Shared data models and classes
    ├── samples/                                 # C++ code templates (valid & error test examples)
    └── tests/                                   # Unit test suites
```

---

## ⚙️ Compilation Pipeline Modules

1. **Lexical Analysis (`lexer.py`)**: Tokenizes source text, tracking locations for error diagnostics.
2. **SLR Parsing & AST (`parser.py`, `grammar.py`)**: Executes table-driven SLR parsing via shift-reduce actions, building an Abstract Syntax Tree (AST) on successful reductions.
3. **Semantic Analysis (`semantic.py`)**: Construct symbol tables, handles scope bounds, checks types, and ensures variables are declared before use.
4. **Intermediate Code Generation (`tac.py`)**: Converts semantic ASTs into a linear list of **Three-Address Code (TAC)** instructions.
5. **Optimization (`optimizer.py`)**: Analyzes TAC to perform constant folding and eliminate unreachable (dead) instructions.
6. **GUI Workbench IDE (`gui.py`)**: Renders editor grids with custom syntax highlighting, log consoles, and visual compilation stages (Lexer tokens, Parser actions, AST logs, and Symbol tables).

---

## 🛠️ Technology Stack

* **Language**: Python 3.x
* **GUI library**: PySide6 (Qt for Python)
* **Testing framework**: unittest
* **Styling & Layout**: Qt stylesheets

---

## 🚀 Getting Started

Please navigate to the [system-prog README.md](file:///C:/Users/abdo2/OneDrive/Desktop/projects%20gam3a/system%20pograming%20project/system-prog/README.md) for detailed descriptions of grammar rules, CLI compiler commands, and test suites execution.

### Installation
Make sure Python 3.8+ is installed:
```bash
# Navigate to code folder
cd system-prog

# Install PySide6
pip install PySide6 pytest
```

### Running the Workbench GUI
```bash
python main.py
```

### Running CLI Compilation
```bash
python main.py --cli samples/valid_switch_case.txt
```
