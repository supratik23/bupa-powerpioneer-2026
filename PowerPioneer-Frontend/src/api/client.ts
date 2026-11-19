/**
 * Thin fetch wrapper around the PowerPioneer REST API.
 *
 * - Pages pass PARTIAL urls ("/leave-requests/"); the base URL comes from ./config.
 * - Adds the JWT access token, refreshes it once on 401, and retries the request.
 * - Normalises DRF error bodies into a readable message (ApiError.message).
 */
import { AGENT_BASE_URL, apiUrl } from "./config";
import type { AgentStreamEvent, Paginated } from "./types";

const ACCESS_KEY = "pp.access";
const REFRESH_KEY = "pp.refresh";

// ---------------------------------------------------------------------------
// token storage
// ---------------------------------------------------------------------------
function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: tokens stay in memory only */
  }
}

let accessToken: string | null = safeGet(ACCESS_KEY);
let refreshToken: string | null = safeGet(REFRESH_KEY);

type Listener = () => void;
const sessionExpiredListeners = new Set<Listener>();

export const tokens = {
  get access() {
    return accessToken;
  },
  get refresh() {
    return refreshToken;
  },
  set(access: string | null, refresh?: string | null) {
    accessToken = access;
    safeSet(ACCESS_KEY, access);
    if (refresh !== undefined) {
      refreshToken = refresh;
      safeSet(REFRESH_KEY, refresh);
    }
  },
  clear() {
    this.set(null, null);
  },
  /** Called when the refresh token is rejected and the user must log in again. */
  onSessionExpired(listener: Listener) {
    sessionExpiredListeners.add(listener);
    return () => {
      sessionExpiredListeners.delete(listener);
    };
  },
};

/** Seconds until the access token expires (negative when already expired). */
function accessSecondsLeft(): number {
  if (!accessToken) return -1;
  try {
    const payload = JSON.parse(atob(accessToken.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return payload.exp - Date.now() / 1000;
  } catch {
    return -1;
  }
}

// ---------------------------------------------------------------------------
// errors
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, data: unknown, fallback: string) {
    super(formatErrorBody(data) || fallback);
    this.status = status;
    this.data = data;
  }
}

const humanise = (key: string) =>
  key === "non_field_errors" || key === "detail" ? "" : `${key.replace(/_/g, " ")}: `;

function formatErrorBody(data: unknown): string {
  if (!data) return "";
  if (typeof data === "string") return data;
  if (Array.isArray(data)) return data.map(formatErrorBody).filter(Boolean).join(" ");
  if (typeof data === "object") {
    return Object.entries(data as Record<string, unknown>)
      .map(([key, value]) => `${humanise(key)}${formatErrorBody(value)}`)
      .join(" ");
  }
  return String(data);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) {
    return "Cannot reach the server. Check that the backend is running and the API base URL is correct.";
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

// ---------------------------------------------------------------------------
// token refresh (single flight)
// ---------------------------------------------------------------------------
let refreshing: Promise<boolean> | null = null;

export function refreshAccessToken(): Promise<boolean> {
  if (!refreshToken) return Promise.resolve(false);
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(apiUrl("/auth/token/refresh/"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh: refreshToken }),
        });
        if (!res.ok) return false;
        const body = (await res.json()) as { access: string; refresh?: string };
        // Refresh tokens rotate, so keep the new one when the server sends it.
        tokens.set(body.access, body.refresh ?? refreshToken);
        return true;
      } catch {
        return false;
      } finally {
        window.setTimeout(() => {
          refreshing = null;
        }, 0);
      }
    })();
  }
  return refreshing;
}

/** Returns a valid access token, refreshing it first if it is (nearly) expired. */
export async function getFreshAccessToken(): Promise<string | null> {
  if (accessSecondsLeft() < 30) {
    const ok = await refreshAccessToken();
    if (!ok) return null;
  }
  return accessToken;
}

// ---------------------------------------------------------------------------
// request
// ---------------------------------------------------------------------------
export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  /** Skip the Authorization header (login, register, refresh). */
  anonymous?: boolean;
  /** Absolute base URL for a service other than the Django API (e.g. the AI agent). */
  baseUrl?: string;
}

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.append(key, String(value));
  });
  const qs = params.toString();
  if (!qs) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${qs}`;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!options.anonymous && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  const url = options.baseUrl
    ? `${options.baseUrl}${path.startsWith("/") ? path : `/${path}`}`
    : apiUrl(path);
  return fetch(withQuery(url, options.query), {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let res = await send(path, options);

  if (res.status === 401 && !options.anonymous && refreshToken) {
    if (await refreshAccessToken()) {
      res = await send(path, options);
    } else {
      tokens.clear();
      sessionExpiredListeners.forEach((listener) => listener());
    }
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) throw new ApiError(res.status, data, `Request failed (${res.status})`);
  return data as T;
}

/**
 * Calls to the ShiftGuard AI agent. Same JWT as the Django API (the agent verifies it with /auth/me/),
 * including the refresh-on-401 retry.
 */
export const agentApi = {
  get: <T>(path: string, query?: Query) => request<T>(path, { query, baseUrl: AGENT_BASE_URL }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ?? {}, baseUrl: AGENT_BASE_URL }),
};

/**
 * POST {agent}/agent/stream and call onEvent for every Server-Sent Event (steps, tokens, approval, answer).
 * EventSource can't POST or send headers, so this reads the fetch body stream. Refreshes the token once on 401.
 */
export async function agentStream(
  body: { session_id: string; query?: string; resume?: { approved: boolean; comment?: string } },
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const post = async () =>
    fetch(`${AGENT_BASE_URL}/agent/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({ organization_name: "Bupa", ...body }),
      signal,
    });

  let res = await post();
  if (res.status === 401 && refreshToken && (await refreshAccessToken())) res = await post();
  if (!res.ok || !res.body) {
    const text = await res.text();
    let data: unknown = text;
    try {
      data = JSON.parse(text);
    } catch {
      /* plain text */
    }
    throw new ApiError(res.status, data, `Assistant request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (!data) continue;
      try {
        onEvent(JSON.parse(data) as AgentStreamEvent);
      } catch {
        /* ignore a malformed frame */
      }
    }
  }
}

/** Accepts either a paginated DRF response or a plain array. */
export function unwrap<T>(data: Paginated<T> | T[]): T[] {
  return Array.isArray(data) ? data : data.results;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown, extra?: Partial<RequestOptions>) =>
    request<T>(path, { method: "POST", body: body ?? {}, ...extra }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),

  /** GET a list endpoint and return the items (first page only). */
  list: async <T>(path: string, query?: Query) => unwrap(await request<Paginated<T> | T[]>(path, { query })),

  /**
   * GET every page of a paginated list endpoint. Page 1 gives the total count;
   * the remaining pages are then fetched in parallel (a few at a time).
   */
  listAll: async <T>(path: string, query?: Query, maxPages = 80): Promise<T[]> => {
    const first = await request<Paginated<T> | T[]>(path, { query: { ...query, page: 1 } });
    if (Array.isArray(first)) return first;
    if (!first.next || first.results.length === 0) return first.results;
    const pages = Math.min(maxPages, Math.ceil(first.count / first.results.length));
    const rest: T[][] = new Array(Math.max(0, pages - 1));
    const CONCURRENCY = 6;
    let nextPage = 2;
    const worker = async () => {
      while (nextPage <= pages) {
        const page = nextPage++;
        const data = await request<Paginated<T>>(path, { query: { ...query, page } });
        rest[page - 2] = data.results;
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, pages - 1) }, worker));
    return first.results.concat(...rest);
  },
};
