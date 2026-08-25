import { RepoWorkspace } from "@/components/RepoWorkspace";
import { fetchOrientation, fetchTree, type Orientation } from "@/lib/api";

export default async function RepoPage(props: {
  params: Promise<{ owner: string; name: string }>;
  searchParams: Promise<{ run?: string }>;
}) {
  const { owner, name } = await props.params;
  const { run } = await props.searchParams;
  const runId = run ? Number(run) : null;

  // A repo being indexed for the first time has no orientation or tree
  // yet. The shell still renders: the overlay reports progress inside
  // it, and refreshes this page once there is an index to show.
  let orientation: Orientation | null = null;
  let tree: string[] = [];
  try {
    [orientation, tree] = await Promise.all([
      fetchOrientation(owner, name),
      fetchTree(owner, name),
    ]);
  } catch (error) {
    if (runId === null) {
      return (
        <main className="mx-auto flex min-h-screen max-w-2xl items-center justify-center px-6">
          <div className="text-center">
            <h1 className="text-lg font-semibold">
              {owner}/{name} is not indexed
            </h1>
            <p className="mt-2 text-sm opacity-60">
              {error instanceof Error ? error.message : String(error)}
            </p>
            <a
              className="mt-5 inline-block rounded-full bg-accent px-5 py-2
                text-sm font-medium text-[#1b1b1b]"
              href="/"
            >
              Index a repository
            </a>
          </div>
        </main>
      );
    }
  }

  return (
    <RepoWorkspace
      owner={owner}
      name={name}
      orientation={orientation}
      tree={tree}
      runId={runId}
    />
  );
}
