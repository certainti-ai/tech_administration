import { NextResponse } from "next/server";
import { store } from "@/lib/store";
import type { AccessRequestStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

const STATUSES: readonly AccessRequestStatus[] = ["pending", "approved", "denied"];

export async function GET(request: Request) {
  const requested = new URL(request.url).searchParams.get("status");
  const all = store.listAccessRequests();

  if (requested === null) {
    return NextResponse.json({ accessRequests: all });
  }

  const match = STATUSES.find((status) => status === requested);
  if (!match) {
    return NextResponse.json(
      { error: `Unknown status "${requested}". Expected one of: ${STATUSES.join(", ")}.` },
      { status: 400 },
    );
  }

  return NextResponse.json({
    accessRequests: all.filter((item) => item.status === match),
  });
}
