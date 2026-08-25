"""Language detection and tree-sitter parser wiring.

M1 supports Python and TypeScript only (JS parses with the TS/TSX grammars).
The language name is what lands in the chunks table: "python" or "typescript".
"""

from pathlib import Path

import tree_sitter
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

# Extension -> language name used in the chunks table.
EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "typescript",
    ".tsx": "typescript",
    ".jsx": "typescript",
}

# Extension -> tree-sitter grammar. JSX has its own grammar.
_GRAMMAR_BY_EXTENSION: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".js": "typescript",
    ".tsx": "tsx",
    ".jsx": "tsx",
}

_PARSERS: dict[str, Parser] = {
    "python": Parser(Language(tree_sitter_python.language())),
    "typescript": Parser(Language(tree_sitter_typescript.language_typescript())),
    "tsx": Parser(Language(tree_sitter_typescript.language_tsx())),
}


def detect_language(path: str) -> str | None:
    """Return the language a file should be parsed as, or None if unsupported."""
    return EXTENSION_LANGUAGES.get(Path(path).suffix.lower())


def parse(path: str, source: str) -> tuple[str, tree_sitter.Tree]:
    """Parse source with the grammar for its extension.

    Raises ValueError for extensions M1 does not support, so callers filter
    first and this failing is a bug, not a fallback path.
    """
    suffix = Path(path).suffix.lower()
    grammar = _GRAMMAR_BY_EXTENSION.get(suffix)
    if grammar is None:
        raise ValueError(f"unsupported file type: {path}")
    language = EXTENSION_LANGUAGES[suffix]
    return language, _PARSERS[grammar].parse(source.encode())
