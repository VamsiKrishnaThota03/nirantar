/** Indian-convention number formatting.
 *
 * Rupee amounts use the lakh/crore grouping, because a dashboard for Indian
 * health administrators that prints "1,800,000" is asking its reader to do
 * arithmetic the software should have done.
 */

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr1 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });

export const n = (value: number) => inr.format(Math.round(value));
export const n1 = (value: number) => inr1.format(value);

export const rupees = (value: number) => `₹${inr.format(Math.round(value))}`;

/** Compact rupees in the units Indian budgets are actually discussed in. */
export function rupeesCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e7) return `₹${inr1.format(value / 1e7)} cr`;
  if (abs >= 1e5) return `₹${inr1.format(value / 1e5)} lakh`;
  if (abs >= 1e3) return `₹${inr.format(Math.round(value / 1e3))}k`;
  return `₹${inr.format(Math.round(value))}`;
}

export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${inr1.format(value / 1e7)} cr`;
  if (abs >= 1e5) return `${inr1.format(value / 1e5)} lakh`;
  if (abs >= 1e3) return `${inr1.format(value / 1e3)}k`;
  return inr.format(value);
}

export const pct = (value: number, digits = 0) =>
  `${(value * 100).toFixed(digits)}%`;

export function dateShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

export function dateFull(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function overdueLabel(days: number): string {
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "due today";
  return `${days}d left`;
}

export const titleCase = (value: string) =>
  value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());

/** Ten ordinal-safe steps of the single-hue blue ramp, light to dark. */
export const SEQ_STEPS = [
  "var(--seq-250)",
  "var(--seq-300)",
  "var(--seq-350)",
  "var(--seq-400)",
  "var(--seq-450)",
  "var(--seq-500)",
  "var(--seq-550)",
  "var(--seq-600)",
  "var(--seq-650)",
  "var(--seq-700)",
];

/** Map a value onto the sequential ramp. */
export function seqColor(value: number, max: number, steps = SEQ_STEPS): string {
  if (max <= 0) return steps[0];
  const ratio = Math.min(1, Math.max(0, value / max));
  const index = Math.min(steps.length - 1, Math.round(ratio * (steps.length - 1)));
  return steps[index];
}

/** Readable ink for a label sitting inside a sequential fill.
 *
 * Returns a CSS variable rather than a literal, because the ramp's direction
 * flips between modes: in light mode the top of the scale is a dark blue and
 * wants white text, while in dark mode the top of the scale is a light blue
 * and wants near-black. Hard-coding white here produced white-on-pale-blue
 * tiles in dark mode.
 */
export function inkOn(value: number, max: number): string {
  const ratio = max <= 0 ? 0 : Math.min(1, value / max);
  return ratio > 0.42 ? "var(--ink-on-high)" : "var(--ink-on-low)";
}

export function nice(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const normalised = max / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}
