/**
 * The landing state for a freshly indexed repo.
 *
 * Deliberately just the starter questions: the file tree and symbol
 * outline already sit in the left pane, so repeating stack, entry
 * points and key files here was duplicate furniture between the user
 * and their first question.
 */

import { StarterQuestions } from "@/components/StarterQuestions";
import type { Orientation as OrientationPayload } from "@/lib/api";

export function Orientation({
  orientation,
  onAsk,
}: {
  orientation: OrientationPayload;
  onAsk?: (question: string) => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-2 text-center">
      <p className="text-sm opacity-60">
        Indexed {Object.values(orientation.languages).reduce((a, b) => a + b, 0)}{" "}
        files at{" "}
        <span className="font-mono">{orientation.sha.slice(0, 8)}</span>
      </p>
      <StarterQuestions
        questions={orientation.starter_questions}
        onAsk={onAsk}
      />
    </div>
  );
}
