from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

from PySide6.QtCore import QRect, QSize, Qt, QRegularExpression
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import ASTNode, CompilationArtifacts, Diagnostic, ParseStep
from pipeline import CompilerPipeline
from runtime import RuntimeExecutor
from tac import render_instructions


LOGGER = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT_DIR / "samples"


class MiniLangHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#7dd3fc"))
        keyword_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "cin",
            "cout",
            "endl",
            "include",
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
        ]
        self._add_words(keywords, keyword_format)

        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#fbbf24"))
        self.rules.append((QRegularExpression(r"\b\d+\b"), number_format))

        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#86efac"))
        self.rules.append((QRegularExpression(r'"([^"\\]|\\.)*"'), string_format))

        operator_format = QTextCharFormat()
        operator_format.setForeground(QColor("#c084fc"))
        self.rules.append((QRegularExpression(r"::|<<|>>|[#<>+*=;:{}()]"), operator_format))

        id_format = QTextCharFormat()
        id_format.setForeground(QColor("#e2e8f0"))
        self.rules.append((QRegularExpression(r"\b[A-Za-z_][A-Za-z0-9_]*\b"), id_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#64748b"))
        comment_format.setFontItalic(True)
        self.rules.append((QRegularExpression(r"//[^\n]*"), comment_format))
        self.rules.append((QRegularExpression(r"/\*.*\*/"), comment_format))

    def _add_words(self, words: list[str], fmt: QTextCharFormat) -> None:
        for word in words:
            self.rules.append((QRegularExpression(fr"\b{word}\b"), fmt))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.code_editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.code_editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        self.code_editor.line_number_area_paint_event(event)


class CodeEditor(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 20 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        geometry = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(geometry.left(), geometry.top(), self.line_number_area_width(), geometry.height())
        )

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#0b1220"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#64748b"))
                painter.drawText(
                    0,
                    top,
                    self.line_number_area.width() - 8,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        if self.isReadOnly():
            self.setExtraSelections([])
            return
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#172036"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])


class CompilerWorkbench(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.pipeline = CompilerPipeline()
        self.runtime = RuntimeExecutor()
        self.current_artifacts: CompilationArtifacts | None = None
        self.current_step_index = -1
        self.console_inputs: list[str] = []

        self.setWindowTitle("Compiler Studio")
        self.resize(1680, 1020)
        self.setMinimumSize(1320, 860)
        self.setStatusBar(QStatusBar(self))

        self.ui_font = QFont("Segoe UI", 10)
        self.code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.code_font.setPointSize(11)

        self._apply_theme()
        self._build_ui()
        self._load_sample_list()
        self.statusBar().showMessage("Ready")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #0a0f1e;
                color: #dbe4ff;
                font-family: "Segoe UI", "SF Pro Display", sans-serif;
                font-size: 13px;
            }
            QMainWindow {
                background: #070b16;
            }
            QFrame#Hero {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0f172a, stop:0.5 #111c38, stop:1 #0b1326);
                border: 1px solid #20314f;
                border-radius: 18px;
            }
            QLabel#HeroTitle {
                font-size: 28px;
                font-weight: 700;
                color: #eff6ff;
            }
            QLabel#HeroSubtitle {
                color: #94a3b8;
                font-size: 13px;
            }
            QFrame#Badge {
                background: #0d2348;
                border: 1px solid #2563eb;
                border-radius: 14px;
            }
            QLabel#BadgeText {
                color: #93c5fd;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QGroupBox {
                border: 1px solid #1e293b;
                border-radius: 16px;
                margin-top: 18px;
                padding-top: 12px;
                background: #0b1220;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 6px 0 6px;
                color: #e2e8f0;
            }
            QTabWidget::pane {
                border: 1px solid #1e293b;
                border-radius: 18px;
                top: -1px;
                background: #08111f;
            }
            QTabBar::tab {
                background: #0f172a;
                color: #94a3b8;
                padding: 10px 18px;
                margin-right: 4px;
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
            QTabBar::tab:selected {
                background: #132445;
                color: #f8fafc;
            }
            QPlainTextEdit, QTreeWidget, QTableWidget, QComboBox {
                background: #0f172a;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                border-radius: 12px;
                selection-background-color: #1d4ed8;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background: #13213d;
                color: #e2e8f0;
                border: none;
                border-right: 1px solid #20314f;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton {
                background: #152444;
                color: #eff6ff;
                border: 1px solid #27406b;
                border-radius: 12px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #1d3461;
            }
            QPushButton#PrimaryButton {
                background: #1d4ed8;
                border: 1px solid #3b82f6;
            }
            QPushButton#PrimaryButton:hover {
                background: #2563eb;
            }
            QLabel#SectionNote {
                color: #94a3b8;
            }
            QStatusBar {
                background: #071120;
                color: #93c5fd;
                border-top: 1px solid #1e293b;
            }
            QScrollBar:vertical {
                background: #0b1220;
                width: 12px;
                margin: 8px 0 8px 0;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #243554;
                min-height: 28px;
                border-radius: 6px;
            }
            QScrollBar:horizontal {
                background: #0b1220;
                height: 12px;
                margin: 0 8px 0 8px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #243554;
                min-width: 28px;
                border-radius: 6px;
            }
            """
        )

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("Hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(22, 18, 22, 18)
        hero_layout.setSpacing(18)

        title_column = QVBoxLayout()
        title = QLabel("Compiler Studio")
        title.setObjectName("HeroTitle")
        subtitle = QLabel(
            "SLR parser generation, AST construction, semantic validation, TAC emission, and optimization in one workbench."
        )
        subtitle.setObjectName("HeroSubtitle")
        subtitle.setWordWrap(True)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        hero_layout.addLayout(title_column, stretch=1)

        badge = QFrame()
        badge.setObjectName("Badge")
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(14, 10, 14, 10)
        badge_title = QLabel("PIPELINE")
        badge_title.setObjectName("BadgeText")
        badge_value = QLabel("Lexer → SLR → AST → Semantic → TAC → Optimize")
        badge_value.setObjectName("HeroSubtitle")
        badge_value.setWordWrap(True)
        badge_layout.addWidget(badge_title)
        badge_layout.addWidget(badge_value)
        hero_layout.addWidget(badge, stretch=0)
        root.addWidget(hero)

        toolbar_group = QGroupBox("Workspace")
        toolbar_layout = QGridLayout(toolbar_group)
        toolbar_layout.setContentsMargins(16, 22, 16, 16)
        toolbar_layout.setHorizontalSpacing(12)
        toolbar_layout.setVerticalSpacing(10)

        sample_label = QLabel("Sample Program")
        self.sample_combo = QComboBox()
        self.sample_combo.setMinimumWidth(280)

        load_sample_button = QPushButton("Load Sample")
        load_sample_button.clicked.connect(self.load_selected_sample)

        open_button = QPushButton("Open File")
        open_button.clicked.connect(self.open_source_file)

        save_button = QPushButton("Save Source")
        save_button.clicked.connect(self.save_source_file)

        self.compile_button = QPushButton("Compile / Run")
        self.compile_button.setObjectName("PrimaryButton")
        self.compile_button.clicked.connect(self.run_compiler)

        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear_workspace)

        note = QLabel("Use Ctrl+Enter to compile and run the current editor contents.")
        note.setObjectName("SectionNote")

        toolbar_layout.addWidget(sample_label, 0, 0)
        toolbar_layout.addWidget(self.sample_combo, 0, 1)
        toolbar_layout.addWidget(load_sample_button, 0, 2)
        toolbar_layout.addWidget(open_button, 0, 3)
        toolbar_layout.addWidget(save_button, 0, 4)
        toolbar_layout.addWidget(self.compile_button, 0, 5)
        toolbar_layout.addWidget(clear_button, 0, 6)
        toolbar_layout.addWidget(note, 1, 0, 1, 7)
        root.addWidget(toolbar_group)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self._build_source_tab()
        self._build_tokens_tab()
        self._build_lr_tab()
        self._build_ast_tab()
        self._build_semantic_tab()
        self._build_tac_tab()
        self._build_optimization_tab()

        self.source_editor.setFocus()

    def _build_source_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        editor_group = QGroupBox("Source Code")
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setContentsMargins(14, 22, 14, 14)
        self.source_editor = CodeEditor()
        self.source_editor.setFont(self.code_font)
        self.source_editor.setPlaceholderText("Write your source program here...")
        self.source_editor.setTabStopDistance(32)
        MiniLangHighlighter(self.source_editor.document())
        editor_layout.addWidget(self.source_editor)
        layout.addWidget(editor_group, stretch=3)

        bottom_split = QSplitter(Qt.Orientation.Horizontal)

        diag_group = QGroupBox("Diagnostics")
        diag_layout = QVBoxLayout(diag_group)
        diag_layout.setContentsMargins(14, 22, 14, 14)
        self.diagnostics_text = self._make_viewer()
        diag_layout.addWidget(self.diagnostics_text)
        bottom_split.addWidget(diag_group)

        console_group = QGroupBox("Console")
        console_layout = QVBoxLayout(console_group)
        console_layout.setContentsMargins(14, 22, 14, 14)
        console_layout.setSpacing(10)
        self.console_view = self._make_viewer()
        self.console_view.setPlaceholderText("Program output appears here...")
        console_layout.addWidget(self.console_view, stretch=1)

        console_input_row = QHBoxLayout()
        self.console_input = QLineEdit()
        self.console_input.setPlaceholderText("Enter next cin value(s) and press Send Input")
        self.console_input.returnPressed.connect(self.submit_console_input)
        self.send_input_button = QPushButton("Send Input")
        self.send_input_button.clicked.connect(self.submit_console_input)
        console_input_row.addWidget(self.console_input, stretch=1)
        console_input_row.addWidget(self.send_input_button)
        console_layout.addLayout(console_input_row)
        bottom_split.addWidget(console_group)
        bottom_split.setSizes([680, 680])

        layout.addWidget(bottom_split, stretch=2)

        self.tabs.addTab(tab, "Source Code")

    def _build_tokens_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        group = QGroupBox("Token Stream")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(14, 22, 14, 14)
        self.tokens_table = self._make_table()
        group_layout.addWidget(self.tokens_table)
        layout.addWidget(group)
        self.tabs.addTab(tab, "Tokens")

    def _build_lr_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        lr_subtabs = QTabWidget()

        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        table_layout.setContentsMargins(10, 10, 10, 10)
        table_group = QGroupBox("ACTION / GOTO Table")
        table_group_layout = QVBoxLayout(table_group)
        table_group_layout.setContentsMargins(14, 22, 14, 14)
        self.parse_table_widget = self._make_table()
        table_group_layout.addWidget(self.parse_table_widget)
        table_layout.addWidget(table_group, stretch=1)
        lr_subtabs.addTab(table_tab, "ACTION / GOTO Table")

        trace_tab = QWidget()
        trace_tab_layout = QVBoxLayout(trace_tab)
        trace_tab_layout.setContentsMargins(10, 10, 10, 10)
        trace_tab_layout.setSpacing(10)

        controls_group = QGroupBox("Parse Trace Controls")
        controls_layout = QHBoxLayout(controls_group)
        controls_layout.setContentsMargins(14, 22, 14, 14)
        self.prev_step_button = QPushButton("Previous Step")
        self.next_step_button = QPushButton("Next Step")
        self.prev_step_button.clicked.connect(lambda: self.move_parse_step(-1))
        self.next_step_button.clicked.connect(lambda: self.move_parse_step(1))
        self.step_label = QLabel("No parse trace loaded")
        self.step_label.setObjectName("SectionNote")
        controls_layout.addWidget(self.prev_step_button)
        controls_layout.addWidget(self.next_step_button)
        controls_layout.addWidget(self.step_label, stretch=1)
        trace_tab_layout.addWidget(controls_group)

        trace_group = QGroupBox("Shift / Reduce Trace")
        trace_layout = QVBoxLayout(trace_group)
        trace_layout.setContentsMargins(14, 22, 14, 14)
        self.parse_steps_table = self._make_table()
        self.parse_steps_table.itemSelectionChanged.connect(self.on_parse_step_selected)
        trace_layout.addWidget(self.parse_steps_table)
        trace_tab_layout.addWidget(trace_group, stretch=1)
        lr_subtabs.addTab(trace_tab, "Shift / Reduce Trace")

        states_tab = QWidget()
        states_layout = QVBoxLayout(states_tab)
        states_layout.setContentsMargins(10, 10, 10, 10)
        states_group = QGroupBox("Canonical LR(0) Item Sets")
        states_group_layout = QVBoxLayout(states_group)
        states_group_layout.setContentsMargins(14, 22, 14, 14)
        self.states_view = self._make_viewer()
        states_group_layout.addWidget(self.states_view)
        states_layout.addWidget(states_group, stretch=1)
        lr_subtabs.addTab(states_tab, "Canonical LR(0) Item Sets")

        layout.addWidget(lr_subtabs, stretch=1)
        self.tabs.addTab(tab, "LR Parsing")

    def _build_ast_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal)
        tree_group = QGroupBox("AST Tree")
        tree_layout = QVBoxLayout(tree_group)
        tree_layout.setContentsMargins(14, 22, 14, 14)
        self.ast_tree = QTreeWidget()
        self.ast_tree.setHeaderHidden(True)
        tree_layout.addWidget(self.ast_tree)
        split.addWidget(tree_group)

        json_group = QGroupBox("AST JSON")
        json_layout = QVBoxLayout(json_group)
        json_layout.setContentsMargins(14, 22, 14, 14)
        self.ast_json_view = self._make_viewer()
        json_layout.addWidget(self.ast_json_view)
        split.addWidget(json_group)
        split.setSizes([520, 880])
        layout.addWidget(split)

        self.tabs.addTab(tab, "AST")

    def _build_semantic_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        symbols_group = QGroupBox("Symbol Table")
        symbols_layout = QVBoxLayout(symbols_group)
        symbols_layout.setContentsMargins(14, 22, 14, 14)
        self.symbol_table_widget = self._make_table()
        symbols_layout.addWidget(self.symbol_table_widget)
        layout.addWidget(symbols_group, stretch=1)

        semantic_group = QGroupBox("Semantic Diagnostics")
        semantic_layout = QVBoxLayout(semantic_group)
        semantic_layout.setContentsMargins(14, 22, 14, 14)
        self.semantic_view = self._make_viewer()
        semantic_layout.addWidget(self.semantic_view)
        layout.addWidget(semantic_group, stretch=1)

        self.tabs.addTab(tab, "Semantic Analysis")

    def _build_tac_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        group = QGroupBox("Three Address Code")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(14, 22, 14, 14)
        self.tac_view = self._make_viewer()
        group_layout.addWidget(self.tac_view)
        layout.addWidget(group)
        self.tabs.addTab(tab, "TAC")

    def _build_optimization_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal)
        before_group = QGroupBox("Before Optimization")
        before_layout = QVBoxLayout(before_group)
        before_layout.setContentsMargins(14, 22, 14, 14)
        self.optim_before_view = self._make_viewer()
        before_layout.addWidget(self.optim_before_view)
        split.addWidget(before_group)

        after_group = QGroupBox("After Optimization")
        after_layout = QVBoxLayout(after_group)
        after_layout.setContentsMargins(14, 22, 14, 14)
        self.optim_after_view = self._make_viewer()
        after_layout.addWidget(self.optim_after_view)
        split.addWidget(after_group)
        split.setSizes([680, 680])
        layout.addWidget(split, stretch=1)

        notes_group = QGroupBox("Optimization Notes")
        notes_layout = QVBoxLayout(notes_group)
        notes_layout.setContentsMargins(14, 22, 14, 14)
        self.optim_notes_view = self._make_viewer()
        notes_layout.addWidget(self.optim_notes_view)
        layout.addWidget(notes_group, stretch=0)

        self.tabs.addTab(tab, "Optimization")

    def _make_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setAlternatingRowColors(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setShowGrid(False)
        table.setFont(self.ui_font)
        return table

    def _make_viewer(self) -> QPlainTextEdit:
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setFont(self.code_font)
        viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return viewer

    def _load_sample_list(self) -> None:
        samples = sorted(path.name for path in SAMPLES_DIR.glob("*.txt"))
        self.sample_combo.clear()
        self.sample_combo.addItems(samples)
        if samples:
            self.load_selected_sample()

    def load_selected_sample(self) -> None:
        sample_name = self.sample_combo.currentText()
        if not sample_name:
            return
        sample_path = SAMPLES_DIR / sample_name
        if not sample_path.exists():
            QMessageBox.warning(self, "Sample Missing", f"Could not find sample file {sample_name}.")
            return
        self.source_editor.setPlainText(sample_path.read_text(encoding="utf-8"))
        self.statusBar().showMessage(f"Loaded sample {sample_name}")

    def open_source_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Source File",
            str(ROOT_DIR),
            "Source Files (*.txt *.src *.code);;All Files (*)",
        )
        if not file_path:
            return
        path = Path(file_path)
        self.source_editor.setPlainText(path.read_text(encoding="utf-8"))
        self.statusBar().showMessage(f"Opened {path.name}")

    def save_source_file(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Source File",
            str(ROOT_DIR / "program.txt"),
            "Source Files (*.txt *.src *.code);;All Files (*)",
        )
        if not file_path:
            return
        path = Path(file_path)
        path.write_text(self.source_editor.toPlainText(), encoding="utf-8")
        self.statusBar().showMessage(f"Saved {path.name}")

    def clear_workspace(self) -> None:
        self.source_editor.clear()
        self.current_artifacts = None
        self.current_step_index = -1
        self.console_inputs = []
        for viewer in [
            self.diagnostics_text,
            self.console_view,
            self.states_view,
            self.ast_json_view,
            self.semantic_view,
            self.tac_view,
            self.optim_before_view,
            self.optim_after_view,
            self.optim_notes_view,
        ]:
            viewer.clear()
        self.console_input.clear()
        for table in [
            self.tokens_table,
            self.parse_table_widget,
            self.parse_steps_table,
            self.symbol_table_widget,
        ]:
            table.clear()
            table.setRowCount(0)
            table.setColumnCount(0)
        self.ast_tree.clear()
        self.step_label.setText("No parse trace loaded")
        self.statusBar().showMessage("Workspace cleared")

    def run_compiler(self) -> None:
        source = self.source_editor.toPlainText()
        if not source.strip():
            QMessageBox.information(self, "Empty Source", "Enter source code or load a sample before compiling.")
            return

        LOGGER.info("Running compiler from PySide6 GUI")
        artifacts = self.pipeline.compile(source)
        self.current_artifacts = artifacts
        self.current_step_index = -1
        self.console_inputs = []
        self.populate_artifacts(artifacts)

        error_count = sum(1 for item in artifacts.diagnostics if item.level == "error")
        warning_count = sum(1 for item in artifacts.diagnostics if item.level == "warning")
        self.statusBar().showMessage(
            f"Compilation finished | {len(artifacts.tokens)} token(s) | {error_count} error(s) | {warning_count} warning(s)"
        )
        self._execute_current_program()

    def populate_artifacts(self, artifacts: CompilationArtifacts) -> None:
        self.populate_diagnostics(artifacts.diagnostics)
        self.populate_tokens(artifacts)
        self.populate_lr_views(artifacts)
        self.populate_ast(artifacts.ast)
        self.populate_semantic(artifacts)
        self.tac_view.setPlainText(render_instructions(artifacts.tac))
        self.optim_before_view.setPlainText(render_instructions(artifacts.tac))
        self.optim_after_view.setPlainText(render_instructions(artifacts.optimized_tac))
        optimizer_notes = "\n".join(
            diagnostic.format() for diagnostic in artifacts.diagnostics if diagnostic.phase == "optimizer"
        )
        self.optim_notes_view.setPlainText(optimizer_notes or "No optimization notes.")

    def populate_diagnostics(self, diagnostics: list[Diagnostic]) -> None:
        if not diagnostics:
            self.diagnostics_text.setPlainText("No diagnostics.")
            return
        self.diagnostics_text.setPlainText("\n".join(item.format() for item in diagnostics))

    def populate_console(self, text: str) -> None:
        self.console_view.setPlainText(text or "<no console output>")

    def submit_console_input(self) -> None:
        if self.current_artifacts is None or self._compilation_has_errors(self.current_artifacts):
            return
        pending = self.console_input.text().strip()
        if not pending:
            return
        self.console_inputs.extend(pending.split())
        self.console_input.clear()
        self._execute_current_program()

    def populate_tokens(self, artifacts: CompilationArtifacts) -> None:
        columns = ["#", "Type", "Symbol", "Lexeme", "Line", "Column"]
        rows = [
            [
                str(index),
                token.type,
                token.symbol,
                token.lexeme,
                str(token.line),
                str(token.column),
            ]
            for index, token in enumerate(artifacts.tokens, start=1)
        ]
        self.fill_table(self.tokens_table, columns, rows)

    def populate_lr_views(self, artifacts: CompilationArtifacts) -> None:
        parse_rows = self.pipeline.parser.grammar.format_parse_table_rows()
        if parse_rows:
            columns = list(parse_rows[0].keys())
            rows = [[row.get(column, "") for column in columns] for row in parse_rows]
            self.fill_table(self.parse_table_widget, columns, rows)
        else:
            self.fill_table(self.parse_table_widget, [], [])

        parse_table = self.pipeline.parser.grammar.parse_table
        state_lines: list[str] = []
        if parse_table.conflicts:
            state_lines.append("Conflicts detected:")
            for conflict in parse_table.conflicts:
                state_lines.append(f"- {conflict}")
            state_lines.append("")
        for index, state in enumerate(parse_table.states):
            state_lines.append(f"State {index}")
            for item in state:
                state_lines.append(f"  {item}")
            state_lines.append("")
        self.states_view.setPlainText("\n".join(state_lines).rstrip())

        step_columns = ["Step", "Stack", "Input", "Action"]
        step_rows = [
            [
                str(step.step),
                self.format_stack(step),
                " ".join(step.remaining_input),
                step.action,
            ]
            for step in artifacts.parse_steps
        ]
        self.fill_table(self.parse_steps_table, step_columns, step_rows)
        if artifacts.parse_steps:
            self.select_parse_step(0)
        else:
            self.step_label.setText("No parse trace loaded")

    def populate_ast(self, ast: ASTNode | None) -> None:
        self.ast_tree.clear()
        if ast is None:
            self.ast_json_view.setPlainText("<no AST available>")
            return
        self.ast_json_view.setPlainText(json.dumps(ast.to_dict(), indent=2))
        root_item = QTreeWidgetItem([self.ast_label(ast)])
        self.ast_tree.addTopLevelItem(root_item)
        self.insert_ast_children(root_item, ast)
        self.ast_tree.expandAll()

    def populate_semantic(self, artifacts: CompilationArtifacts) -> None:
        semantic = artifacts.semantic
        if semantic is None:
            self.fill_table(self.symbol_table_widget, [], [])
            self.semantic_view.setPlainText("<semantic analysis not executed>")
            return

        columns = ["Name", "Type", "Scope", "Line"]
        rows = [
            [entry.name, entry.type, entry.scope, "" if entry.line is None else str(entry.line)]
            for entry in semantic.symbols
        ]
        self.fill_table(self.symbol_table_widget, columns, rows)

        semantic_diagnostics = [item.format() for item in semantic.diagnostics]
        self.semantic_view.setPlainText("\n".join(semantic_diagnostics) or "No semantic diagnostics.")

    def fill_table(self, table: QTableWidget, columns: list[str], rows: list[list[str]]) -> None:
        table.clear()
        table.setColumnCount(len(columns))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(columns)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row_index, column_index, item)
        if columns:
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setStretchLastSection(True)

    def insert_ast_children(self, parent_item: QTreeWidgetItem, node: ASTNode) -> None:
        for child in node.children:
            child_item = QTreeWidgetItem([self.ast_label(child)])
            parent_item.addChild(child_item)
            self.insert_ast_children(child_item, child)

    def ast_label(self, node: ASTNode) -> str:
        return node.type if node.value is None else f"{node.type}: {node.value}"

    def move_parse_step(self, delta: int) -> None:
        if self.current_artifacts is None or not self.current_artifacts.parse_steps:
            return
        new_index = max(0, min(len(self.current_artifacts.parse_steps) - 1, self.current_step_index + delta))
        self.select_parse_step(new_index)

    def select_parse_step(self, index: int) -> None:
        if self.current_artifacts is None or not self.current_artifacts.parse_steps:
            return
        self.current_step_index = index
        self.parse_steps_table.blockSignals(True)
        self.parse_steps_table.selectRow(index)
        self.parse_steps_table.blockSignals(False)
        step = self.current_artifacts.parse_steps[index]
        self.step_label.setText(f"Step {step.step}/{len(self.current_artifacts.parse_steps)}: {step.action}")

    def on_parse_step_selected(self) -> None:
        if self.current_artifacts is None or not self.current_artifacts.parse_steps:
            return
        row = self.parse_steps_table.currentRow()
        if row < 0 or row >= len(self.current_artifacts.parse_steps):
            return
        self.current_step_index = row
        step = self.current_artifacts.parse_steps[row]
        self.step_label.setText(f"Step {step.step}/{len(self.current_artifacts.parse_steps)}: {step.action}")

    def format_stack(self, step: ParseStep) -> str:
        parts = [str(step.state_stack[0])]
        for symbol, state in zip(step.symbol_stack, step.state_stack[1:]):
            parts.extend([symbol, str(state)])
        return " ".join(parts)

    def _execute_current_program(self) -> None:
        if self.current_artifacts is None:
            self.populate_console("")
            return
        if self._compilation_has_errors(self.current_artifacts):
            self.populate_console("<program not executed because compilation failed>")
            self.console_input.setPlaceholderText("Fix compilation errors before providing input")
            return

        result = self.runtime.execute(self.current_artifacts.ast, self.console_inputs)
        self.populate_console(self._render_execution_output(result))
        if result.waiting_for_input:
            variable = result.requested_input or "value"
            self.console_input.setPlaceholderText(f"Input required for {variable}")
            self.statusBar().showMessage(f"Program is waiting for input: {variable}")
        elif result.diagnostics:
            self.console_input.setPlaceholderText("Program stopped with a runtime error")
            self.statusBar().showMessage("Program stopped with a runtime error")
        else:
            self.console_input.setPlaceholderText("Program finished. Enter values and rerun if needed")

    def _render_execution_output(self, result) -> str:
        text = result.output
        extras: list[str] = []
        if result.waiting_for_input:
            extras.append(f"[waiting for input: {result.requested_input}]")
        if result.diagnostics:
            extras.extend(diagnostic.format() for diagnostic in result.diagnostics)
        if not extras:
            return text
        separator = "" if not text or text.endswith("\n") else "\n"
        return f"{text}{separator}{'\n'.join(extras)}"

    def _compilation_has_errors(self, artifacts: CompilationArtifacts) -> bool:
        return any(diagnostic.level == "error" for diagnostic in artifacts.diagnostics)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() in {
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        }:
            self.run_compiler()
            return
        super().keyPressEvent(event)


def launch_gui() -> None:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("Compiler Studio")
    app.setOrganizationName("AAST")
    app.setStyle("Fusion")

    window = CompilerWorkbench()
    window.show()

    if owns_app:
        app.exec()
