import { daysUntil } from "./dates";
import type {
  AdminData,
  Asset,
  AssetStatus,
  License,
  AccessRequest,
} from "./types";

/**
 * Severity roles from the shared status palette. They are always rendered with
 * an icon and a text label — never colour alone.
 */
export type Severity = "good" | "warning" | "serious" | "critical";

/** A renewal inside this window is "coming up" and shows on the dashboard. */
export const RENEWAL_WINDOW_DAYS = 45;

/** A warranty inside this window is worth acting on before it lapses. */
export const WARRANTY_WINDOW_DAYS = 60;

const ASSET_STATUSES: readonly AssetStatus[] = [
  "in_use",
  "available",
  "repair",
  "retired",
];

/** Fraction of purchased seats that are actually assigned. `0` when no seats exist. */
export function seatUtilization(license: License): number {
  if (license.seatsTotal <= 0) return 0;
  return license.seatsUsed / license.seatsTotal;
}

/**
 * A fully-consumed licence is `critical` — the next hire cannot be seated
 * without a contract change. Low utilisation is also flagged, because idle
 * seats are recurring spend with nothing behind them.
 */
export function seatUtilizationSeverity(license: License): Severity {
  const ratio = seatUtilization(license);
  if (ratio >= 1) return "critical";
  if (ratio >= 0.9) return "serious";
  if (ratio < 0.6) return "warning";
  return "good";
}

/** How urgent a renewal is, given how many days remain. */
export function renewalSeverity(days: number): Severity {
  if (days < 0) return "critical";
  if (days <= 14) return "serious";
  if (days <= RENEWAL_WINDOW_DAYS) return "warning";
  return "good";
}

/** How urgent a warranty expiry is, given how many days remain. */
export function warrantySeverity(days: number): Severity {
  if (days < 0) return "critical";
  if (days <= 30) return "serious";
  if (days <= WARRANTY_WINDOW_DAYS) return "warning";
  return "good";
}

export interface DatedItem<T> {
  item: T;
  daysRemaining: number;
  severity: Severity;
}

/**
 * Licences renewing within `withinDays`, soonest first. Already-lapsed renewals
 * are included — they are the most urgent thing on the page, not the least.
 */
export function upcomingRenewals(
  licenses: readonly License[],
  today: Date,
  withinDays: number = RENEWAL_WINDOW_DAYS,
): DatedItem<License>[] {
  return licenses
    .map((license) => {
      const daysRemaining = daysUntil(license.renewalDate, today);
      return { item: license, daysRemaining, severity: renewalSeverity(daysRemaining) };
    })
    .filter(({ daysRemaining }) => daysRemaining <= withinDays)
    .sort((a, b) => a.daysRemaining - b.daysRemaining);
}

/**
 * Assets whose warranty lapses within `withinDays`, soonest first. Retired
 * assets are excluded — their warranty is nobody's problem.
 */
export function expiringWarranties(
  assets: readonly Asset[],
  today: Date,
  withinDays: number = WARRANTY_WINDOW_DAYS,
): DatedItem<Asset>[] {
  return assets
    .filter((asset) => asset.status !== "retired")
    .map((asset) => {
      const daysRemaining = daysUntil(asset.warrantyEndDate, today);
      return { item: asset, daysRemaining, severity: warrantySeverity(daysRemaining) };
    })
    .filter(({ daysRemaining }) => daysRemaining <= withinDays)
    .sort((a, b) => a.daysRemaining - b.daysRemaining);
}

export type AssetStatusBreakdown = Record<AssetStatus, number>;

export function assetStatusBreakdown(
  assets: readonly Asset[],
): AssetStatusBreakdown {
  const breakdown: AssetStatusBreakdown = {
    in_use: 0,
    available: 0,
    repair: 0,
    retired: 0,
  };
  for (const asset of assets) {
    breakdown[asset.status] += 1;
  }
  return breakdown;
}

/** The status list in the order dashboards and filters should present it. */
export function assetStatusOrder(): readonly AssetStatus[] {
  return ASSET_STATUSES;
}

export interface LicenseSpend {
  /** What the contracts bill each month, across every purchased seat. */
  committedMinor: number;
  /** The portion of that backed by an assigned seat. */
  assignedMinor: number;
  /** Recurring spend on seats nobody is using. */
  idleMinor: number;
  currency: string;
}

/**
 * Monthly licence spend.
 *
 * Assumes a single currency across the estate and reports the first licence's
 * currency; mixed-currency portfolios need per-currency totals and an FX rate,
 * which this deliberately does not invent.
 */
export function monthlyLicenseSpend(licenses: readonly License[]): LicenseSpend {
  let committedMinor = 0;
  let assignedMinor = 0;
  for (const license of licenses) {
    committedMinor += license.seatsTotal * license.monthlyCostPerSeatMinor;
    assignedMinor +=
      Math.min(license.seatsUsed, license.seatsTotal) *
      license.monthlyCostPerSeatMinor;
  }
  return {
    committedMinor,
    assignedMinor,
    idleMinor: committedMinor - assignedMinor,
    currency: licenses[0]?.currency ?? "INR",
  };
}

export function pendingAccessRequests(
  requests: readonly AccessRequest[],
): AccessRequest[] {
  return requests
    .filter((request) => request.status === "pending")
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

export interface DashboardSummary {
  totalAssets: number;
  assetsInUse: number;
  assetsAvailable: number;
  activePeople: number;
  onboardingPeople: number;
  pendingRequests: number;
  renewalsDue: DatedItem<License>[];
  warrantiesExpiring: DatedItem<Asset>[];
  spend: LicenseSpend;
  breakdown: AssetStatusBreakdown;
}

/** Everything the dashboard needs, computed in one pass over the dataset. */
export function dashboardSummary(data: AdminData, today: Date): DashboardSummary {
  const breakdown = assetStatusBreakdown(data.assets);
  return {
    totalAssets: data.assets.length,
    assetsInUse: breakdown.in_use,
    assetsAvailable: breakdown.available,
    activePeople: data.people.filter((p) => p.status === "active").length,
    onboardingPeople: data.people.filter((p) => p.status === "onboarding").length,
    pendingRequests: pendingAccessRequests(data.accessRequests).length,
    renewalsDue: upcomingRenewals(data.licenses, today),
    warrantiesExpiring: expiringWarranties(data.assets, today),
    spend: monthlyLicenseSpend(data.licenses),
    breakdown,
  };
}
