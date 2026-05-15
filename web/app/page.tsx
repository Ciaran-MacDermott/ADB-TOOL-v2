"use client";

import { useEffect, useState } from "react";
import {
  AppBar,
  AppShell,
  Badge,
  Button,
  ButtonLink,
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
  Chip,
  PageHeader,
  Spinner,
  Wordmark,
} from "@/kit";
import { api, type Industry, type Levels, type RunStatus } from "@/lib/api";

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;
const YEARS = Array.from({ length: 8 }, (_, i) => 2024 + i);

// ── Page persistence ──────────────────────────────────────────────────
// Stash {token, username, run_id} in localStorage so a Cmd+R during a
// 10–15 min run doesn't lose visibility. Backend keeps the session +
// run alive for 60 min idle, so we just need the client-side hooks.
const STORAGE_KEY = "adb_v2_session";
const STORAGE_TTL_MS = 20 * 60 * 1000;   // 20 minutes — user's spec

type StoredSession = {
  token:    string;
  username: string;
  run_id:   string | null;
  savedAt:  number;
};

function readStash(): StoredSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as StoredSession;
    if (!data?.token || Date.now() - data.savedAt > STORAGE_TTL_MS) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

function writeStash(data: StoredSession) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // localStorage quota / disabled — silent fail is fine.
  }
}

function clearStash() {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(STORAGE_KEY); } catch {}
}

const STATE_TONE: Record<RunStatus["state"], "info" | "success" | "warning" | "error" | "neutral"> = {
  queued:    "neutral",
  running:   "info",
  done:      "success",
  error:     "error",
  cancelled: "warning",
};

function formatEta(seconds: number): string {
  if (seconds < 90) return `~${Math.max(1, Math.round(seconds))}s`;
  const mins = Math.round(seconds / 60);
  return `~${mins} min`;
}

function formatElapsed(seconds: number): string {
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

export default function Home() {
  // ── Connect state ──────────────────────────────────────────────────────
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  // ── Run params ─────────────────────────────────────────────────────────
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [industry, setIndustry] = useState<string>("");
  const [year, setYear] = useState<number>(2026);
  const [quarter, setQuarter] = useState<typeof QUARTERS[number]>("Q1");
  const now = new Date();
  const defaultRelease = `${String(now.getMonth() + 1).padStart(2, "0")}/${now.getFullYear()}`;
  const [releaseDate, setReleaseDate] = useState<string>(defaultRelease);
  const [categoryOrder, setCategoryOrder] = useState<"sales_volume" | "alphabetical">("sales_volume");
  const [levels, setLevels] = useState<Levels | null>(null);
  const [loadingLevels, setLoadingLevels] = useState(false);
  const [level1Filter, setLevel1Filter] = useState<string>("");      // "" = All
  const [analysisLevel, setAnalysisLevel] = useState<string>("level2");

  // ── Run state ──────────────────────────────────────────────────────────
  const [run, setRun] = useState<RunStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [logsExpanded, setLogsExpanded] = useState(false);

  const connected = !!token;
  const selectedIndustry = industries.find((i) => i.slug === industry);
  const isFs = selectedIndustry?.pipeline === "fs";
  const inFlight = run?.state === "queued" || run?.state === "running";

  // Rehydrate session + in-flight run from localStorage on mount.
  // Validates the token by calling /api/industries — if the backend
  // rejected it (expired / restarted), clear the stash and show Connect.
  useEffect(() => {
    const stash = readStash();
    if (!stash) return;
    let cancelled = false;
    api.industries(stash.token)
      .then(() => {
        if (cancelled) return;
        setToken(stash.token);
        setUsername(stash.username);
        if (stash.run_id) {
          api.getRun(stash.token, stash.run_id)
            .then((r) => !cancelled && setRun(r))
            .catch(() => undefined);   // run was reaped — token still good
        }
      })
      .catch(() => clearStash());
    return () => { cancelled = true; };
  }, []);

  // Persist whenever the relevant pieces change.
  useEffect(() => {
    if (!token) {
      clearStash();
      return;
    }
    writeStash({
      token,
      username,
      run_id: run?.run_id ?? null,
      savedAt: Date.now(),
    });
  }, [token, username, run?.run_id]);

  // Load industries once we have a token.
  useEffect(() => {
    if (!token) {
      setIndustries([]);
      setIndustry("");
      setLevels(null);
      return;
    }
    api.industries(token)
      .then((rows) => {
        setIndustries(rows);
        if (rows[0]) setIndustry(rows[0].slug);
      })
      .catch((e) => setConnectError(String(e)));
  }, [token]);

  // Load level1 + analysis-level options when an ADB industry is picked.
  // Foodservice industries skip this step (the FS pipeline doesn't use them).
  useEffect(() => {
    if (!token || !industry) {
      setLevels(null);
      return;
    }
    if (isFs) {
      setLevels(null);
      setLevel1Filter("");
      setAnalysisLevel("level2");
      return;
    }
    setLoadingLevels(true);
    setLevels(null);
    api.levels(token, industry)
      .then((res) => {
        setLevels(res);
        // Default level1 filter to "All" (empty string).
        setLevel1Filter("");
        // Default analysis level to level2 if present, else first available.
        if (res.level_cols.includes("level2")) setAnalysisLevel("level2");
        else if (res.level_cols[0]) setAnalysisLevel(res.level_cols[0]);
      })
      .catch((e) => setRunError(`Could not load level options: ${e}`))
      .finally(() => setLoadingLevels(false));
  }, [token, industry, isFs]);

  // Poll run status while a run is in flight.
  useEffect(() => {
    if (!run || !token) return;
    if (run.state === "done" || run.state === "error" || run.state === "cancelled") return;
    const id = setInterval(async () => {
      try {
        const next = await api.getRun(token, run.run_id);
        setRun(next);
      } catch (e) {
        setRunError(String(e));
        clearInterval(id);
      }
    }, 1000);
    return () => clearInterval(id);
  }, [run, token]);

  async function onConnect() {
    setConnectError(null);
    setConnecting(true);
    try {
      const res = await api.connect(username, password);
      setToken(res.session_token);
    } catch (e) {
      setConnectError(e instanceof Error ? e.message : String(e));
    } finally {
      setConnecting(false);
    }
  }

  async function onDisconnect() {
    if (token) await api.disconnect(token).catch(() => undefined);
    clearStash();
    setToken(null);
    setRun(null);
    setRunError(null);
  }

  async function onRun() {
    if (!token) return;
    setRunError(null);
    setSubmitting(true);
    try {
      const { run_id } = await api.startRun(token, {
        industry,
        year,
        quarter,
        release_date: releaseDate,
        category_order: categoryOrder,
        level1_filter: isFs ? null : (level1Filter || null),
        analysis_level: isFs ? null : analysisLevel,
      });
      const initial = await api.getRun(token, run_id);
      setRun(initial);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancel() {
    if (!token || !run) return;
    setCancelling(true);
    try {
      await api.cancelRun(token, run.run_id);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  }

  return (
    <>
      <AppBar
        left={
          <a href="/" aria-label="Circana ADB — Accuracy Deck Builder home">
            <Wordmark prefix="ADB" tag="Accuracy Deck Builder" />
          </a>
        }
        right={
          connected ? (
            <>
              <Chip tone="success">Connected — {username || "session"}</Chip>
              <Button variant="ghost" onClick={onDisconnect}>Disconnect</Button>
            </>
          ) : (
            <Chip tone="neutral">Not connected</Chip>
          )
        }
      />

      <AppShell>
        <PageHeader
          eyebrow={
            <span className="inline-flex items-center gap-2">
              <img
                src="/Circana_logo.png"
                alt="Circana"
                className="h-4 w-auto opacity-80"
                draggable={false}
              />
              <span>Forecast accuracy</span>
            </span>
          }
          title="Generate a deck"
          subtitle="Connect via NPD credentials, pick the time periods, industry and required filters, and run Pipeline. You can view logs and download the deck after."
        />

        {/* ── Step 1: Connect (full width) ─────────────────────────────── */}
        <Card className="mb-5">
          <CardHeader>
            <CardTitle>1 — Connect to NPD</CardTitle>
            {connected
              ? <Badge tone="success">Authenticated</Badge>
              : <Badge tone="neutral">Required</Badge>}
          </CardHeader>
          <CardDescription>
            Live API mode. Industries and runs are scoped to your NPD session.
          </CardDescription>

          {!connected ? (
            <>
              <div className="mt-5 grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <Field label="NPD username">
                  <input
                    className={inputCls}
                    type="email"
                    autoComplete="username"
                    placeholder="your@email.com"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && username && password && onConnect()}
                  />
                </Field>
                <Field label="NPD password">
                  <input
                    className={inputCls}
                    type="password"
                    autoComplete="current-password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && username && password && onConnect()}
                  />
                </Field>
                <Button
                  variant="primary"
                  disabled={connecting || !username || !password}
                  onClick={onConnect}
                >
                  {connecting ? (
                    <span className="inline-flex items-center gap-2">
                      <Spinner size={14} /> Connecting…
                    </span>
                  ) : "Connect"}
                </Button>
              </div>
              {connectError && (
                <p className="mt-3 text-sm text-red-700">{connectError}</p>
              )}
            </>
          ) : (
            <p className="mt-3 text-sm text-zinc-600">
              Signed in as <strong>{username || "session"}</strong>. {industries.length} industries available.
            </p>
          )}
        </Card>

        {/* ── Step 2: Run params ──────────────────────────────────────── */}
        {runError && (
          <Card variant="quiet" className="mb-5 border-red-200 bg-red-50/60">
            <p className="text-sm text-red-800">{runError}</p>
          </Card>
        )}

        <Card aria-disabled={!connected} className={!connected ? "opacity-60 pointer-events-none" : ""}>
            <CardHeader>
              <CardTitle>2 — Run parameters</CardTitle>
              {selectedIndustry && (
                <Chip tone={isFs ? "info" : "neutral"}>
                  {isFs ? "Foodservice pipeline" : "ADB pipeline"}
                </Chip>
              )}
            </CardHeader>
            <CardDescription>
              Match the wave and release date to the dashboard release you want to report on.
              {isFs && " Level filters are skipped for the foodservice pipeline."}
            </CardDescription>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <Field label="Industry">
                <select
                  className={inputCls}
                  value={industry}
                  onChange={(e) => setIndustry(e.target.value)}
                  disabled={!connected}
                >
                  {industries.map((i) => (
                    <option key={i.slug} value={i.slug}>{i.label}</option>
                  ))}
                </select>
              </Field>

              <Field label="Accuracy year">
                <select className={inputCls} value={year} onChange={(e) => setYear(Number(e.target.value))} disabled={!connected}>
                  {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
              </Field>

              <Field label="Quarter">
                <select
                  className={inputCls}
                  value={quarter}
                  onChange={(e) => setQuarter(e.target.value as typeof QUARTERS[number])}
                  disabled={!connected}
                >
                  {QUARTERS.map((q) => <option key={q} value={q}>{q}</option>)}
                </select>
              </Field>

              <Field label="Release date (mm/yyyy)">
                <input
                  className={inputCls}
                  value={releaseDate}
                  onChange={(e) => setReleaseDate(e.target.value)}
                  placeholder="05/2026"
                  disabled={!connected}
                />
              </Field>

              <Field label="Category order">
                <select
                  className={inputCls}
                  value={categoryOrder}
                  onChange={(e) => setCategoryOrder(e.target.value as "sales_volume" | "alphabetical")}
                  disabled={!connected || isFs}
                >
                  <option value="sales_volume">Sales volume (recommended)</option>
                  <option value="alphabetical">Alphabetical</option>
                </select>
              </Field>

              <Field label="Level 1 filter">
                <select
                  className={inputCls}
                  value={level1Filter}
                  onChange={(e) => setLevel1Filter(e.target.value)}
                  disabled={!connected || isFs || loadingLevels || !levels}
                >
                  <option value="">
                    {isFs
                      ? "Not used for foodservice"
                      : loadingLevels
                      ? "Loading…"
                      : levels && levels.level1_options.length === 0
                      ? "No level1 values"
                      : levels && levels.level1_options.length === 1
                      ? levels.level1_options[0]
                      : "All"}
                  </option>
                  {!isFs && levels && levels.level1_options.length > 1 &&
                    levels.level1_options.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                </select>
              </Field>

              <Field label="Analysis granularity">
                <select
                  className={inputCls}
                  value={analysisLevel}
                  onChange={(e) => setAnalysisLevel(e.target.value)}
                  disabled={!connected || isFs || loadingLevels}
                >
                  {(levels?.level_cols && levels.level_cols.length > 0
                    ? levels.level_cols
                    : ["level2", "level3", "level4", "level5"]
                  ).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              {inFlight && (
                <Button
                  variant="ghost"
                  disabled={cancelling}
                  onClick={onCancel}
                >
                  {cancelling ? "Cancelling…" : "Cancel"}
                </Button>
              )}
              <Button
                variant="primary"
                disabled={!connected || submitting || !industry || inFlight}
                onClick={onRun}
              >
                {submitting ? "Starting…" : "Run pipeline"}
              </Button>
            </div>
        </Card>

        {/* ── Pipeline log (collapsed by default) ─────────────────────── */}
        {run && (
          <Card className="mt-5">
            <button
              type="button"
              onClick={() => setLogsExpanded((v) => !v)}
              className="flex w-full items-center justify-between gap-3 text-left"
              aria-expanded={logsExpanded}
            >
              <span className="inline-flex items-center gap-3">
                {inFlight && <Spinner size={16} className="text-brand-600" />}
                <span className="text-base font-semibold text-zinc-900">
                  Pipeline log
                </span>
                <Chip tone={STATE_TONE[run.state]}>
                  {run.step ?? run.state}
                </Chip>
              </span>
              <span className="inline-flex items-center gap-3 text-sm text-zinc-500">
                <span className="font-mono">{formatElapsed(run.elapsed_s)}</span>
                <span aria-hidden className={`transition-transform ${logsExpanded ? "rotate-180" : ""}`}>
                  ▾
                </span>
              </span>
            </button>
            {logsExpanded && (
              <pre className="mt-3 max-h-80 overflow-auto rounded-lg border border-zinc-200 bg-zinc-900 px-3 py-2 text-[12px] leading-relaxed text-zinc-100 whitespace-pre-wrap break-words">
                {run.logs.length > 0 ? run.logs.join("\n") : "Waiting for output…"}
              </pre>
            )}
            {!logsExpanded && run.message && (
              <p className="mt-2 text-sm text-zinc-500">{run.message}</p>
            )}
          </Card>
        )}

        {/* ── Run status + downloads (below logs) ─────────────────────── */}
        {run && (
          <Card variant="quiet" className="mt-5">
            <CardHeader>
              <CardTitle>Run status</CardTitle>
              <Badge tone={STATE_TONE[run.state]}>{run.state}</Badge>
            </CardHeader>
            <div className="mt-3 space-y-2 text-sm">
              <Row label="Run ID"  value={<code className="text-xs">{run.run_id}</code>} />
              {run.state === "queued" && run.queue_position != null && run.queue_depth != null && (
                <Row
                  label="Queue"
                  value={
                    <span>
                      Position {run.queue_position + 1} of {run.queue_depth}
                      {run.eta_seconds != null && (
                        <span className="text-zinc-500"> · ETA {formatEta(run.eta_seconds)}</span>
                      )}
                    </span>
                  }
                />
              )}
              <Row label="Step"    value={run.step ?? "—"} />
              <Row
                label="Elapsed"
                value={
                  <span className="inline-flex items-center gap-2 font-mono">
                    {inFlight && <Spinner size={12} className="text-brand-600" />}
                    {formatElapsed(run.elapsed_s)}
                  </span>
                }
              />
              {run.message && <Row label="Message" value={run.message} />}
            </div>
            {run.state === "done" && (
              <div className="mt-4 flex flex-wrap gap-2">
                <ButtonLink
                  variant="success"
                  href={api.downloadUrl(run.run_id)}
                  download
                  onClick={clearStash}
                >
                  Download deck (.pptx)
                </ButtonLink>
                {!isFs && (
                  <ButtonLink
                    variant="ghost"
                    href={api.downloadXlsxUrl(run.run_id)}
                    download
                    onClick={clearStash}
                  >
                    Download insights (.xlsx)
                  </ButtonLink>
                )}
              </div>
            )}
          </Card>
        )}
      </AppShell>
    </>
  );
}

const inputCls =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm " +
  "focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 " +
  "disabled:bg-zinc-50 disabled:text-zinc-400 transition-colors";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{label}</span>
      {children}
    </label>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{label}</span>
      <span className="text-zinc-900">{value}</span>
    </div>
  );
}
