import { NextResponse } from "next/server";
import { monthlyLicenseSpend } from "@/lib/metrics";
import { store } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET() {
  const licenses = store.listLicenses();
  return NextResponse.json({
    licenses,
    spend: monthlyLicenseSpend(licenses),
  });
}
