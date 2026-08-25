"use client";

/** Questions built from real symbols, so they are never generic filler. */

export function StarterQuestions({
  questions,
  onAsk,
}: {
  questions: string[];
  onAsk?: (question: string) => void;
}) {
  if (questions.length === 0) return null;
  return (
    <section className="mt-6 w-full max-w-sm">
      <h2 className="text-xs font-semibold uppercase tracking-wide opacity-40">
        Try asking
      </h2>
      <ul className="mt-3 flex flex-col gap-2">
        {questions.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onAsk?.(question)}
              className="w-full rounded-xl border border-border bg-surface
                px-3 py-2.5 text-left text-sm text-accent transition
                hover:border-border"
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
