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
  Wordmark,
} from "@/kit";
import { api, type Industry, type RunStatus } from "@/lib/api";

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;
const YEARS = Array.from({ length: 8 }, (_, i) => 2024 + i);

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

  // ── Run state ──────────────────────────────────────────────────────────
  const [run, setRun] = useState<RunStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const connected = !!token;
  const selectedIndustry = industries.find((i) => i.slug === industry);
  const isFs = selectedIndustry?.pipeline === "fs";

  // Load industries once we have a token.
  useEffect(() => {
    if (!token) {
      setIndustries([]);
      setIndustry("");
      return;
    }
    api.industries(token)
      .then((rows) => {
        setIndustries(rows);
        if (rows[0]) setIndustry(rows[0].slug);
      })
      .catch((e) => setConnectError(String(e)));
  }, [token]);

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
      });
      const initial = await api.getRun(token, run_id);
      setRun(initial);
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppBar
        left={
          <a href="/" aria-label="Circana — Deck Builder home">
            <Wordmark tag="Deck Builder" />
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
          subtitle="Connect to NPD, pick the wave and industry, and produce a Circana-branded PowerPoint."
        />

        {/* ── Step 1: Connect (left)  +  Run status (top-right) ───────── */}
        <div className="mb-5 grid grid-cols-12 gap-5">
          <Card className="col-span-12 sm:col-span-9">
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
                    {connecting ? "Connecting…" : "Connect"}
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

          <Card variant="quiet" className="col-span-12 sm:col-span-3">
            <CardHeader>
              <CardTitle>Run status</CardTitle>
              {run && <Badge tone={STATE_TONE[run.state]}>{run.state}</Badge>}
            </CardHeader>
            {!run ? (
              <CardDescription>
                {connected ? "No run yet. Submit the form to start." : "Connect to NPD to begin."}
              </CardDescription>
            ) : (
              <div className="space-y-2 text-sm">
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
                <Row label="Elapsed" value={`${run.elapsed_s.toFixed(1)}s`} />
                {run.message && <Row label="Message" value={run.message} />}
                {run.state === "done" && (
                  <ButtonLink
                    variant="success"
                    href={api.downloadUrl(run.run_id)}
                    download
                    className="mt-3 w-full"
                  >
                    Download deck (.pptx)
                  </ButtonLink>
                )}
              </div>
            )}
          </Card>
        </div>

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
                  disabled={!connected}
                >
                  <option value="sales_volume">Sales volume (recommended)</option>
                  <option value="alphabetical">Alphabetical</option>
                </select>
              </Field>

            </div>

            <div className="mt-6 flex justify-end gap-2">
              <Button
                variant="primary"
                disabled={!connected || submitting || !industry || run?.state === "queued" || run?.state === "running"}
                onClick={onRun}
              >
                {submitting ? "Starting…" : "Run pipeline"}
              </Button>
            </div>
        </Card>
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
