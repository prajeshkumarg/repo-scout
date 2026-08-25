"use client";

/** Follows one indexing run's SSE stream into renderable state. */

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api";
import { readEvents } from "@/lib/events";

export type Stage = { stage: string; message: string; percent: number | null };

export type IndexState = {
  stages: Stage[];
  /** Structure is stored: the repo is browsable and answerable now. */
  ready: boolean;
  /** Vectors have landed too, so search is at full strength. */
  done: boolean;
  error: string | null;
};

export function useIndexRun(runId: number): IndexState {
  const [state, setState] = useState<IndexState>({
    stages: [],
    ready: false,
    done: false,
    error: null,
  });

  useEffect(() => {
    const controller = new AbortController();

    async function follow() {
      try {
        const response = await fetch(`${API_URL}/index/${runId}/events`, {
          signal: controller.signal,
        });
        for await (const event of readEvents(response, controller.signal)) {
          // Each stage renders the moment it arrives: the rules forbid
          // buffering progress behind a generic spinner.
          if (event.type === "progress") {
            const update: Stage = {
              stage: event.stage,
              message: event.message,
              percent: event.percent,
            };
            if (event.stage === "ready") {
              setState((prev) => ({ ...prev, ready: true }));
            }
            setState((prev) => {
              // Embedding reports after every batch. Replace that stage
              // in place so the list stays a list of stages, not a log.
              const existing = prev.stages.findIndex(
                (item) => item.stage === event.stage,
              );
              if (existing === -1) {
                return { ...prev, stages: [...prev.stages, update] };
              }
              const stages = [...prev.stages];
              stages[existing] = update;
              return { ...prev, stages };
            });
          } else if (event.type === "done") {
            setState((prev) => ({ ...prev, ready: true, done: true }));
          } else if (event.type === "error") {
            setState((prev) => ({ ...prev, error: event.message }));
          }
        }
      } catch (caught) {
        if (controller.signal.aborted) return;
        setState((prev) => ({
          ...prev,
          error: caught instanceof Error ? caught.message : String(caught),
        }));
      }
    }

    void follow();
    return () => controller.abort();
  }, [runId]);

  return state;
}
