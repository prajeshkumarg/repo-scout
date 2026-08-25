"use client";

/** The conversation column: trace, answer, clickable citations. */

import { Children, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { AgentTrace } from "@/components/AgentTrace";
import type { CitationRef, Exchange } from "@/lib/useAgentRun";

// Ranges and single lines both: the model writes README.md:16 as often
// as README.md:1-8, and only the range form was becoming a chip.
const CITATION = /^([\w./-]+):(\d+)(?:-(\d+))?$/;
const CITATION_IN_TEXT = /\b([\w./-]+):(\d+)(?:-(\d+))?\b/g;

/** A citation rendered as a chip that drives the code viewer. */
function Chip({
  label,
  citation,
  onCitation,
}: {
  label: string;
  citation: CitationRef;
  onCitation: (citation: CitationRef) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onCitation(citation)}
      className="mx-0.5 rounded bg-accent/15 px-1 font-mono text-[11px]
        text-accent hover:bg-accent/30"
    >
      {label}
    </button>
  );
}

/** Turn any bare path:start-end inside plain text into chips. */
function chipsInText(
  text: string,
  onCitation: (citation: CitationRef) => void,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(CITATION_IN_TEXT)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(text.slice(cursor, index));
    parts.push(
      <Chip
        key={`${index}-${match[0]}`}
        label={match[0]}
        citation={{
          path: match[1],
          start: Number(match[2]),
          end: Number(match[3]),
        }}
        onCitation={onCitation}
      />,
    );
    cursor = index + match[0].length;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}

/**
 * Apply the chip transform to the string children of a markdown node.
 *
 * Markdown gives us mixed children: strings plus already-rendered
 * elements (emphasis, inline code). Only the strings can contain a bare
 * citation, so the elements pass through untouched.
 */
function chipsInChildren(
  children: React.ReactNode,
  onCitation: (citation: CitationRef) => void,
): React.ReactNode {
  return Children.map(children, (child) =>
    typeof child === "string" ? chipsInText(child, onCitation) : child,
  );
}

/**
 * The answer, rendered as markdown.
 *
 * The model writes lists, emphasis and inline code, which read as
 * literal asterisks and backticks otherwise. Citations stay clickable
 * whether the model wrapped them in backticks (the common case) or left
 * them bare in a sentence.
 */
function AnswerBody({
  text,
  onCitation,
}: {
  text: string;
  onCitation: (citation: CitationRef) => void;
}) {
  return (
    <div className="answer text-sm leading-relaxed">
      <ReactMarkdown
        components={{
          code({ children, ...props }) {
            const content = String(children);
            const match = CITATION.exec(content);
            if (match) {
              return (
                <Chip
                  label={content}
                  citation={{
                    path: match[1],
                    start: Number(match[2]),
                    end: Number(match[3] ?? match[2]),
                  }}
                  onCitation={onCitation}
                />
              );
            }
            return (
              <code
                className="rounded bg-current/10 px-1 font-mono text-[0.85em]"
                {...props}
              >
                {children}
              </code>
            );
          },
          p({ children }) {
            return (
              <p className="my-2">{chipsInChildren(children, onCitation)}</p>
            );
          },
          ul({ children }) {
            return <ul className="my-2 list-disc pl-5">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="my-2 list-decimal pl-5">{children}</ol>;
          },
          li({ children }) {
            return (
              <li className="my-0.5">
                {chipsInChildren(children, onCitation)}
              </li>
            );
          },
          a({ children, href }) {
            return (
              <a className="underline" href={href}>
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function ChatPanel({
  exchanges,
  running,
  onAsk,
  onCancel,
  onCitation,
  draft,
  empty,
  disabled = false,
}: {
  exchanges: Exchange[];
  running: boolean;
  onAsk: (question: string) => void;
  onCancel: () => void;
  onCitation: (citation: CitationRef) => void;
  draft?: string | null;
  /** Shown in place of the transcript before the first question. */
  empty?: React.ReactNode;
  /** No index to answer from yet, so the composer is inert. */
  disabled?: boolean;
}) {
  const [question, setQuestion] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (draft) setQuestion(draft);
  }, [draft]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [exchanges]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-6 overflow-auto p-4">
        {exchanges.length === 0 && empty}
        {exchanges.map((exchange, index) => (
          <article key={index} className="space-y-2">
            <p className="text-sm font-medium">{exchange.question}</p>
            <AgentTrace steps={exchange.steps} />
            {exchange.answer && (
              <AnswerBody text={exchange.answer} onCitation={onCitation} />
            )}
            {exchange.error && (
              <p className="text-sm text-red-600 dark:text-red-400">
                {exchange.error}
              </p>
            )}
            {!exchange.done && !exchange.answer && (
              <p className="text-xs opacity-50">thinking…</p>
            )}
          </article>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        className="flex gap-2 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!question.trim() || running || disabled) return;
          onAsk(question.trim());
          setQuestion("");
        }}
      >
        <input
          className="field flex-1 !rounded-xl !px-4 !py-2.5 text-sm
            disabled:opacity-50"
          disabled={disabled}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this codebase…"
          aria-label="Question"
        />
        {running ? (
          <button
            type="button"
            className="p-btn p-btn-destructive"
            onClick={onCancel}
          >
            Stop
          </button>
        ) : (
          <button className="p-btn" type="submit">
            Ask
          </button>
        )}
      </form>
    </div>
  );
}
