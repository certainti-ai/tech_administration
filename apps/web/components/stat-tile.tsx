/**
 * A headline number. A single current value is a stat tile, not a one-bar chart
 * — there is no plot here, so there is nothing to hover.
 *
 * The value uses proportional figures (it stands alone); only columns that must
 * align vertically get `tabular-nums`.
 */
export function StatTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <div className="text-sm text-ink-2">{label}</div>
      <div className="mt-1 text-3xl font-semibold tracking-tight">{value}</div>
      {detail ? <div className="mt-1 text-sm text-muted">{detail}</div> : null}
    </div>
  );
}

export function StatRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
  );
}
