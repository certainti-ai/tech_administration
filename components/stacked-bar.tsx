export interface StackSegment {
  key: string;
  label: string;
  value: number;
  /** A categorical slot, assigned in fixed order by the caller. */
  color: string;
}

/**
 * Part-to-whole across a small fixed set of classes: a single horizontal
 * stacked bar.
 *
 * Segments are separated by a 2px surface gap so adjacent fills never touch,
 * and the outer ends are rounded 4px against the baseline. Every segment is
 * also named and counted in the legend below, so identity never rests on colour
 * alone — which is what makes four slots safe here.
 */
export function StackedBar({
  segments,
  caption,
}: {
  segments: readonly StackSegment[];
  caption?: string;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const visible = segments.filter((segment) => segment.value > 0);

  return (
    <figure className="m-0">
      {total > 0 ? (
        <div className="flex h-3 w-full gap-[2px]">
          {visible.map((segment, index) => (
            <div
              key={segment.key}
              title={`${segment.label}: ${segment.value}`}
              style={{
                background: segment.color,
                flexGrow: segment.value,
                borderTopLeftRadius: index === 0 ? 4 : 0,
                borderBottomLeftRadius: index === 0 ? 4 : 0,
                borderTopRightRadius: index === visible.length - 1 ? 4 : 0,
                borderBottomRightRadius: index === visible.length - 1 ? 4 : 0,
              }}
            />
          ))}
        </div>
      ) : (
        <div className="h-3 w-full rounded bg-line" />
      )}

      <figcaption className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {segments.map((segment) => (
          <span key={segment.key} className="inline-flex items-center gap-2 text-sm">
            <span
              aria-hidden
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ background: segment.color }}
            />
            <span className="text-ink-2">{segment.label}</span>
            <span className="tabular font-medium text-ink">{segment.value}</span>
          </span>
        ))}
        {caption ? (
          <span className="w-full text-sm text-muted">{caption}</span>
        ) : null}
      </figcaption>
    </figure>
  );
}
