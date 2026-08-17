import Link from "next/link";
import { Meter } from "@/components/meter";
import { Panel, Table, Row, Cell, EmptyState } from "@/components/table";
import { StackedBar } from "@/components/stacked-bar";
import { StatRow, StatTile } from "@/components/stat-tile";
import { StatusBadge } from "@/components/status-badge";
import { describeDayOffset, formatIsoDate } from "@/lib/dates";
import { formatMoneyMinor, humanize } from "@/lib/format";
import {
  RENEWAL_WINDOW_DAYS,
  WARRANTY_WINDOW_DAYS,
  dashboardSummary,
} from "@/lib/metrics";
import { store } from "@/lib/store";

// The store is mutable, so the dashboard must reflect the request, not the build.
export const dynamic = "force-dynamic";

/** Categorical slots 1–4, assigned in fixed order. Never cycled. */
const STATUS_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
] as const;

export default function DashboardPage() {
  const today = new Date();
  const data = store.snapshot();
  const summary = dashboardSummary(data, today);

  const segments = (["in_use", "available", "repair", "retired"] as const).map(
    (status, index) => ({
      key: status,
      label: humanize(status),
      value: summary.breakdown[status],
      color: STATUS_COLORS[index] ?? STATUS_COLORS[0],
    }),
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          Estate overview as of {formatIsoDate(today.toISOString().slice(0, 10))}.
        </p>
      </div>

      <StatRow>
        <StatTile
          label="Assets in use"
          value={String(summary.assetsInUse)}
          detail={`${summary.totalAssets} tracked in total`}
        />
        <StatTile
          label="Available to issue"
          value={String(summary.assetsAvailable)}
          detail={`${summary.breakdown.repair} in repair`}
        />
        <StatTile
          label="Pending access requests"
          value={String(summary.pendingRequests)}
          detail={
            summary.pendingRequests > 0 ? "Awaiting a decision" : "Queue is clear"
          }
        />
        <StatTile
          label="Committed licence spend"
          value={formatMoneyMinor(summary.spend.committedMinor, summary.spend.currency, {
            compact: true,
          })}
          detail={`${formatMoneyMinor(summary.spend.idleMinor, summary.spend.currency, {
            compact: true,
          })} on idle seats`}
        />
      </StatRow>

      <Panel
        title="Asset status"
        description={`${summary.totalAssets} assets across ${segments.length} states`}
      >
        <StackedBar segments={segments} />
      </Panel>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Panel
          title="Renewals due"
          description={`Renewing within ${RENEWAL_WINDOW_DAYS} days, plus anything already lapsed`}
          action={
            <Link href="/licenses" className="text-sm text-ink-2 underline hover:text-ink">
              All licences
            </Link>
          }
        >
          {summary.renewalsDue.length === 0 ? (
            <EmptyState>Nothing renewing in this window.</EmptyState>
          ) : (
            <Table headers={["Licence", "Seats", "Renews", "Status"]}>
              {summary.renewalsDue.map(({ item, daysRemaining, severity }) => (
                <Row key={item.id}>
                  <Cell>
                    <div className="font-medium">{item.product}</div>
                    <div className="text-sm text-muted">{item.vendor}</div>
                  </Cell>
                  <Cell numeric muted>
                    {item.seatsUsed}/{item.seatsTotal}
                  </Cell>
                  <Cell numeric muted>
                    {formatIsoDate(item.renewalDate)}
                  </Cell>
                  <Cell>
                    <StatusBadge
                      severity={severity}
                      label={describeDayOffset(daysRemaining)}
                    />
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>

        <Panel
          title="Warranties expiring"
          description={`Cover ending within ${WARRANTY_WINDOW_DAYS} days, plus anything already lapsed`}
          action={
            <Link href="/assets" className="text-sm text-ink-2 underline hover:text-ink">
              All assets
            </Link>
          }
        >
          {summary.warrantiesExpiring.length === 0 ? (
            <EmptyState>No warranties lapsing in this window.</EmptyState>
          ) : (
            <Table headers={["Asset", "Assigned to", "Expires", "Status"]}>
              {summary.warrantiesExpiring.map(({ item, daysRemaining, severity }) => (
                <Row key={item.id}>
                  <Cell>
                    <div className="font-medium">{item.tag}</div>
                    <div className="text-sm text-muted">{item.model}</div>
                  </Cell>
                  <Cell muted>{store.personName(item.assignedToId)}</Cell>
                  <Cell numeric muted>
                    {formatIsoDate(item.warrantyEndDate)}
                  </Cell>
                  <Cell>
                    <StatusBadge
                      severity={severity}
                      label={describeDayOffset(daysRemaining)}
                    />
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel
        title="Licence seat utilisation"
        description="Assigned seats against what each contract pays for"
        action={
          <Link href="/licenses" className="text-sm text-ink-2 underline hover:text-ink">
            Manage
          </Link>
        }
      >
        <Table headers={["Licence", "Seats assigned", "Monthly cost"]}>
          {store.listLicenses().map((license) => (
            <Row key={license.id}>
              <Cell>
                <div className="font-medium">{license.product}</div>
                <div className="text-sm text-muted">{license.vendor}</div>
              </Cell>
              <Cell>
                <Meter
                  used={license.seatsUsed}
                  total={license.seatsTotal}
                  label={`${license.product}: ${license.seatsUsed} of ${license.seatsTotal} seats assigned`}
                />
              </Cell>
              <Cell numeric muted>
                {formatMoneyMinor(
                  license.seatsTotal * license.monthlyCostPerSeatMinor,
                  license.currency,
                )}
              </Cell>
            </Row>
          ))}
        </Table>
      </Panel>
    </div>
  );
}
