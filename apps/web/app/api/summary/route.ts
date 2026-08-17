import { NextResponse } from "next/server";
import { dashboardSummary } from "@/lib/metrics";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(dashboardSummary(store.snapshot(), new Date()));
}
