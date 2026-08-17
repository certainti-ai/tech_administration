import { NextResponse } from "next/server";
import { assetStatusOrder } from "@/lib/metrics";
import { store } from "@/lib/store";
import type { AssetStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const requested = new URL(request.url).searchParams.get("status");

  if (requested !== null) {
    const statuses = assetStatusOrder();
    const match = statuses.find((status) => status === requested);
    if (!match) {
      return NextResponse.json(
        { error: `Unknown status "${requested}". Expected one of: ${statuses.join(", ")}.` },
        { status: 400 },
      );
    }
    const filtered = store
      .listAssets()
      .filter((asset) => asset.status === (match as AssetStatus));
    return NextResponse.json({ assets: filtered });
  }

  return NextResponse.json({ assets: store.listAssets() });
}
