import type { ReactNode } from "react";

export function Panel({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
        <div>
          <h2 className="font-medium tracking-tight">{title}</h2>
          {description ? (
            <p className="mt-0.5 text-sm text-muted">{description}</p>
          ) : null}
        </div>
        {action}
      </div>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

export function Table({
  headers,
  children,
}: {
  headers: readonly string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-left">
            {headers.map((header) => (
              <th
                key={header}
                scope="col"
                className="px-2 py-2 font-medium text-ink-2"
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <tr className="border-b border-line last:border-0">{children}</tr>;
}

export function Cell({
  children,
  numeric = false,
  muted = false,
}: {
  children: ReactNode;
  numeric?: boolean;
  muted?: boolean;
}) {
  return (
    <td
      className={[
        "px-2 py-2.5 align-middle",
        numeric ? "tabular" : "",
        muted ? "text-ink-2" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </td>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}
