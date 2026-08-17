import { describe, expect, it } from "vitest";
import {
  RENEWAL_WINDOW_DAYS,
  assetStatusBreakdown,
  dashboardSummary,
  expiringWarranties,
  monthlyLicenseSpend,
  pendingAccessRequests,
  renewalSeverity,
  seatUtilization,
  seatUtilizationSeverity,
  upcomingRenewals,
  warrantySeverity,
} from "@/lib/metrics";
import { createSeedData } from "@/lib/seed";
import type { Asset, License } from "@/lib/types";

const TODAY = new Date("2026-08-17T00:00:00.000Z");

function license(overrides: Partial<License> = {}): License {
  return {
    id: "lic-test",
    vendor: "Vendor",
    product: "Product",
    seatsTotal: 10,
    seatsUsed: 7,
    monthlyCostPerSeatMinor: 100_000,
    currency: "INR",
    renewalDate: "2026-12-31",
    ownerId: "per-001",
    ...overrides,
  };
}

function asset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: "ast-test",
    tag: "CTI-TEST-0001",
    type: "laptop",
    model: "Test Laptop",
    serialNumber: "SN0001",
    status: "in_use",
    assignedToId: "per-001",
    purchaseDate: "2024-01-01",
    warrantyEndDate: "2027-01-01",
    ...overrides,
  };
}

describe("seatUtilization", () => {
  it("is the assigned fraction of purchased seats", () => {
    expect(seatUtilization(license({ seatsTotal: 10, seatsUsed: 7 }))).toBeCloseTo(0.7);
  });

  it("returns zero rather than dividing by zero when no seats are purchased", () => {
    expect(seatUtilization(license({ seatsTotal: 0, seatsUsed: 0 }))).toBe(0);
  });

  it("can exceed one when a contract is over-allocated", () => {
    expect(seatUtilization(license({ seatsTotal: 10, seatsUsed: 12 }))).toBeCloseTo(1.2);
  });
});

describe("seatUtilizationSeverity", () => {
  it("flags a full licence as critical", () => {
    expect(seatUtilizationSeverity(license({ seatsTotal: 10, seatsUsed: 10 }))).toBe(
      "critical",
    );
    expect(seatUtilizationSeverity(license({ seatsTotal: 10, seatsUsed: 11 }))).toBe(
      "critical",
    );
  });

  it("flags a nearly-full licence as serious", () => {
    expect(seatUtilizationSeverity(license({ seatsTotal: 10, seatsUsed: 9 }))).toBe(
      "serious",
    );
  });

  it("flags idle seats as a warning", () => {
    expect(seatUtilizationSeverity(license({ seatsTotal: 10, seatsUsed: 5 }))).toBe(
      "warning",
    );
  });

  it("treats the comfortable middle as good", () => {
    expect(seatUtilizationSeverity(license({ seatsTotal: 10, seatsUsed: 7 }))).toBe(
      "good",
    );
  });
});

describe("renewalSeverity", () => {
  it("escalates as the date approaches and once it passes", () => {
    expect(renewalSeverity(90)).toBe("good");
    expect(renewalSeverity(RENEWAL_WINDOW_DAYS)).toBe("warning");
    expect(renewalSeverity(14)).toBe("serious");
    expect(renewalSeverity(0)).toBe("serious");
    expect(renewalSeverity(-1)).toBe("critical");
  });
});

describe("warrantySeverity", () => {
  it("escalates as cover runs out", () => {
    expect(warrantySeverity(120)).toBe("good");
    expect(warrantySeverity(60)).toBe("warning");
    expect(warrantySeverity(30)).toBe("serious");
    expect(warrantySeverity(-5)).toBe("critical");
  });
});

describe("upcomingRenewals", () => {
  it("returns only licences inside the window, soonest first", () => {
    const result = upcomingRenewals(
      [
        license({ id: "far", renewalDate: "2027-06-01" }),
        license({ id: "soon", renewalDate: "2026-08-25" }),
        license({ id: "next", renewalDate: "2026-09-20" }),
      ],
      TODAY,
      45,
    );

    expect(result.map((entry) => entry.item.id)).toEqual(["soon", "next"]);
    expect(result[0]?.daysRemaining).toBe(8);
  });

  it("includes lapsed renewals and sorts them first", () => {
    const result = upcomingRenewals(
      [
        license({ id: "upcoming", renewalDate: "2026-09-01" }),
        license({ id: "lapsed", renewalDate: "2026-08-01" }),
      ],
      TODAY,
    );

    expect(result[0]?.item.id).toBe("lapsed");
    expect(result[0]?.daysRemaining).toBe(-16);
    expect(result[0]?.severity).toBe("critical");
  });
});

describe("expiringWarranties", () => {
  it("excludes retired assets, whose warranty nobody is chasing", () => {
    const result = expiringWarranties(
      [
        asset({ id: "live", warrantyEndDate: "2026-09-01" }),
        asset({ id: "dead", status: "retired", warrantyEndDate: "2026-08-20" }),
      ],
      TODAY,
      60,
    );

    expect(result.map((entry) => entry.item.id)).toEqual(["live"]);
  });

  it("orders the soonest expiry first", () => {
    const result = expiringWarranties(
      [
        asset({ id: "b", warrantyEndDate: "2026-10-01" }),
        asset({ id: "a", warrantyEndDate: "2026-08-30" }),
      ],
      TODAY,
      60,
    );

    expect(result.map((entry) => entry.item.id)).toEqual(["a", "b"]);
  });
});

describe("assetStatusBreakdown", () => {
  it("counts every status, including those with no assets", () => {
    expect(
      assetStatusBreakdown([
        asset({ id: "1", status: "in_use" }),
        asset({ id: "2", status: "in_use" }),
        asset({ id: "3", status: "available" }),
      ]),
    ).toEqual({ in_use: 2, available: 1, repair: 0, retired: 0 });
  });

  it("sums to the number of assets given", () => {
    const assets = createSeedData().assets;
    const breakdown = assetStatusBreakdown(assets);
    const total = Object.values(breakdown).reduce((sum, n) => sum + n, 0);
    expect(total).toBe(assets.length);
  });
});

describe("monthlyLicenseSpend", () => {
  it("splits committed spend into assigned and idle", () => {
    const spend = monthlyLicenseSpend([
      license({ seatsTotal: 10, seatsUsed: 6, monthlyCostPerSeatMinor: 100_000 }),
      license({ seatsTotal: 4, seatsUsed: 4, monthlyCostPerSeatMinor: 50_000 }),
    ]);

    expect(spend.committedMinor).toBe(10 * 100_000 + 4 * 50_000);
    expect(spend.assignedMinor).toBe(6 * 100_000 + 4 * 50_000);
    expect(spend.idleMinor).toBe(4 * 100_000);
  });

  it("never reports negative idle spend for an over-allocated licence", () => {
    const spend = monthlyLicenseSpend([
      license({ seatsTotal: 5, seatsUsed: 8, monthlyCostPerSeatMinor: 100_000 }),
    ]);

    expect(spend.assignedMinor).toBe(5 * 100_000);
    expect(spend.idleMinor).toBe(0);
  });

  it("returns zeroes and a default currency for an empty portfolio", () => {
    expect(monthlyLicenseSpend([])).toEqual({
      committedMinor: 0,
      assignedMinor: 0,
      idleMinor: 0,
      currency: "INR",
    });
  });
});

describe("pendingAccessRequests", () => {
  it("returns only pending requests, oldest first", () => {
    const requests = createSeedData().accessRequests;
    const pending = pendingAccessRequests(requests);

    expect(pending.every((request) => request.status === "pending")).toBe(true);
    const timestamps = pending.map((request) => request.createdAt);
    expect([...timestamps].sort()).toEqual(timestamps);
  });
});

describe("dashboardSummary", () => {
  it("agrees with the underlying dataset", () => {
    const data = createSeedData();
    const summary = dashboardSummary(data, TODAY);

    expect(summary.totalAssets).toBe(data.assets.length);
    expect(summary.assetsInUse).toBe(summary.breakdown.in_use);
    expect(summary.assetsAvailable).toBe(summary.breakdown.available);
    expect(summary.pendingRequests).toBe(
      data.accessRequests.filter((request) => request.status === "pending").length,
    );
    expect(summary.spend.committedMinor).toBeGreaterThan(0);
  });

  it("never reports a warranty for a retired asset", () => {
    const summary = dashboardSummary(createSeedData(), TODAY);
    expect(
      summary.warrantiesExpiring.some((entry) => entry.item.status === "retired"),
    ).toBe(false);
  });
});
