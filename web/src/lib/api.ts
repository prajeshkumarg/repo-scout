/**
 * Backend API client.
 *
 * The base URL comes from the environment so nothing is hardcoded to a
 * host. Types here mirror the pydantic response models in backend/api.
 */

/**
 * Where the API lives.
 *
 * An explicit NEXT_PUBLIC_API_URL always wins. Otherwise the browser
 * talks to port 8000 on whatever host served the page: hardcoding
 * 127.0.0.1 breaks the moment the app is opened over a LAN address,
 * because 127.0.0.1 then means the visiting device, not the server.
 * On the server (no window) 127.0.0.1 is correct.
 */
function resolveApiUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://127.0.0.1:8000";
}

export const API_URL = resolveApiUrl();

export type DependencyStatus = { ok: boolean; detail: string | null };

export type Health = {
  status: "ok" | "degraded";
  version: string;
  dependencies: Record<string, DependencyStatus>;
};

export type RepoSummary = {
  owner: string;
  name: string;
  sha: string;
  status: string;
  files: number;
  chunks: number;
};

export type FileContent = { path: string; content: string; lines: number };

export type SymbolEntry = {
  name: string;
  kind: string;
  line: number;
  parent: string | null;
};

export type Orientation = {
  owner: string;
  name: string;
  sha: string;
  languages: Record<string, number>;
  entry_points: string[];
  key_files: string[];
  top_symbols: SymbolEntry[];
  readme: string | null;
  starter_questions: string[];
};

export type MessageEntry = {
  role: string;
  content: string;
  citations: string[];
};

export type IndexRun = {
  run_id: number;
  status: string;
  events_url: string;
};

export type Conversation = {
  conversation_id: number;
  repo: string;
  sha: string;
};

/** What a page renders when the API itself cannot be reached. */
export type HealthResult =
  | { reachable: true; health: Health }
  | { reachable: false; error: string };

async function getJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<HealthResult> {
  try {
    return { reachable: true, health: await getJSON<Health>("/health") };
  } catch (error) {
    return {
      reachable: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export const listRepos = () => getJSON<RepoSummary[]>("/repos");

export const fetchTree = (owner: string, name: string) =>
  getJSON<string[]>(`/repos/${owner}/${name}/tree`);

export const fetchFile = (owner: string, name: string, path: string) =>
  getJSON<FileContent>(
    `/repos/${owner}/${name}/file?path=${encodeURIComponent(path)}`,
  );

export const fetchSymbols = (owner: string, name: string, path?: string) =>
  getJSON<SymbolEntry[]>(
    `/repos/${owner}/${name}/symbols${
      path ? `?path=${encodeURIComponent(path)}` : ""
    }`,
  );

export const fetchOrientation = (owner: string, name: string) =>
  getJSON<Orientation>(`/repos/${owner}/${name}/orientation`);

export const fetchMessages = (conversationId: number) =>
  getJSON<MessageEntry[]>(`/conversations/${conversationId}/messages`);

export const startIndexing = (url: string) =>
  getJSON<IndexRun>("/index", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

export const startConversation = (repo: string) =>
  getJSON<Conversation>("/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo }),
  });

/** Parse "owner/name" out of a GitHub URL, for post-index navigation. */
export function repoSlug(url: string): string | null {
  const match = url
    .trim()
    .match(/^https:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?\/?$/);
  return match ? `${match[1]}/${match[2]}` : null;
}
