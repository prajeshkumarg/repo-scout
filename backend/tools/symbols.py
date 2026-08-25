"""Symbol tools: find_symbol and find_references."""

from __future__ import annotations

from tools.base import FIND_MAX_RESULTS, ToolContext, ToolResult


def find_symbol(ctx: ToolContext, name: str) -> ToolResult:
    """Definition sites of a symbol, from the symbol table."""
    rows = ctx.conn.execute(
        """
        SELECT name, kind, path, line, parent_symbol FROM symbols
        WHERE repo_id = %s AND sha = %s AND name = %s
        ORDER BY path, line
        LIMIT %s
        """,
        (ctx.repo_id, ctx.sha, name, FIND_MAX_RESULTS),
    ).fetchall()
    if not rows:
        return ToolResult(summary=f"find_symbol {name}: not found", content="not found")
    lines = []
    for symbol_name, kind, path, line, parent in rows:
        label = f"{path}:{line}  {kind} {symbol_name}"
        if parent:
            label += f" (in {parent})"
        lines.append(label)
    body = "\n".join(lines)
    if len(rows) == FIND_MAX_RESULTS:
        body += "\n... truncated at 20 results"
    return ToolResult(
        summary=f"find_symbol {name}: {len(rows)} definition(s)",
        content=body,
        files_read=[row[2] for row in rows],
    )


def find_references(ctx: ToolContext, name: str) -> ToolResult:
    """Uses of an identifier, best effort: exact FTS over chunk text."""
    rows = ctx.conn.execute(
        """
        SELECT path, start_line, end_line, content FROM chunks
        WHERE repo_id = %s AND sha = %s
          AND tsv @@ plainto_tsquery('simple', %s)
        ORDER BY path, start_line
        LIMIT %s
        """,
        (ctx.repo_id, ctx.sha, name, FIND_MAX_RESULTS),
    ).fetchall()
    if not rows:
        return ToolResult(
            summary=f"find_references {name}: no matches", content="no matches"
        )
    lines = [
        f"{path}:{start}-{end}  {content.splitlines()[0] if content else ''}"
        for path, start, end, content in rows
    ]
    body = "\n".join(lines)
    if len(rows) == FIND_MAX_RESULTS:
        body += "\n... truncated at 20 results"
    return ToolResult(
        summary=f"find_references {name}: {len(rows)} match(es)",
        content=body,
        files_read=[row[0] for row in rows],
    )
