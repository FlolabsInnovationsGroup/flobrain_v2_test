import { cn } from "@/lib/utils";

/** Page title, one plain sentence about the page, and its main action on the end side. */
export function PageHeader({ title, intro, action }: { title: string; intro?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {intro ? <p className="mt-1 text-[color:var(--fb-v2-text-muted)]">{intro}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="mb-8">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A list of rows separated by hairlines; rows are the default shape for records here. */
export function Rows({ children }: { children: React.ReactNode }) {
  return <ul className="divide-y divide-[color:var(--fb-v2-border)] rounded-xl bg-[color:var(--fb-v2-surface)]">{children}</ul>;
}

export function Row({ children, className }: { children: React.ReactNode; className?: string }) {
  return <li className={cn("flex flex-wrap items-center justify-between gap-3 px-4 py-3", className)}>{children}</li>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="mb-4 block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[color:var(--fb-v2-text-muted)]">{hint}</span> : null}
    </label>
  );
}

type Tone = "neutral" | "waiting" | "good" | "bad" | "accent";
const tones: Record<Tone, string> = {
  neutral: "bg-[color:var(--fb-v2-border)] text-[color:var(--fb-v2-text)]",
  waiting: "bg-[color:var(--fb-v2-waiting)] text-black",
  good: "bg-[color:var(--fb-v2-success)] text-black",
  bad: "bg-[color:var(--fb-v2-error)] text-black",
  accent: "bg-[color:var(--fb-v2-accent)] text-white",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span
      aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-[color:var(--fb-v2-accent)] font-semibold text-white"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {initials || "?"}
    </span>
  );
}

/** Inline result of an action: what happened, or what went wrong and how to fix it. */
export function Notice({ kind = "info", children }: { kind?: "info" | "error" | "ok"; children: React.ReactNode }) {
  const color = kind === "error" ? "var(--fb-v2-error)" : kind === "ok" ? "var(--fb-v2-success)" : "var(--fb-v2-text-muted)";
  return (
    <p role={kind === "error" ? "alert" : "status"} className="my-2 text-sm" style={{ color }}>
      {children}
    </p>
  );
}

export function when(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
