import { HowItWorks } from "@/components/HowItWorks";
import { RepoInput } from "@/components/RepoInput";

export default function Home() {
  return (
    <main
      className="mx-auto flex min-h-screen w-full max-w-4xl flex-col
        items-center justify-center gap-12 px-6 py-16"
    >
      <header className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight text-accent">
          repo-scout
        </h1>
        <p className="mt-2 text-sm opacity-70">
          Ask questions about any codebase. Get answers with citations.
        </p>
      </header>

      <RepoInput />

      <hr className="w-full max-w-3xl border-t border-current opacity-10" />

      <HowItWorks />
    </main>
  );
}
