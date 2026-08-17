import { createSeedData } from "./seed";
import type {
  AccessRequest,
  AccessRequestStatus,
  AdminData,
  Asset,
  License,
  Person,
} from "./types";

/** Thrown when a caller references a record that does not exist. */
export class NotFoundError extends Error {
  constructor(kind: string, id: string) {
    super(`${kind} "${id}" not found`);
    this.name = "NotFoundError";
  }
}

/** Thrown when a record exists but the requested transition is not legal. */
export class InvalidTransitionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidTransitionError";
  }
}

/**
 * In-memory data store.
 *
 * State lives in the process, so it resets on restart and is not shared across
 * server instances. That is intentional for a scaffold: every read and write
 * goes through this class, so swapping in a real database means reimplementing
 * these methods and nothing else.
 */
export class AdminStore {
  private data: AdminData;

  constructor(data: AdminData = createSeedData()) {
    this.data = data;
  }

  /** Replace all state — used by tests to start from a known fixture. */
  reset(data: AdminData = createSeedData()): void {
    this.data = data;
  }

  snapshot(): AdminData {
    return this.data;
  }

  // ---------------------------------------------------------------- people

  listPeople(): Person[] {
    return [...this.data.people].sort((a, b) =>
      a.fullName.localeCompare(b.fullName),
    );
  }

  getPerson(id: string): Person | undefined {
    return this.data.people.find((person) => person.id === id);
  }

  requirePerson(id: string): Person {
    const person = this.getPerson(id);
    if (!person) throw new NotFoundError("Person", id);
    return person;
  }

  /** Display name for a person id, falling back to the raw id when unknown. */
  personName(id: string | null): string {
    if (!id) return "Unassigned";
    return this.getPerson(id)?.fullName ?? id;
  }

  // ---------------------------------------------------------------- assets

  listAssets(): Asset[] {
    return [...this.data.assets].sort((a, b) => a.tag.localeCompare(b.tag));
  }

  getAsset(id: string): Asset | undefined {
    return this.data.assets.find((asset) => asset.id === id);
  }

  assetsAssignedTo(personId: string): Asset[] {
    return this.data.assets.filter((asset) => asset.assignedToId === personId);
  }

  /**
   * Issue an asset to a person, or return it to the pool when `personId` is
   * `null`. Status follows the assignment so the two can never disagree.
   */
  assignAsset(assetId: string, personId: string | null): Asset {
    const asset = this.getAsset(assetId);
    if (!asset) throw new NotFoundError("Asset", assetId);

    if (asset.status === "retired") {
      throw new InvalidTransitionError(
        `Asset "${asset.tag}" is retired and cannot be reassigned`,
      );
    }
    if (personId !== null) {
      this.requirePerson(personId);
    }

    asset.assignedToId = personId;
    asset.status = personId === null ? "available" : "in_use";
    return asset;
  }

  // -------------------------------------------------------------- licenses

  listLicenses(): License[] {
    return [...this.data.licenses].sort(
      (a, b) =>
        a.vendor.localeCompare(b.vendor) || a.product.localeCompare(b.product),
    );
  }

  getLicense(id: string): License | undefined {
    return this.data.licenses.find((license) => license.id === id);
  }

  // ------------------------------------------------------- access requests

  listAccessRequests(): AccessRequest[] {
    // Newest first — the queue is worked from the top.
    return [...this.data.accessRequests].sort((a, b) =>
      b.createdAt.localeCompare(a.createdAt),
    );
  }

  getAccessRequest(id: string): AccessRequest | undefined {
    return this.data.accessRequests.find((request) => request.id === id);
  }

  /**
   * Approve or deny a pending request. Decisions are final: re-deciding an
   * already-decided request is rejected rather than silently overwritten, so an
   * approval cannot be quietly flipped after the fact.
   */
  decideAccessRequest(
    id: string,
    decision: Exclude<AccessRequestStatus, "pending">,
    decidedById: string,
    now: Date,
  ): AccessRequest {
    const request = this.getAccessRequest(id);
    if (!request) throw new NotFoundError("Access request", id);

    if (request.status !== "pending") {
      throw new InvalidTransitionError(
        `Access request "${id}" was already ${request.status}`,
      );
    }
    this.requirePerson(decidedById);

    request.status = decision;
    request.decidedById = decidedById;
    request.decidedAt = now.toISOString();
    return request;
  }
}

/**
 * The process-wide store instance, pinned to `globalThis`.
 *
 * This is not just a development convenience. Next.js compiles server actions
 * into a different server bundle from page and route handlers, so this module
 * is evaluated more than once per process — without a shared anchor each bundle
 * would build its own `AdminStore` over its own copy of the seed data, and a
 * write made by a server action would be invisible to the page that triggered
 * it. Pinning the instance in every environment keeps them the same object.
 * (It also survives module reloads in development.)
 */
const globalForStore = globalThis as typeof globalThis & {
  __certaintiAdminStore?: AdminStore;
};

export const store: AdminStore = (globalForStore.__certaintiAdminStore ??=
  new AdminStore());
