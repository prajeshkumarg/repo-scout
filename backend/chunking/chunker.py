"""Symbol-boundary chunking for Python and TypeScript.

The rules this implements (from .claude/rules/ingest.md):

- Chunk at tree-sitter symbol boundaries, never fixed token windows.
- A symbol larger than the budget is split, but every piece carries the
  full symbol signature. A chunk with no signature is unretrievable.
- A file that fails to parse is logged and falls back to whole-file
  chunking; the run continues.
- Module-level statements that do not belong to a symbol (constants,
  docstrings, setup code) become "module" chunks. Runs of pure import
  statements produce nothing: imports are attached to every chunk.

Line numbers are 1-based and refer to real file lines, so citations can be
checked against them. On split pieces past the first, `content` starts with
the signature lines while `start_line` points at the piece's first body
line: the signature is context for the embedder, not part of the cited
range.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tree_sitter import Node

from chunking.languages import parse

logger = logging.getLogger(__name__)

# Kinds a symbol can be. "method" is a function defined in a class body.
KIND_FUNCTION = "function"
KIND_METHOD = "method"
KIND_CLASS = "class"
KIND_MODULE = "module"

_PY_IMPORT_TYPES = {"import_statement", "import_from_statement"}
_TS_IMPORT_TYPES = {"import_statement"}
_TS_DECLARATION_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
    "abstract_class_declaration",
    "lexical_declaration",
}


@dataclass
class Chunk:
    """One retrievable piece of a source file."""

    path: str
    language: str
    symbol_kind: str
    start_line: int
    end_line: int
    content: str
    symbol_name: str | None = None
    parent_symbol: str | None = None
    imports: list[str] = field(default_factory=list)


@dataclass
class _Unit:
    """A symbol found at module or class level.

    `top` is the statement node as seen by the enclosing scope, so
    decorated and exported definitions count as covered in the module
    walk. `node` is the definition node itself.
    """

    top: Node
    node: Node
    kind: str
    name: str | None
    parent: str | None


@dataclass
class Symbol:
    """A definition site: one row of the symbol table."""

    path: str
    name: str
    kind: str
    line: int
    parent: str | None = None


def symbols_for(path: str, source: str) -> list[Symbol]:
    """Definition sites in a file: module symbols plus all class members.

    Separate from chunking because the symbol table needs every method,
    including methods of classes small enough to stay in one chunk.
    Files too broken to parse yield no symbols.
    """
    try:
        language, tree = parse(path, source)
    except ValueError:
        return []
    root = tree.root_node
    if _is_broken(root):
        return []
    symbols: list[Symbol] = []
    for child in root.named_children:
        for unit in _units_for_statement(child, language, parent=None):
            symbols.extend(_symbols_from_unit(path, unit, language))
    return symbols


def _symbols_from_unit(path: str, unit: _Unit, language: str) -> list[Symbol]:
    if not unit.name:
        return []
    start, _ = _line_range(unit.node)
    symbols = [
        Symbol(
            path=path, name=unit.name, kind=unit.kind, line=start, parent=unit.parent
        )
    ]
    if unit.kind == KIND_CLASS:
        body = unit.node.child_by_field_name("body")
        if body is not None:
            for member in body.named_children:
                for member_unit in _units_for_statement(
                    member, language, parent=unit.name
                ):
                    symbols.extend(_symbols_from_unit(path, member_unit, language))
    return symbols


def chunk_file(path: str, source: str, max_chars: int) -> list[Chunk]:
    """Chunk one source file at symbol boundaries.

    `max_chars` is the chunk budget. The budget is compared against the
    character count of chunk content, a cheap proxy for tokens (chars / 4).
    """
    language, tree = parse(path, source)
    root = tree.root_node
    if _is_broken(root):
        logger.warning(
            "%s is too broken to parse; falling back to whole-file chunk", path
        )
        return _whole_file_chunks(path, language, source, max_chars)

    lines = source.splitlines(keepends=True)
    imports = _extract_imports(root, language)
    units = {id(unit.top): unit for unit in _collect_units(root, language)}
    import_types = _PY_IMPORT_TYPES if language == "python" else _TS_IMPORT_TYPES

    chunks: list[Chunk] = []
    run: list[Node] = []  # consecutive top-level statements that are not units

    def flush_run() -> None:
        if not run:
            return
        # A run that is only imports adds nothing: imports ride along on
        # every chunk already.
        if any(node.type not in import_types for node in run):
            chunks.extend(
                _module_chunks(path, language, run, lines, max_chars, imports)
            )
        run.clear()

    for top_child in root.named_children:
        unit = units.get(id(top_child))
        if unit is not None:
            flush_run()
            chunks.extend(_chunk_unit(path, language, unit, lines, max_chars, imports))
        else:
            run.append(top_child)
    flush_run()
    return chunks


def _is_broken(root: Node) -> bool:
    """True when more than half of the top-level statements have errors.

    tree-sitter's error recovery is local: one unparsable construct in an
    otherwise fine file must not cost the whole file its symbol names
    (real case: zustand's vanilla.ts, one error in 100 lines). Files that
    are fundamentally unparsable still get the whole-file fallback.
    """
    statements = root.named_children
    if not statements:
        return root.has_error
    broken = sum(1 for stmt in statements if stmt.has_error)
    return broken * 2 > len(statements)


# --- unit collection --------------------------------------------------------


def _collect_units(root: Node, language: str) -> list[_Unit]:
    """Find symbol units at module level, unwrapping decorators and exports."""
    units: list[_Unit] = []
    for child in root.named_children:
        units.extend(_units_for_statement(child, language, parent=None))
    return units


def _units_for_statement(node: Node, language: str, parent: str | None) -> list[_Unit]:
    """Classify one statement into zero or one unit."""
    top = node
    node = _unwrap(node, language)

    if language == "python":
        if node.type == "function_definition":
            return [_make_unit(top, node, _function_kind(parent), parent)]
        if node.type == "class_definition":
            return [_make_unit(top, node, KIND_CLASS, parent)]
        return []

    if node.type in (
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
    ):
        return [_make_unit(top, node, _function_kind(parent), parent)]
    if node.type in ("class_declaration", "abstract_class_declaration"):
        return [_make_unit(top, node, KIND_CLASS, parent)]
    if node.type == "lexical_declaration":
        # `const name = (...) => ...` is a callable symbol. If a statement
        # declares several, one chunk covers the statement, named by the
        # first arrow function declared.
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            value = declarator.child_by_field_name("value")
            if value is not None and _is_arrow(value):
                name_node = declarator.child_by_field_name("name")
                name = _text(name_node) if name_node is not None else None
                return [
                    _Unit(
                        top=top, node=top, kind=KIND_FUNCTION, name=name, parent=parent
                    )
                ]
    return []


_TS_VALUE_WRAPPERS = {
    "parenthesized_expression",
    "type_assertion",
    "as_expression",
    "satisfies_expression",
    "non_null_expression",
}


def _is_arrow(node: Node) -> bool:
    """True when the node is an arrow function, through value wrappers.

    Real-world declarations like `const f = ((x) => x) as Cast` wrap the
    arrow in parentheses and type casts; without unwrapping, the symbol
    falls through to module-level chunking and loses its name.
    """
    while node.type in _TS_VALUE_WRAPPERS and node.named_children:
        node = node.named_children[0]
    return node.type == "arrow_function"


def _unwrap(node: Node, language: str) -> Node:
    """Strip decorators/exports down to the definition node."""
    while True:
        if language == "python" and node.type == "decorated_definition":
            node = node.named_children[-1]
        elif language != "python" and node.type == "export_statement":
            declarations = [
                child
                for child in node.named_children
                if child.type in _TS_DECLARATION_TYPES
            ]
            if len(declarations) == 1:
                node = declarations[0]
            else:
                return node  # re-exports and export lists are not units
        else:
            return node


def _make_unit(top: Node, node: Node, kind: str, parent: str | None) -> _Unit:
    name_node = node.child_by_field_name("name")
    return _Unit(
        top=top,
        node=node,
        kind=kind,
        name=_text(name_node) if name_node is not None else None,
        parent=parent,
    )


def _function_kind(parent: str | None) -> str:
    """A function inside a class body is a method."""
    return KIND_METHOD if parent is not None else KIND_FUNCTION


# --- per-unit chunking ------------------------------------------------------


def _chunk_unit(
    path: str,
    language: str,
    unit: _Unit,
    lines: list[str],
    max_chars: int,
    imports: list[str],
) -> list[Chunk]:
    """Chunk one symbol unit, splitting only when it exceeds the budget."""
    start, end = _line_range(unit.top)
    content = _join(lines, start, end)
    if unit.kind == KIND_CLASS and len(content) > max_chars:
        return _chunk_big_class(path, language, unit, lines, max_chars, imports)
    if len(content) <= max_chars:
        return [_make_chunk(path, language, unit, start, end, content, imports)]
    return _split_symbol(path, language, unit, lines, max_chars, imports)


def _chunk_big_class(
    path: str,
    language: str,
    unit: _Unit,
    lines: list[str],
    max_chars: int,
    imports: list[str],
) -> list[Chunk]:
    """An over-budget class: header chunk(s) plus one chunk per member symbol."""
    body = unit.node.child_by_field_name("body")
    if body is None:
        return _split_symbol(path, language, unit, lines, max_chars, imports)

    chunks: list[Chunk] = []
    # The header: signature, docstring, and class-level statements that are
    # not themselves symbols. Methods and nested classes get their own
    # chunks below.
    header_ranges = [
        _line_range(member)
        for member in body.named_children
        if not _units_for_statement(member, language, parent=unit.name)
    ]
    chunks.extend(
        _split_symbol(path, language, unit, lines, max_chars, imports, header_ranges)
    )
    for member in body.named_children:
        member_units = _units_for_statement(member, language, parent=unit.name)
        for member_unit in member_units:
            chunks.extend(
                _chunk_unit(path, language, member_unit, lines, max_chars, imports)
            )
    return chunks


def _split_symbol(
    path: str,
    language: str,
    unit: _Unit,
    lines: list[str],
    max_chars: int,
    imports: list[str],
    statement_ranges: list[tuple[int, int]] | None = None,
) -> list[Chunk]:
    """Split an over-budget symbol at statement boundaries.

    The signature is prepended to every piece. `statement_ranges` overrides
    the body's statements (used for class headers, which exclude methods).
    """
    body = unit.node.child_by_field_name("body")
    sig_start, _ = _line_range(unit.top)
    sig_end_line = body.start_point.row + 1 if body is not None else None

    if sig_end_line is None:
        # A bodyless symbol (abstract TS method): split raw lines.
        start, end = _line_range(unit.top)
        return _split_lines(
            path, language, unit, lines, start, end, max_chars, imports, signature=""
        )

    sig_text = _signature_text(lines, sig_start, sig_end_line, max_chars)
    if statement_ranges is None:
        statement_ranges = [_line_range(stmt) for stmt in body.named_children]

    pieces: list[tuple[int, int, str]] = []
    current = sig_text
    piece_start = sig_start
    last_end = sig_end_line - 1
    for stmt_start, stmt_end in statement_ranges:
        stmt_text = _join(lines, stmt_start, stmt_end)
        if len(current) + len(stmt_text) > max_chars and current != sig_text:
            pieces.append((piece_start, last_end, current))
            current = sig_text + stmt_text
            piece_start = stmt_start
        else:
            current += stmt_text
        last_end = stmt_end
    pieces.append((piece_start, last_end, current))

    chunks: list[Chunk] = []
    for piece_start, piece_end, piece_text in pieces:
        if piece_start > piece_end:
            # A gap (blank lines) between statements can leave a piece with
            # no range of its own; its content rides with its neighbours.
            continue
        if len(piece_text) > max_chars:
            # One statement alone is over budget: split by lines.
            chunks.extend(
                _split_lines(
                    path,
                    language,
                    unit,
                    lines,
                    piece_start,
                    piece_end,
                    max_chars,
                    imports,
                    signature=sig_text,
                )
            )
        else:
            chunks.append(
                _make_chunk(
                    path, language, unit, piece_start, piece_end, piece_text, imports
                )
            )
    return chunks


def _split_lines(
    path: str,
    language: str,
    unit: _Unit,
    lines: list[str],
    start: int,
    end: int,
    max_chars: int,
    imports: list[str],
    signature: str,
) -> list[Chunk]:
    """Last resort: split a range by lines.

    `signature` is prepended to pieces that do not already contain it (the
    first piece of a split symbol starts at the signature lines itself).
    """
    if start > end:
        return []  # an empty range has no lines; never emit a phantom chunk
    chunks: list[Chunk] = []
    starts_with_signature = signature and start <= unit.top.start_point.row + 1
    current = "" if starts_with_signature else signature
    piece_start = start
    last_line = start
    for line_no in range(start, end + 1):
        line_text = lines[line_no - 1]
        if len(current) + len(line_text) > max_chars and current not in ("", signature):
            chunks.append(
                _make_chunk(
                    path, language, unit, piece_start, last_line, current, imports
                )
            )
            current = signature + line_text
            piece_start = line_no
        else:
            current += line_text
        last_line = line_no
    chunks.append(
        _make_chunk(path, language, unit, piece_start, last_line, current, imports)
    )
    return chunks


def _make_chunk(
    path: str,
    language: str,
    unit: _Unit,
    start: int,
    end: int,
    content: str,
    imports: list[str],
) -> Chunk:
    return Chunk(
        path=path,
        language=language,
        symbol_kind=unit.kind,
        symbol_name=unit.name,
        parent_symbol=unit.parent,
        start_line=start,
        end_line=end,
        content=content,
        imports=imports,
    )


# --- module-level leftovers -------------------------------------------------


def _module_chunks(
    path: str,
    language: str,
    run: list[Node],
    lines: list[str],
    max_chars: int,
    imports: list[str],
) -> list[Chunk]:
    """Chunk a run of consecutive top-level statements that are not symbols."""
    start, _ = _line_range(run[0])
    _, end = _line_range(run[-1])
    content = _join(lines, start, end)
    if len(content) <= max_chars:
        return [
            Chunk(
                path=path,
                language=language,
                symbol_kind=KIND_MODULE,
                start_line=start,
                end_line=end,
                content=content,
                imports=imports,
            )
        ]
    # A giant run (a data table, say): split by lines.
    chunks: list[Chunk] = []
    current: list[str] = []
    piece_start = start
    last_line = start
    for line_no in range(start, end + 1):
        line_text = lines[line_no - 1]
        if sum(map(len, current)) + len(line_text) > max_chars and current:
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    symbol_kind=KIND_MODULE,
                    start_line=piece_start,
                    end_line=last_line,
                    content="".join(current),
                    imports=imports,
                )
            )
            current = [line_text]
            piece_start = line_no
        else:
            current.append(line_text)
        last_line = line_no
    chunks.append(
        Chunk(
            path=path,
            language=language,
            symbol_kind=KIND_MODULE,
            start_line=piece_start,
            end_line=last_line,
            content="".join(current),
            imports=imports,
        )
    )
    return chunks


# --- fallback ---------------------------------------------------------------


def _whole_file_chunks(
    path: str, language: str, source: str, max_chars: int
) -> list[Chunk]:
    """Parse failed: emit the file as module chunks, split only by budget."""
    lines = source.splitlines(keepends=True)
    chunks: list[Chunk] = []
    current: list[str] = []
    piece_start = 1
    last_line = 1
    for line_no, line_text in enumerate(lines, start=1):
        if sum(map(len, current)) + len(line_text) > max_chars and current:
            chunks.append(
                Chunk(
                    path=path,
                    language=language,
                    symbol_kind=KIND_MODULE,
                    start_line=piece_start,
                    end_line=last_line,
                    content="".join(current),
                )
            )
            current = [line_text]
            piece_start = line_no
        else:
            current.append(line_text)
        last_line = line_no
    if current:
        chunks.append(
            Chunk(
                path=path,
                language=language,
                symbol_kind=KIND_MODULE,
                start_line=piece_start,
                end_line=last_line,
                content="".join(current),
            )
        )
    return chunks


# --- imports ----------------------------------------------------------------


def _extract_imports(root: Node, language: str) -> list[str]:
    """Module-level imports, best effort."""
    names: list[str] = []
    for child in root.named_children:
        if language == "python":
            if child.type == "import_statement":
                for sub in child.named_children:
                    if sub.type == "dotted_name":
                        names.append(_text(sub))
                    elif sub.type == "aliased_import":
                        name = sub.child_by_field_name("name")
                        if name is not None:
                            names.append(_text(name))
            elif child.type == "import_from_statement":
                module = child.child_by_field_name("module_name")
                if module is not None:
                    names.append(_text(module))
        else:
            source = child.child_by_field_name("source")
            if child.type == "import_statement" and source is not None:
                names.append(_source_text(source))
            elif child.type == "export_statement" and source is not None:
                # Re-exports are dependencies too.
                names.append(_source_text(source))
    return names


def _source_text(source: Node) -> str:
    inner = source.named_children
    if inner:
        return _text(inner[0])
    return _text(source).strip("\"'`")


# --- helpers ----------------------------------------------------------------


def _signature_text(
    lines: list[str], sig_start: int, sig_end_line: int, max_chars: int
) -> str:
    """The symbol signature, capped to the chunk budget.

    A pathological signature (FastAPI's __init__ has ~815 lines of typed
    parameters) cannot ride along on every piece. The first lines keep the
    name and shape; a marker says the rest was truncated.
    """
    sig_text = "".join(lines[sig_start - 1 : sig_end_line - 1])
    if len(sig_text) <= max_chars:
        return sig_text
    kept = 8
    total = sig_end_line - sig_start
    return "".join(lines[sig_start - 1 : sig_start - 1 + kept]) + (
        f"# ... {total - kept} signature lines truncated\n"
    )


def _line_range(node: Node) -> tuple[int, int]:
    """1-based inclusive line range of a node.

    tree-sitter nodes include their trailing newline; the range must point
    at real content lines or citations resolve to nothing.
    """
    start = node.start_point.row + 1
    end = node.end_point.row + 1
    if node.text.endswith(b"\n") and end > start:
        end -= 1
    return start, end


def _join(lines: list[str], start: int, end: int) -> str:
    """Join 1-based inclusive line numbers into one string."""
    return "".join(lines[start - 1 : end])


def _text(node: Node) -> str:
    return node.text.decode("utf8")
