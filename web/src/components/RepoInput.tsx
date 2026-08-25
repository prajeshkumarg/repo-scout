"use client";

/** The one thing on the home page: paste a repo, start indexing. */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { repoSlug, startIndexing } from "@/lib/api";

const EXAMPLES = [
  "https://github.com/pallets/click",
  "https://github.com/psf/requests",
];

export function RepoInput() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(target: string) {
    const slug = repoSlug(target);
    if (!slug) {
      setError("That does not look like https://github.com/owner/name");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await startIndexing(target);
      // Straight into the workspace: it renders the shell and reports
      // indexing inside it, rather than parking on a progress page.
      router.push(`/r/${slug}?run=${run.run_id}`);
    } catch (caught) {
      // A failed fetch here usually means the API is not running, so say
      // that rather than surfacing a bare "Failed to fetch".
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(
        message.includes("fetch")
          ? "Could not reach the API. Is `make dev` running?"
          : message,
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex w-full max-w-2xl flex-col items-center">
      <form
        className="flex w-full items-stretch gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(url);
        }}
      >
        <input
          className="field min-w-0 flex-1"
          type="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://github.com/owner/repo"
          aria-label="GitHub repository URL"
          autoFocus
        />
        <button
          className="shrink-0 rounded-lg bg-accent px-6 text-[0.95rem]
            font-medium text-[#1b1b1b] transition hover:opacity-90
            disabled:opacity-50"
          type="submit"
          disabled={busy}
        >
          {busy ? "Starting…" : "Read it"}
        </button>
      </form>

      {error && (
        <p
          role="alert"
          className="mt-3 text-center text-sm text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-sm">
        <span>try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            disabled={busy}
            className="underline underline-offset-2 hover:opacity-100 disabled:opacity-40"
            onClick={() => {
              setUrl(example);
              void submit(example);
            }}
          >
            {example.replace("https://github.com/", "")}
          </button>
        ))}
      </div>
    </div>
  );
}
