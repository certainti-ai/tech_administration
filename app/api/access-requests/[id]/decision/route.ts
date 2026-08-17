import { NextResponse } from "next/server";
import { currentUserId } from "@/lib/session";
import { InvalidTransitionError, NotFoundError, store } from "@/lib/store";

export const dynamic = "force-dynamic";

/**
 * Record a decision on a pending access request.
 *
 * `POST /api/access-requests/{id}/decision` with `{ "decision": "approved" }`.
 * The approver comes from the session rather than the request body — letting a
 * caller name their own approver would make the audit trail meaningless.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Request body must be JSON." }, { status: 400 });
  }

  const decision =
    typeof body === "object" && body !== null
      ? (body as { decision?: unknown }).decision
      : undefined;

  if (decision !== "approved" && decision !== "denied") {
    return NextResponse.json(
      { error: 'Field "decision" must be "approved" or "denied".' },
      { status: 400 },
    );
  }

  try {
    const updated = store.decideAccessRequest(
      id,
      decision,
      currentUserId(),
      new Date(),
    );
    return NextResponse.json({ accessRequest: updated });
  } catch (error) {
    if (error instanceof NotFoundError) {
      return NextResponse.json({ error: error.message }, { status: 404 });
    }
    if (error instanceof InvalidTransitionError) {
      return NextResponse.json({ error: error.message }, { status: 409 });
    }
    throw error;
  }
}
