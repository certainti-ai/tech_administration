import { Panel, Table, Row, Cell } from "@/components/table";
import { StatRow, StatTile } from "@/components/stat-tile";
import { formatIsoDate } from "@/lib/dates";
import { humanize } from "@/lib/format";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

export default function PeoplePage() {
  const people = store.listPeople();
  const requests = store.listAccessRequests();

  const byStatus = {
    active: people.filter((p) => p.status === "active").length,
    onboarding: people.filter((p) => p.status === "onboarding").length,
    offboarded: people.filter((p) => p.status === "offboarded").length,
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">People</h1>
        <p className="mt-1 text-sm text-muted">
          Everyone the estate is administered for, and what they currently hold.
        </p>
      </div>

      <StatRow>
        <StatTile label="Active" value={String(byStatus.active)} />
        <StatTile
          label="Onboarding"
          value={String(byStatus.onboarding)}
          detail={byStatus.onboarding > 0 ? "Needs kit and accounts" : undefined}
        />
        <StatTile label="Offboarded" value={String(byStatus.offboarded)} />
        <StatTile label="Total records" value={String(people.length)} />
      </StatRow>

      <Panel title="Directory" description="Sorted by name">
        <Table
          headers={[
            "Name",
            "Email",
            "Department",
            "Role",
            "Status",
            "Assets held",
            "Open requests",
            "Started",
          ]}
        >
          {people.map((person) => {
            const assetsHeld = store.assetsAssignedTo(person.id).length;
            const openRequests = requests.filter(
              (request) =>
                request.requesterId === person.id && request.status === "pending",
            ).length;

            return (
              <Row key={person.id}>
                <Cell>
                  <span className="font-medium">{person.fullName}</span>
                </Cell>
                <Cell muted>{person.email}</Cell>
                <Cell muted>{person.department}</Cell>
                <Cell muted>{person.jobTitle}</Cell>
                <Cell muted>{humanize(person.status)}</Cell>
                <Cell numeric muted>
                  {assetsHeld}
                </Cell>
                <Cell numeric muted>
                  {openRequests}
                </Cell>
                <Cell numeric muted>
                  {formatIsoDate(person.startDate)}
                </Cell>
              </Row>
            );
          })}
        </Table>
      </Panel>
    </div>
  );
}
