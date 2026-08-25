"use client";

/**
 * The step trace: the centrepiece of the UI.
 *
 * Each step appears the moment its event arrives, is collapsible, and
 * shows the tool name plus a one-line result summary.
 */

import { useState } from "react";

import type { TraceStep } from "@/lib/useAgentRun";

function Step({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const pending = step.summary === null;

  return (
    <li className="border-b border-current/5 last:border-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-baseline gap-2 py-1.5 text-left text-xs"
        aria-expanded={open}
      >
        <span className="opacity-40">{open ? "▾" : "▸"}</span>
        <span className="font-mono font-medium">{step.tool}</span>
        <span className="flex-1 truncate opacity-60">
          {pending ? "running…" : step.summary}
        </span>
      </button>
      {open && (
        <pre className="overflow-x-auto pb-2 pl-6 font-mono text-[11px] opacity-60">
          {JSON.stringify(step.args, null, 2)}
        </pre>
      )}
    </li>
  );
}

export function AgentTrace({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="rounded-md border border-border px-2">
      <ul>
        {steps.map((step) => (
          <Step key={step.step} step={step} />
        ))}
      </ul>
    </div>
  );
}
