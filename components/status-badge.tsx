import type { Severity } from "@/lib/metrics";

/**
 * Status is never carried by colour alone: each severity gets a distinct icon
 * shape *and* a text label, so it survives colour-vision deficiency, greyscale
 * printing and forced-colors mode.
 */
const SEVERITY_STYLE: Record<Severity, { color: string; shape: Shape }> = {
  good: { color: "var(--good)", shape: "check" },
  warning: { color: "var(--warning)", shape: "triangle" },
  serious: { color: "var(--serious)", shape: "diamond" },
  critical: { color: "var(--critical)", shape: "octagon" },
};

type Shape = "check" | "triangle" | "diamond" | "octagon";

function SeverityIcon({ shape, color }: { shape: Shape; color: string }) {
  const common = { width: 14, height: 14, viewBox: "0 0 16 16", "aria-hidden": true } as const;

  switch (shape) {
    case "check":
      return (
        <svg {...common} fill="none" stroke={color} strokeWidth="2">
          <circle cx="8" cy="8" r="6.5" />
          <path d="M5 8.4l2 2 4-4.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "triangle":
      return (
        <svg {...common} fill="none" stroke={color} strokeWidth="1.8">
          <path d="M8 1.8l6.4 11.4H1.6z" strokeLinejoin="round" />
          <path d="M8 6v3.2" strokeLinecap="round" />
          <circle cx="8" cy="11.3" r="0.5" fill={color} stroke="none" />
        </svg>
      );
    case "diamond":
      return (
        <svg {...common} fill="none" stroke={color} strokeWidth="1.8">
          <path d="M8 1.3L14.7 8 8 14.7 1.3 8z" strokeLinejoin="round" />
          <path d="M8 5v3.4" strokeLinecap="round" />
          <circle cx="8" cy="10.7" r="0.5" fill={color} stroke="none" />
        </svg>
      );
    case "octagon":
      return (
        <svg {...common} fill="none" stroke={color} strokeWidth="1.8">
          <path d="M5.4 1.4h5.2L14.6 5.4v5.2l-4 4H5.4l-4-4V5.4z" strokeLinejoin="round" />
          <path d="M5.9 5.9l4.2 4.2M10.1 5.9l-4.2 4.2" strokeLinecap="round" />
        </svg>
      );
  }
}

export function StatusBadge({
  severity,
  label,
}: {
  severity: Severity;
  label: string;
}) {
  const { color, shape } = SEVERITY_STYLE[severity];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-ink-2">
      <SeverityIcon shape={shape} color={color} />
      {label}
    </span>
  );
}
