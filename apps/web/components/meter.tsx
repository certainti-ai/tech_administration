import { formatPercent } from "@/lib/format";

/**
 * A single ratio against a limit — a meter, not a two-slice pie.
 *
 * The fill is the sequential hue on a light step of its own ramp, so the track
 * recedes. Urgency is deliberately *not* encoded here: status colours are
 * reserved, and the caller pairs this with a `StatusBadge` so the state carries
 * an icon and a label rather than a hue.
 */
export function Meter({
  used,
  total,
  label,
}: {
  used: number;
  total: number;
  label?: string;
}) {
  const ratio = total > 0 ? used / total : 0;
  const clamped = Math.max(0, Math.min(1, ratio));
  const accessibleLabel = label ?? `${used} of ${total} used`;

  return (
    <div className="min-w-32">
      <div
        role="meter"
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={accessibleLabel}
        className="h-2 w-full overflow-hidden rounded"
        style={{ background: "var(--seq-track)" }}
      >
        <div
          className="h-full rounded"
          style={{
            width: `${clamped * 100}%`,
            background: "var(--seq-fill)",
          }}
        />
      </div>
      <div className="tabular mt-1 text-sm text-ink-2">
        {used} / {total}
        <span className="text-muted"> ({formatPercent(ratio)})</span>
      </div>
    </div>
  );
}
