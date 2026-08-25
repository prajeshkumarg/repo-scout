/**
 * The four steps, connected, so the mechanism is visible before anyone
 * commits a URL. Server component: no interactivity here.
 */

const STEPS = [
  { n: 1, title: "paste a repo", body: "any public GitHub URL" },
  { n: 2, title: "we read it", body: "every function and class, indexed" },
  { n: 3, title: "ask in English", body: "an agent walks the code" },
  { n: 4, title: "get proof", body: "answers cite file:line you can click" },
];

export function HowItWorks() {
  return (
    <section className="w-full max-w-3xl px-1" aria-label="How it works">
      <ol className="flex flex-col gap-6 sm:flex-row sm:items-start sm:gap-0">
        {STEPS.map((step, index) => (
          <li key={step.n} className="flex flex-1 items-start gap-3 sm:flex-col">
            <div className="flex items-center gap-3 sm:w-full">
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center
                  rounded-full border border-current text-xs font-semibold
                  opacity-80"
                aria-hidden="true"
              >
                {step.n}
              </span>
              {index < STEPS.length - 1 && (
                <span
                  className="hidden h-px flex-1 bg-current opacity-20 sm:block"
                  aria-hidden="true"
                />
              )}
            </div>
            <div className="sm:mt-3 sm:pr-6">
              <p className="text-sm font-medium">{step.title}</p>
              <p className="text-sm opacity-60">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <p className="mx-auto mt-10 max-w-2xl text-center text-sm leading-relaxed text-accent">
        Searching a codebase returns snippets that <em>look</em> similar. Real
        answers need navigation — handler to service to model. repo-scout runs
        an agent that walks the code, and every claim it makes carries a line
        range you can open.
      </p>
    </section>
  );
}
