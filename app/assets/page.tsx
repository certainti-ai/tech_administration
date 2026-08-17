import Link from "next/link";
import { Panel, Table, Row, Cell, EmptyState } from "@/components/table";
import { StatusBadge } from "@/components/status-badge";
import { describeDayOffset, daysUntil, formatIsoDate } from "@/lib/dates";
import { humanize } from "@/lib/format";
import { assetStatusOrder, warrantySeverity } from "@/lib/metrics";
import { store } from "@/lib/store";
import type { AssetStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

function parseStatus(value: string | string[] | undefined): AssetStatus | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  const statuses = assetStatusOrder();
  return statuses.find((status) => status === candidate) ?? null;
}

export default async function AssetsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const activeStatus = parseStatus(params.status);
  const today = new Date();

  const assets = store
    .listAssets()
    .filter((asset) => activeStatus === null || asset.status === activeStatus);

  const filters = [
    { label: "All", href: "/assets", active: activeStatus === null },
    ...assetStatusOrder().map((status) => ({
      label: humanize(status),
      href: `/assets?status=${status}`,
      active: activeStatus === status,
    })),
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Assets</h1>
        <p className="mt-1 text-sm text-muted">
          Hardware inventory, who holds it, and how long it stays under warranty.
        </p>
      </div>

      {/* Filters sit in one row above the content they filter. */}
      <nav aria-label="Filter by status" className="flex flex-wrap gap-2">
        {filters.map((filter) => (
          <Link
            key={filter.href}
            href={filter.href}
            aria-current={filter.active ? "true" : undefined}
            className={[
              "rounded-full border px-3 py-1 text-sm transition-colors",
              filter.active
                ? "border-transparent bg-ink text-page"
                : "border-line text-ink-2 hover:text-ink",
            ].join(" ")}
          >
            {filter.label}
          </Link>
        ))}
      </nav>

      <Panel
        title={activeStatus ? `${humanize(activeStatus)} assets` : "All assets"}
        description={`${assets.length} ${assets.length === 1 ? "asset" : "assets"}`}
      >
        {assets.length === 0 ? (
          <EmptyState>No assets match this filter.</EmptyState>
        ) : (
          <Table
            headers={[
              "Tag",
              "Type",
              "Model",
              "Serial",
              "Status",
              "Assigned to",
              "Warranty",
            ]}
          >
            {assets.map((asset) => {
              const remaining = daysUntil(asset.warrantyEndDate, today);
              return (
                <Row key={asset.id}>
                  <Cell>
                    <span className="font-medium">{asset.tag}</span>
                  </Cell>
                  <Cell muted>{humanize(asset.type)}</Cell>
                  <Cell>{asset.model}</Cell>
                  <Cell numeric muted>
                    {asset.serialNumber}
                  </Cell>
                  <Cell muted>{humanize(asset.status)}</Cell>
                  <Cell muted>{store.personName(asset.assignedToId)}</Cell>
                  <Cell>
                    {asset.status === "retired" ? (
                      <span className="text-sm text-muted">—</span>
                    ) : (
                      <span className="flex flex-col gap-0.5">
                        <StatusBadge
                          severity={warrantySeverity(remaining)}
                          label={describeDayOffset(remaining)}
                        />
                        <span className="tabular text-sm text-muted">
                          {formatIsoDate(asset.warrantyEndDate)}
                        </span>
                      </span>
                    )}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Panel>
    </div>
  );
}
