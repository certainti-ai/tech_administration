import { Meter } from "@/components/meter";
import { Panel, Table, Row, Cell } from "@/components/table";
import { StatRow, StatTile } from "@/components/stat-tile";
import { StatusBadge } from "@/components/status-badge";
import { describeDayOffset, daysUntil, formatIsoDate } from "@/lib/dates";
import { formatMoneyMinor, formatPercent } from "@/lib/format";
import {
  monthlyLicenseSpend,
  renewalSeverity,
  seatUtilization,
  seatUtilizationSeverity,
} from "@/lib/metrics";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

/** Why a licence is flagged, so the badge never has to be read from colour. */
function utilisationLabel(ratio: number): string {
  if (ratio >= 1) return "No seats left";
  if (ratio >= 0.9) return "Nearly full";
  if (ratio < 0.6) return `${formatPercent(ratio)} used`;
  return "Healthy";
}

export default function LicensesPage() {
  const today = new Date();
  const licenses = store.listLicenses();
  const spend = monthlyLicenseSpend(licenses);

  const totalSeats = licenses.reduce((sum, l) => sum + l.seatsTotal, 0);
  const usedSeats = licenses.reduce((sum, l) => sum + l.seatsUsed, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Licences</h1>
        <p className="mt-1 text-sm text-muted">
          Software contracts, seat utilisation, and what renews when.
        </p>
      </div>

      <StatRow>
        <StatTile
          label="Contracts"
          value={String(licenses.length)}
          detail={`${new Set(licenses.map((l) => l.vendor)).size} vendors`}
        />
        <StatTile
          label="Seats assigned"
          value={`${usedSeats} / ${totalSeats}`}
          detail={`${formatPercent(totalSeats > 0 ? usedSeats / totalSeats : 0)} of purchased seats`}
        />
        <StatTile
          label="Committed monthly"
          value={formatMoneyMinor(spend.committedMinor, spend.currency, { compact: true })}
          detail="Across every purchased seat"
        />
        <StatTile
          label="Idle seat spend"
          value={formatMoneyMinor(spend.idleMinor, spend.currency, { compact: true })}
          detail="Recurring cost with nobody assigned"
        />
      </StatRow>

      <Panel title="All licences" description="Sorted by vendor, then product">
        <Table
          headers={[
            "Vendor",
            "Product",
            "Seats",
            "Utilisation",
            "Monthly cost",
            "Renews",
            "Owner",
          ]}
        >
          {licenses.map((license) => {
            const ratio = seatUtilization(license);
            const renewalDays = daysUntil(license.renewalDate, today);
            return (
              <Row key={license.id}>
                <Cell muted>{license.vendor}</Cell>
                <Cell>
                  <span className="font-medium">{license.product}</span>
                </Cell>
                <Cell>
                  <Meter
                    used={license.seatsUsed}
                    total={license.seatsTotal}
                    label={`${license.product}: ${license.seatsUsed} of ${license.seatsTotal} seats assigned`}
                  />
                </Cell>
                <Cell>
                  <StatusBadge
                    severity={seatUtilizationSeverity(license)}
                    label={utilisationLabel(ratio)}
                  />
                </Cell>
                <Cell numeric muted>
                  {formatMoneyMinor(
                    license.seatsTotal * license.monthlyCostPerSeatMinor,
                    license.currency,
                  )}
                </Cell>
                <Cell>
                  <span className="flex flex-col gap-0.5">
                    <StatusBadge
                      severity={renewalSeverity(renewalDays)}
                      label={describeDayOffset(renewalDays)}
                    />
                    <span className="tabular text-sm text-muted">
                      {formatIsoDate(license.renewalDate)}
                    </span>
                  </span>
                </Cell>
                <Cell muted>{store.personName(license.ownerId)}</Cell>
              </Row>
            );
          })}
        </Table>
      </Panel>
    </div>
  );
}
