import { Panel, Table, Row, Cell, EmptyState } from "@/components/table";
import { StatusBadge } from "@/components/status-badge";
import { humanize } from "@/lib/format";
import { pendingAccessRequests } from "@/lib/metrics";
import { store } from "@/lib/store";
import type { AccessRequest } from "@/lib/types";
import { DecisionControls } from "./decision-controls";

export const dynamic = "force-dynamic";

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(new Date(value));
}

function DecisionBadge({ request }: { request: AccessRequest }) {
  return request.status === "approved" ? (
    <StatusBadge severity="good" label="Approved" />
  ) : (
    <StatusBadge severity="critical" label="Denied" />
  );
}

export default function AccessRequestsPage() {
  const all = store.listAccessRequests();
  const pending = pendingAccessRequests(all);
  const decided = all.filter((request) => request.status !== "pending");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Access requests</h1>
        <p className="mt-1 text-sm text-muted">
          Requests for system access, oldest first. Decisions are final.
        </p>
      </div>

      <Panel
        title="Pending"
        description={`${pending.length} awaiting a decision`}
      >
        {pending.length === 0 ? (
          <EmptyState>The queue is clear.</EmptyState>
        ) : (
          <Table
            headers={[
              "Requester",
              "System",
              "Level",
              "Justification",
              "Raised",
              "Decision",
            ]}
          >
            {pending.map((request) => (
              <Row key={request.id}>
                <Cell>
                  <span className="font-medium">
                    {store.personName(request.requesterId)}
                  </span>
                </Cell>
                <Cell muted>{request.system}</Cell>
                <Cell muted>{humanize(request.accessLevel)}</Cell>
                <Cell muted>
                  <span className="block max-w-xs">{request.justification}</span>
                </Cell>
                <Cell numeric muted>
                  {formatTimestamp(request.createdAt)}
                </Cell>
                <Cell>
                  <DecisionControls requestId={request.id} />
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Panel>

      <Panel title="Decided" description={`${decided.length} in the audit trail`}>
        {decided.length === 0 ? (
          <EmptyState>No decisions recorded yet.</EmptyState>
        ) : (
          <Table
            headers={[
              "Requester",
              "System",
              "Level",
              "Outcome",
              "Decided by",
              "Decided",
            ]}
          >
            {decided.map((request) => (
              <Row key={request.id}>
                <Cell>
                  <span className="font-medium">
                    {store.personName(request.requesterId)}
                  </span>
                </Cell>
                <Cell muted>{request.system}</Cell>
                <Cell muted>{humanize(request.accessLevel)}</Cell>
                <Cell>
                  <DecisionBadge request={request} />
                </Cell>
                <Cell muted>{store.personName(request.decidedById)}</Cell>
                <Cell numeric muted>
                  {request.decidedAt ? formatTimestamp(request.decidedAt) : "—"}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  );
}
