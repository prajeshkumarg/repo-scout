"""File-oriented tools: read_file, list_dir, grep, git_log.

All of them read from the `files` table, so they work offline against
the same SHA the chunks are pinned to.
"""

from __future__ import annotations

import re

from tools.base import (
    FIND_MAX_RESULTS,
    GREP_MAX_MATCHES,
    READ_FILE_MAX_LINES,
    ToolContext,
    ToolResult,
    error_result,
)


def read_file(
    ctx: ToolContext, path: str, start: int = 1, end: int | None = None
) -> ToolResult:
    """Read a line range of a file (1-based inclusive, max 400 lines)."""
    row = ctx.conn.execute(
        "SELECT content FROM files WHERE repo_id = %s AND sha = %s AND path = %s",
        (ctx.repo_id, ctx.sha, path),
    ).fetchone()
    if row is None:
        return error_result(f"no file {path!r} at this revision")
    lines = row[0].splitlines()
    end = len(lines) if end is None else min(end, len(lines))
    if start > end or start < 1:
        return error_result(
            f"invalid range {start}-{end} for {path} ({len(lines)} lines)"
        )
    if end - start + 1 > READ_FILE_MAX_LINES:
        truncated = True
        end = start + READ_FILE_MAX_LINES - 1
    else:
        truncated = False
    body = "\n".join(
        f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1)
    )
    if truncated:
        body += (
            f"\n... truncated at {READ_FILE_MAX_LINES} lines; the file has {len(lines)}"
        )
    return ToolResult(
        summary=f"read {path}:{start}-{end}",
        content=f"{path}:{start}-{end}\n{body}",
        files_read=[path],
    )


def list_dir(ctx: ToolContext, path: str = "") -> ToolResult:
    """One level of the tree: immediate files and directories."""
    prefix = f"{path.rstrip('/')}/" if path else ""
    rows = ctx.conn.execute(
        """
        SELECT DISTINCT path FROM files
        WHERE repo_id = %s AND sha = %s AND path LIKE %s
        """,
        (ctx.repo_id, ctx.sha, f"{prefix}%"),
    ).fetchall()
    entries: set[str] = set()
    for (full,) in rows:
        rest = full[len(prefix) :]
        if "/" in rest:
            entries.add(rest.split("/", 1)[0] + "/")
        else:
            entries.add(rest)
    listing = "\n".join(sorted(entries)) if entries else "(empty)"
    return ToolResult(
        summary=f"list_dir {path or '/'}: {len(entries)} entries",
        content=f"{path or '/'}\n{listing}",
    )


# Trigram indexes work on three-character sequences, so a shorter
# literal cannot narrow anything and the scan has to be broad.
MIN_TRIGRAM_LITERAL = 3


def literal_prefilter(pattern: str) -> str | None:
    """The longest plain-text run in a regex, for narrowing by trigram.

    Postgres can use the trigram index for a LIKE on a literal, so the
    scan starts from candidate files rather than every file in the repo.
    The full regex still decides what actually matches — this only
    decides what gets read. Returns None when the pattern has no literal
    long enough to narrow with, in which case everything is read.
    """
    runs = re.split(r"[^\w./-]+", pattern)
    longest = max(runs, key=len, default="")
    return longest if len(longest) >= MIN_TRIGRAM_LITERAL else None


def grep(ctx: ToolContext, pattern: str, path: str = "") -> ToolResult:
    """Regex search over file contents; exact-match semantics, capped."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return error_result(f"invalid regex {pattern!r}: {exc}")
    prefix = f"{path.rstrip('/')}/" if path else ""

    # Narrow with the index, then match exactly on what comes back.
    literal = literal_prefilter(pattern)
    if literal:
        rows = ctx.conn.execute(
            """
            SELECT path, content FROM files
            WHERE repo_id = %s AND sha = %s AND path LIKE %s
              AND content LIKE %s
            """,
            (ctx.repo_id, ctx.sha, f"{prefix}%", f"%{literal}%"),
        ).fetchall()
    else:
        rows = ctx.conn.execute(
            """
            SELECT path, content FROM files
            WHERE repo_id = %s AND sha = %s AND path LIKE %s
            """,
            (ctx.repo_id, ctx.sha, f"{prefix}%"),
        ).fetchall()

    matches: list[str] = []
    files_read: list[str] = []
    total = 0
    for file_path, content in rows:
        for line_no, line in enumerate(content.splitlines(), start=1):
            if compiled.search(line):
                total += 1
                if len(matches) < GREP_MAX_MATCHES:
                    matches.append(f"{file_path}:{line_no}: {line}")
                    if file_path not in files_read:
                        files_read.append(file_path)
    body = "\n".join(matches) if matches else "no matches"
    if total > len(matches):
        body += f"\n... truncated: {len(matches)} of {total} matches"
    return ToolResult(
        summary=f"grep {pattern!r}: {total} match(es)",
        content=body,
        files_read=files_read,
    )


def git_log(ctx: ToolContext, path: str, n: int = 10) -> ToolResult:
    """Recent commits touching a file, stored at index time."""
    row = ctx.conn.execute(
        "SELECT git_log FROM files WHERE repo_id = %s AND sha = %s AND path = %s",
        (ctx.repo_id, ctx.sha, path),
    ).fetchone()
    if row is None:
        return error_result(f"no file {path!r} at this revision")
    entries = row[0].splitlines()[: min(n, FIND_MAX_RESULTS)]
    body = "\n".join(entries) if entries else "no history for this file"
    return ToolResult(
        summary=f"git log {path}: {len(entries)} commit(s)",
        content=f"git log -- {path}\n{body}",
        files_read=[path],
    )
