"use client";

/**
 * Indexing shown inside the workspace rather than on a page of its own.
 *
 * The shell is up and the panes are visible from the first moment; the
 * chat is covered and inert until there is an index to ask questions
 * against, because a question before then has nothing to answer from.
 */

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useIndexRun } from "@/lib/useIndexRun";

const STAGE_LABELS: Record<string, string> = {
  clone: "Cloning the repository",
  filter: "Choosing which files to read",
  chunk: "Parsing functions and classes",
  write: "Storing it",
  ready: "Ready to explore",
  embed: "Improving search quality",
  done: "Done",
};

export function IndexingOverlay({ runId }: { runId: number }) {
  const router = useRouter();
  const { stages, ready, done, error } = useIndexRun(runId);
  const visible = stages.filter((stage) => stage.stage !== "failed");
  const current = visible.at(-1);

  useEffect(() => {
    // Refresh as soon as the structure is stored: the tree, the files and
    // the starter questions all exist at that point. Embedding carries on
    // behind a small indicator rather than behind this overlay.
    if (ready) router.refresh();
  }, [ready, router]);

  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center
        justify-center gap-4 bg-background/80 px-6 backdrop-blur-sm"
      role="status"
      aria-live="polite"
    >
      <div className="w-full max-w-sm">
        <p className="text-sm font-medium">
          {error
            ? "Indexing failed"
            : (STAGE_LABELS[current?.stage ?? "clone"] ?? "Working")}
        </p>
        <p className="mt-1 min-h-5 text-xs opacity-60">
          {error ?? current?.message ?? "starting"}
        </p>

        {!error && (
          <span className="mt-3 flex items-center gap-3">
            <progress
              className="h-1.5 flex-1"
              value={current?.percent ?? undefined}
              max={100}
              aria-label="Indexing progress"
            />
            <span className="w-10 shrink-0 text-right font-mono text-xs opacity-60">
              {current?.percent != null ? `${current.percent}%` : ""}
            </span>
          </span>
        )}

        <p className="mt-4 text-xs opacity-50">
          {error
            ? "Try another repository from the home page."
            : "Reading the code. Questions open up in a few seconds."}
        </p>
      </div>
    </div>
  );
}
