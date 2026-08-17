/**
 * Money is carried through the app in minor units (paise/cents) as integers, so
 * it only becomes a decimal at the point of display.
 */
export function formatMoneyMinor(
  amountMinor: number,
  currency: string,
  { compact = false }: { compact?: boolean } = {},
): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 1 : 0,
  }).format(amountMinor / 100);
}

export function formatPercent(ratio: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "percent",
    maximumFractionDigits: 0,
  }).format(ratio);
}

/** Turn a snake_case enum member into display text, e.g. `in_use` → `In use`. */
export function humanize(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
