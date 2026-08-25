"use client";

/**
 * The code pane: line numbers, a highlighted range, and a symbol
 * outline. A citation that does not scroll and highlight is broken, so
 * the scroll is driven by an effect on the range, not by a one-off call.
 */

import { useEffect, useRef, useState } from "react";

import { fetchSymbols } from "@/lib/api";
import type { SymbolEntry } from "@/lib/api";

/** One highlighted token; `dark` is the colour for the dark theme. */
type Token = { content: string; color?: string; dark?: string };

export type Range = { start: number; end: number } | null;

export function CodeViewer({
  owner,
  name,
  path,
  range,
  onJump,
}: {
  owner: string;
  name: string;
  path: string | null;
  range: Range;
  onJump: (line: number) => void;
}) {
  const [lines, setLines] = useState<Token[][]>([]);
  const [symbols, setSymbols] = useState<SymbolEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const activeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setError(null);
    // Highlighting happens on the server; this receives tokens only.
    const highlighted = fetch(
      `/api/file?owner=${owner}&name=${name}&path=${encodeURIComponent(path)}`,
    ).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "could not read file");
      return body as { lines: Token[][] };
    });

    Promise.all([highlighted, fetchSymbols(owner, name, path)])
      .then(([file, outline]) => {
        if (cancelled) return;
        setLines(file.lines);
        setSymbols(outline);
      })
      .catch((caught) => {
        if (!cancelled) setError(String(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [owner, name, path]);

  // Scroll whenever the target range changes, including when the same
  // file is already open and a different citation is clicked.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [range, lines]);

  if (!path) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm opacity-50">
        Pick a file, or click a citation in an answer.
      </div>
    );
  }

  if (error) {
    return <div className="p-4 text-sm text-red-600">{error}</div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="flex items-baseline gap-3 border-b border-border
          bg-surface px-3 py-2"
      >
        <span className="truncate font-mono text-xs">{path}</span>
        {range && (
          <span className="font-mono text-xs opacity-50">
            {range.start}-{range.end}
          </span>
        )}
      </div>

      {symbols.length > 0 && (
        <div
          className="flex gap-2 overflow-x-auto border-b border-border
            bg-surface px-3 py-1.5"
        >
          {symbols.map((symbol) => (
            <button
              key={`${symbol.name}-${symbol.line}`}
              type="button"
              onClick={() => onJump(symbol.line)}
              className="whitespace-nowrap font-mono text-[11px] opacity-60 hover:opacity-100"
              title={`${symbol.kind} at line ${symbol.line}`}
            >
              {symbol.name}
            </button>
          ))}
        </div>
      )}

      <div className="code-surface min-h-0 flex-1 overflow-auto">
        <pre className="text-sm leading-6">
          {lines.map((line, index) => {
            const lineNumber = index + 1;
            const highlighted =
              range !== null &&
              lineNumber >= range.start &&
              lineNumber <= range.end;
            return (
              <div
                key={lineNumber}
                ref={
                  highlighted && lineNumber === range.start ? activeRef : null
                }
                className={`flex ${highlighted ? "bg-yellow-200/40 dark:bg-yellow-400/20" : ""}`}
              >
                <span className="w-12 shrink-0 select-none pr-3 text-right opacity-30">
                  {lineNumber}
                </span>
                <code className="whitespace-pre">
                  {line.length === 0
                    ? " "
                    : line.map((token, position) => (
                        <span
                          key={position}
                          style={
                            {
                              color: token.color,
                              "--shiki-dark": token.dark,
                            } as React.CSSProperties
                          }
                        >
                          {token.content}
                        </span>
                      ))}
                </code>
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
