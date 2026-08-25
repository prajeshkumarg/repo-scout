/**
 * The typed SSE event contract.
 *
 * This file mirrors backend/api/events.py. The web rules say change both
 * or neither: if you add an event type here, add it there and to the
 * spec in the same commit.
 */

export type StepStart = {
  type: "step_start";
  step: number;
  tool: string;
  args: Record<string, unknown>;
};

export type StepResult = {
  type: "step_result";
  step: number;
  summary: string;
};

export type Token = { type: "token"; text: string };

export type Citation = {
  type: "citation";
  path: string;
  start: number;
  end: number;
};

export type Done = {
  type: "done";
  steps: number;
  tokens: number;
  ms: number;
  cost_usd: number;
};

export type Progress = {
  type: "progress";
  stage: string;
  message: string;
  percent: number | null;
};

export type ErrorEvent = {
  type: "error";
  code: string;
  message: string;
  retryable: boolean;
};

export type Event =
  | StepStart
  | StepResult
  | Token
  | Citation
  | Done
  | Progress
  | ErrorEvent;

/**
 * Read an SSE body as typed events, yielding each as it arrives.
 *
 * EventSource cannot POST, and asking a question is a POST, so the
 * stream is read off fetch's ReadableStream instead.
 */
export async function* readEvents(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<Event> {
  const body = response.body;
  if (!body) return;
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;

      // Frames are separated by a blank line; a partial frame stays in
      // the buffer until the rest of it arrives.
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (line) yield JSON.parse(line.slice(6)) as Event;
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}
