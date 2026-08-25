"use client";

/**
 * A quiet note that vectors are still landing.
 *
 * The repo is fully usable at this point — every tool except vector
 * search works off the text index — so this informs rather than blocks.
 */

import { useIndexRun } from "@/lib/useIndexRun";

export function EmbeddingIndicator({ runId }: { runId: number }) {
  const { stages, done, error } = useIndexRun(runId);
  const embed = stages.find((stage) => stage.stage === "embed");

  if (done || error || !embed) return null;

  return (
    <span
      className="ml-3 flex items-center gap-2 text-xs opacity-60"
      title="Search improves as the rest of the code is indexed"
    >
      <progress className="h-1 w-16" value={embed.percent ?? 0} max={100} />
      improving search {embed.percent != null ? `${embed.percent}%` : ""}
    </span>
  );
}
