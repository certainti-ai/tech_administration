/**
 * Domain model for the tech administration portal.
 *
 * Dates are stored as calendar dates (`YYYY-MM-DD`) rather than timestamps.
 * Renewals, warranties and start dates are calendar facts — anchoring them to an
 * instant would make them drift across timezones. Timestamps (`createdAt`,
 * `decidedAt`) are full ISO-8601 strings because the moment matters there.
 */

/** A calendar date in `YYYY-MM-DD` form. */
export type IsoDate = string;

/** A full ISO-8601 instant. */
export type IsoTimestamp = string;

export type PersonStatus = "active" | "onboarding" | "offboarded";

export interface Person {
  id: string;
  fullName: string;
  email: string;
  department: string;
  jobTitle: string;
  status: PersonStatus;
  startDate: IsoDate;
}

export type AssetType =
  | "laptop"
  | "desktop"
  | "monitor"
  | "phone"
  | "server"
  | "peripheral";

export type AssetStatus = "in_use" | "available" | "repair" | "retired";

export interface Asset {
  id: string;
  tag: string;
  type: AssetType;
  model: string;
  serialNumber: string;
  status: AssetStatus;
  /** `null` when the asset is not currently issued to anyone. */
  assignedToId: string | null;
  purchaseDate: IsoDate;
  warrantyEndDate: IsoDate;
}

export interface License {
  id: string;
  vendor: string;
  product: string;
  seatsTotal: number;
  seatsUsed: number;
  /** Cost per seat per month, in minor units (paise/cents) to avoid float drift. */
  monthlyCostPerSeatMinor: number;
  currency: string;
  renewalDate: IsoDate;
  /** Person accountable for the contract. */
  ownerId: string;
}

export type AccessRequestStatus = "pending" | "approved" | "denied";

export type AccessLevel = "read" | "write" | "admin";

export interface AccessRequest {
  id: string;
  requesterId: string;
  /** The system access is being requested for, e.g. "Production AWS". */
  system: string;
  accessLevel: AccessLevel;
  justification: string;
  status: AccessRequestStatus;
  createdAt: IsoTimestamp;
  decidedAt: IsoTimestamp | null;
  /** Person id of the approver, or `null` while pending. */
  decidedById: string | null;
}

/** The full dataset the store holds. */
export interface AdminData {
  people: Person[];
  assets: Asset[];
  licenses: License[];
  accessRequests: AccessRequest[];
}
