export const pct = (v: number | null, digits = 2): string =>
  v === null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(digits)}%`;

export const money = (v: number | null): string =>
  v === null || Number.isNaN(v) ? "—" : `$${v.toFixed(2)}`;

export const num = (v: number | null): string =>
  v === null || Number.isNaN(v) ? "—" : String(v);

export type Tone = "pos" | "neg" | "info" | "muted";

/** Sign-based tone: positive green, negative red, otherwise neutral. */
export const toneForSigned = (v: number | null): Tone =>
  v === null ? "muted" : v > 0 ? "pos" : v < 0 ? "neg" : "muted";
