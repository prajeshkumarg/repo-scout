import { IndexingProgress } from "@/components/IndexingProgress";

// params and searchParams are async in Next 16.
export default async function IndexingPage(props: {
  params: Promise<{ runId: string }>;
  searchParams: Promise<{ repo?: string }>;
}) {
  const { runId } = await props.params;
  const { repo } = await props.searchParams;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-4xl items-center justify-center px-6">
      <IndexingProgress runId={Number(runId)} repo={repo ?? null} />
    </main>
  );
}
