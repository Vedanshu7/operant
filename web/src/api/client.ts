import { getToken, redirectToLogin } from "@/lib/auth";

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function buildUrl(path: string, query?: Query): string {
  const url = new URL(API_BASE + path, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    }
  }
  return url.pathname + url.search;
}

async function extractDetail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail: unknown = parsed.detail;
      return typeof detail === "string" ? detail : JSON.stringify(detail);
    }
  } catch {
    // not JSON
  }
  return text || res.statusText;
}

export async function fetchRaw(path: string, opts: RequestOptions = {}): Promise<Response> {
  const headers: Record<string, string> = { ...authHeaders() };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });
  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) throw new ApiError(res.status, await extractDetail(res));
  return res;
}

export async function fetchJson<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await fetchRaw(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function fetchText(path: string, opts: RequestOptions = {}): Promise<string> {
  const res = await fetchRaw(path, opts);
  return res.text();
}
