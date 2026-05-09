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
} from "@/kit";
import { api, type Industry, type RunStatus } from "@/lib/api";

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;
const YEARS = Array.from({ length: 8 }, (_, i) => 2024 + i);

const STATE_TONE: Record<RunStatus["state"], "info" | "success" | "warning" | "error" | "neutral"> = {
  pending:   "neutral",
  running:   "info",
  done:      "success",
  error:     "error",
  cancelled: "warning",
};

export default function Home() {
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [industry, setIndustry] = useState<string>("");
  const [year, setYear] = useState<number>(2026);
  const [quarter, setQuarter] = useState<typeof QUARTERS[number]>("Q1");
  const now = new Date();
  const defaultRelease = `${String(now.getMonth() + 1).padStart(2, "0")}/${now.getFullYear()}`;
  const [releaseDate, setReleaseDate] = useState<string>(defaultRelease);
  const [insightMode, setInsightMode] = useState<"direct" | "traditional">("direct");
  const [categoryOrder, setCategoryOrder] = useState<"sales_volume" | "alphabetical">("sales_volume");

  const [run, setRun] = useState<RunStatus | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.industries()
      .then((rows) => {
        setIndustries(rows);
        if (rows[0]) setIndustry(rows[0].slug);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!run || run.state === "done" || run.state === "error" || run.state === "cancelled") return;
    const id = setInterval(async () => {
      try {
        const next = await api.getRun(run.run_id);
        setRun(next);
      } catch (e) {
        setError(String(e));
        clearInterval(id);
      }
    }, 1000);
    return () => clearInterval(id);
  }, [run]);

  async function onRun() {
    setError(null);
    setSubmitting(true);
    try {
      const { run_id } = await api.startRun({
        industry,
        year,
        quarter,
        release_date: releaseDate,
        insight_mode: insightMode,
        category_order: categoryOrder,
      });
      const initial = await api.getRun(run_id);
      setRun(initial);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <AppBar
        left={
          <a href="/" className="flex items-center gap-3" aria-label="Circana home">
            <span className="text-[19px] font-semibold tracking-tight text-brand-700">Circana</span>
            <span className="text-zinc-300">/</span>
            <span className="text-[19px] font-semibold tracking-tight">Deck Builder</span>
          </a>
        }
      />

      <AppShell>
        <PageHeader
          eyebrow="Forecast accuracy"
          title="Generate a deck"
          subtitle="Pull the latest forecast vs actuals from the NPD Future of dashboard and produce a Circana-branded PowerPoint."
        />

        {error && (
          <Card variant="quiet" className="mb-6 border-red-200 bg-red-50/60">
            <p className="text-sm text-red-800">{error}</p>
          </Card>
        )}

        <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
          <Card>
            <CardHeader>
              <CardTitle>Run parameters</CardTitle>
              <Chip tone="info">Required</Chip>
            </CardHeader>
            <CardDescription>
              Match the wave and release date to the dashboard release you want to report on.
            </CardDescription>

            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <Field label="Industry">
                <select className={selectCls} value={industry} onChange={(e) => setIndustry(e.target.value)}>
                  {industries.map((i) => <option key={i.slug} value={i.slug}>{i.label}</option>)}
                </select>
              </Field>

              <Field label="Accuracy year">
                <select className={selectCls} value={year} onChange={(e) => setYear(Number(e.target.value))}>
                  {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
              </Field>

              <Field label="Quarter">
                <select
                  className={selectCls}
                  value={quarter}
                  onChange={(e) => setQuarter(e.target.value as typeof QUARTERS[number])}
                >
                  {QUARTERS.map((q) => <option key={q} value={q}>{q}</option>)}
                </select>
              </Field>

              <Field label="Release date (mm/yyyy)">
                <input
                  className={selectCls}
                  value={releaseDate}
                  onChange={(e) => setReleaseDate(e.target.value)}
                  placeholder="05/2026"
                />
              </Field>

              <Field label="Category order">
                <select
                  className={selectCls}
                  value={categoryOrder}
                  onChange={(e) => setCategoryOrder(e.target.value as "sales_volume" | "alphabetical")}
                >
                  <option value="sales_volume">Sales volume (recommended)</option>
                  <option value="alphabetical">Alphabetical</option>
                </select>
              </Field>

              <Field label="Insight mode">
                <select
                  className={selectCls}
                  value={insightMode}
                  onChange={(e) => setInsightMode(e.target.value as "direct" | "traditional")}
                >
                  <option value="direct">Direct (recommended)</option>
                  <option value="traditional">Traditional</option>
                </select>
              </Field>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <Button
                variant="primary"
                disabled={submitting || !industry || run?.state === "running"}
                onClick={onRun}
              >
                {submitting ? "Starting…" : "Run pipeline"}
              </Button>
            </div>
          </Card>

          <Card variant="quiet">
            <CardHeader>
              <CardTitle>Run status</CardTitle>
              {run && <Badge tone={STATE_TONE[run.state]}>{run.state}</Badge>}
            </CardHeader>
            {!run ? (
              <CardDescription>No run yet. Submit the form to start.</CardDescription>
            ) : (
              <div className="space-y-2 text-sm">
                <Row label="Run ID"  value={<code className="text-xs">{run.run_id}</code>} />
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
      </AppShell>
    </>
  );
}

const selectCls =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm " +
  "focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 transition-colors";

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
