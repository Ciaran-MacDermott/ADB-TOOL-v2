// Thin client for the FastAPI BFF.
// In dev Next runs on :3000 and the API on :8000. In prod they share an origin.

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

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
  insight_mode?: "direct" | "traditional";
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

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  industries: () => fetch(`${BASE}/api/industries`).then(json<Industry[]>),

  startRun: (body: RunRequest) =>
    fetch(`${BASE}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ run_id: string }>),

  getRun: (runId: string) =>
    fetch(`${BASE}/api/runs/${runId}`).then(json<RunStatus>),

  downloadUrl: (runId: string) => `${BASE}/api/runs/${runId}/download`,
};
