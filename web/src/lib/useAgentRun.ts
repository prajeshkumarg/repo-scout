"use client";

/** Drives one question: streams steps, then the answer and citations. */

import { useCallback, useRef, useState } from "react";

import { API_URL, startConversation } from "@/lib/api";
import { readEvents } from "@/lib/events";

export type TraceStep = { step: number; tool: string; args: Record<string, unknown>; summary: string | null };
export type CitationRef = { path: string; start: number; end: number };

export type Exchange = {
  question: string;
  steps: TraceStep[];
  answer: string;
  citations: CitationRef[];
  done: boolean;
  error: string | null;
};

export function useAgentRun(repo: string) {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [running, setRunning] = useState(false);
  const conversationRef = useRef<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    // Aborting the fetch drops the connection, which the backend sees as
    // a disconnect and turns into a real cancel inside the tool loop.
    controllerRef.current?.abort();
    setRunning(false);
  }, []);

  const ask = useCallback(
    async (question: string) => {
      if (running) return;
      setRunning(true);
      const index = exchanges.length;
      setExchanges((prev) => [
        ...prev,
        { question, steps: [], answer: "", citations: [], done: false, error: null },
      ]);

      const patch = (update: (current: Exchange) => Exchange) =>
        setExchanges((prev) =>
          prev.map((item, position) => (position === index ? update(item) : item)),
        );

      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        if (conversationRef.current === null) {
          conversationRef.current = (
            await startConversation(repo)
          ).conversation_id;
        }
        const response = await fetch(
          `${API_URL}/conversations/${conversationRef.current}/messages`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
            signal: controller.signal,
          },
        );

        for await (const event of readEvents(response, controller.signal)) {
          // Every step renders the moment its event lands; the trace is
          // never buffered until the run finishes.
          if (event.type === "step_start") {
            patch((current) => ({
              ...current,
              steps: [
                ...current.steps,
                { step: event.step, tool: event.tool, args: event.args, summary: null },
              ],
            }));
          } else if (event.type === "step_result") {
            patch((current) => ({
              ...current,
              steps: current.steps.map((step) =>
                step.step === event.step ? { ...step, summary: event.summary } : step,
              ),
            }));
          } else if (event.type === "token") {
            patch((current) => ({
              ...current,
              answer: current.answer + event.text,
            }));
          } else if (event.type === "citation") {
            patch((current) => ({
              ...current,
              citations: [
                ...current.citations,
                { path: event.path, start: event.start, end: event.end },
              ],
            }));
          } else if (event.type === "done") {
            patch((current) => ({ ...current, done: true }));
          } else if (event.type === "error") {
            patch((current) => ({ ...current, error: event.message, done: true }));
          }
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          patch((current) => ({
            ...current,
            error: caught instanceof Error ? caught.message : String(caught),
            done: true,
          }));
        }
      } finally {
        setRunning(false);
        controllerRef.current = null;
      }
    },
    [repo, running, exchanges.length],
  );

  return { exchanges, running, ask, cancel };
}
