// Generated from ~/Downloads/kit — do not edit directly. Edit the canonical file and re-run kit/sync.sh.
// Barrel export for the Circana kit. Local imports inside <app>/web/kit/.
// Add new components here so app code can import them from "@/kit".

export { cn } from "./lib/cn";

// ── UI primitives ──────────────────────────────────────────────────────
export { Button, ButtonLink } from "./components/ui/Button";
export type { ButtonVariant } from "./components/ui/Button";

export { Card, CardHeader, CardTitle, CardDescription } from "./components/ui/Card";

export { Badge } from "./components/ui/Badge";
export type { BadgeTone } from "./components/ui/Badge";

export { Chip } from "./components/ui/Chip";
export type { ChipTone } from "./components/ui/Chip";

export { Spinner } from "./components/ui/Spinner";

export { SegmentedControl } from "./components/ui/SegmentedControl";
export type { SegmentOption } from "./components/ui/SegmentedControl";

export { Table } from "./components/ui/Table";
export type { TableColumn } from "./components/ui/Table";

// ── Layout ─────────────────────────────────────────────────────────────
export { AppShell }   from "./components/layout/AppShell";
export { AppBar }     from "./components/layout/AppBar";
export { AppHeader }  from "./components/layout/AppHeader";
export { PageHeader } from "./components/layout/PageHeader";
export { Wordmark }   from "./components/layout/Wordmark";
export { NavTabs }    from "./components/layout/NavTabs";
export type { NavItem } from "./components/layout/NavTabs";

// ── Forms ──────────────────────────────────────────────────────────────
export { Field }    from "./components/forms/Field";
export { Input }    from "./components/forms/Input";
export { Select }   from "./components/forms/Select";
export type { SelectOption } from "./components/forms/Select";
export { Checkbox } from "./components/forms/Checkbox";
export { Textarea } from "./components/forms/Textarea";
export { Row }      from "./components/forms/Row";
export { FileSlot } from "./components/forms/FileSlot";

// ── Feedback ───────────────────────────────────────────────────────────
export { EmptyState }     from "./components/feedback/EmptyState";
export { Disclosure }     from "./components/feedback/Disclosure";
export type { DisclosureTone } from "./components/feedback/Disclosure";
export { Modal }          from "./components/feedback/Modal";
export { ProgressBar }    from "./components/feedback/ProgressBar";
export { ProgressPanel }  from "./components/feedback/ProgressPanel";
export type { ProgressState } from "./components/feedback/ProgressPanel";
export { StageStepper }   from "./components/feedback/StageStepper";
export type { StepperStep } from "./components/feedback/StageStepper";
export { RunErrorDialog } from "./components/feedback/RunErrorDialog";
export type { RunErrorEnvelope, ErrorCategory } from "./components/feedback/RunErrorDialog";