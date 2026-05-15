// Thin client for the FastAPI BFF.
// In dev Next runs on :3002 and the API on :8002. In prod they share an origin.

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8002";

// ── Types ────────────────────────────────────────────────────────────────
export type ConnectResponse = {
  session_token: string;
  username:      string;
  expires_at:    number;
};

export type Industry = {
  slug: string;
  label: string;
  pipeline: "adb" | "fs";
};

export type RunRequest = {
  industry: string;
  year: number;
  quarter: "Q1" | "Q2" | "Q3" | "Q4";
  release_date: string;
  category_order?: "sales_volume" | "alphabetical";
  level1_filter?: string;
  analysis_level?: string;
  npd_username?: string;
  npd_password?: string;
};

export type RunStatus = {
  run_id: string;
  state: "pending" | "running" | "done" | "error" | "cancelled";
  step?: string | null;
  message?: string | null;
  elapsed_s: number;
};

// ── Helpers ──────────────────────────────────────────────────────────────
function authHeaders(token: string | null): HeadersInit {
  return token ? { "X-Session-Token": token } : {};
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: string;
    try {
      const body = await res.json();
      detail = body.detail ?? `${res.status} ${res.statusText}`;
    } catch {
      detail = `${res.status} ${res.statusText}`;
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ── Endpoints ────────────────────────────────────────────────────────────
export const api = {
  connect: (username: string, password: string) =>
    fetch(`${BASE}/api/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).then(json<ConnectResponse>),

  disconnect: (token: string) =>
    fetch(`${BASE}/api/disconnect`, {
      method: "POST",
      headers: authHeaders(token),
    }),

  industries: (token: string) =>
    fetch(`${BASE}/api/industries`, { headers: authHeaders(token) })
      .then(json<Industry[]>),

  startRun: (token: string, body: RunRequest) =>
    fetch(`${BASE}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders(token) },
      body: JSON.stringify(body),
    }).then(json<{ run_id: string }>),

  getRun: (token: string, runId: string) =>
    fetch(`${BASE}/api/runs/${runId}`, { headers: authHeaders(token) })
      .then(json<RunStatus>),

  downloadUrl: (runId: string) => `${BASE}/api/runs/${runId}/download`,
};
