"use client";

/** Live per-stage indexing progress. Never a generic spinner. */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useIndexRun } from "@/lib/useIndexRun";

const STAGE_LABELS: Record<string, string> = {
  clone: "Cloning the repository",
  filter: "Choosing which files to read",
  chunk: "Parsing functions and classes",
  embed: "Building the search index",
  write: "Storing it",
  done: "Ready",
};

export function IndexingProgress({
  runId,
  repo,
}: {
  runId: number;
  repo: string | null;
}) {
  const router = useRouter();
  const { stages, done, error } = useIndexRun(runId);
  const visible = stages.filter((stage) => stage.stage !== "failed");
  // The stage still reporting a fraction is the one the bar is for.
  const active = !done && !error
    ? visible.findLast((stage) => stage.percent !== null && stage.percent < 100)
    : undefined;

  useEffect(() => {
    if (done && repo) router.push(`/r/${repo}`);
  }, [done, repo, router]);

  return (
    <div className="w-full max-w-lg">
      <h1 className="text-xl font-semibold tracking-tight">
        Reading {repo ?? "the repository"}
      </h1>
      <p className="mt-1 text-sm opacity-60">
        Indexing happens once. Later questions are instant.
      </p>

      <ol className="mt-6 flex flex-col gap-3">
        {visible.map((stage, index) => {
          // A stage is still running if it reported a percentage below
          // 100 and nothing after it has started.
          const running =
            stage.percent !== null &&
            stage.percent < 100 &&
            index === visible.length - 1;
          return (
            <li key={stage.stage} className="flex gap-3 text-sm">
              <span aria-hidden="true" className="opacity-60">
                {running ? "…" : "✓"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="font-medium">
                  {STAGE_LABELS[stage.stage] ?? stage.stage}
                </span>
                <span className="ml-2 opacity-60">{stage.message}</span>
              </span>
            </li>
          );
        })}
        {!done && !error && (
          <li className="flex gap-3 text-sm opacity-60">
            <span aria-hidden="true">…</span>
            <span>working</span>
          </li>
        )}

        {/* The bar sits with the rows, on the same spacing, rather than
            nested inside one of them. */}
        {active !== undefined && (
          <li className="flex items-center gap-3">
            <progress
              className="h-1.5 flex-1"
              value={active.percent ?? 0}
              max={100}
              aria-label="Indexing progress"
            />
            <span className="w-10 shrink-0 text-right font-mono text-xs opacity-60">
              {active.percent}%
            </span>
          </li>
        )}
      </ol>

      {error && (
        <div className="mt-6 flex flex-col gap-3">
          <p className="flex gap-3 text-sm text-red-600 dark:text-red-400">
            <span aria-hidden="true">✗</span>
            <span className="flex-1">
              <span className="font-medium">Indexing failed</span>
              <span className="ml-2 opacity-80">{error}</span>
            </span>
          </p>
          <div>
            <a className="p-btn" href="/">
              Try another repository
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
