import type { Tone } from "@/lib/format";

const toneClass: Record<Tone, string> = {
  pos: "text-pos",
  neg: "text-neg",
  info: "text-info",
  muted: "text-muted",
};

export function StatCard({
  label,
  value,
  tone = "muted",
  hint,
}: {
  label: string;
  value: string;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-panel p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass[tone]}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}
    </div>
  );
}
