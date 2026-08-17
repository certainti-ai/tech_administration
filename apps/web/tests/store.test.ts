import { beforeEach, describe, expect, it } from "vitest";
import {
  AdminStore,
  InvalidTransitionError,
  NotFoundError,
  store as sharedStore,
} from "@/lib/store";

const NOW = new Date("2026-08-17T10:00:00.000Z");

let store: AdminStore;

beforeEach(() => {
  // Each test starts from a fresh copy of the seed fixture.
  store = new AdminStore();
});

describe("lookups", () => {
  it("sorts people by name and assets by tag", () => {
    const names = store.listPeople().map((person) => person.fullName);
    expect([...names].sort((a, b) => a.localeCompare(b))).toEqual(names);

    const tags = store.listAssets().map((asset) => asset.tag);
    expect([...tags].sort((a, b) => a.localeCompare(b))).toEqual(tags);
  });

  it("lists access requests newest first", () => {
    const created = store.listAccessRequests().map((request) => request.createdAt);
    expect([...created].sort().reverse()).toEqual(created);
  });

  it("resolves a person's display name, and says so when there is none", () => {
    expect(store.personName("per-001")).toBe("Prabhu Balakrishnan");
    expect(store.personName(null)).toBe("Unassigned");
  });

  it("falls back to the raw id for an unknown person", () => {
    expect(store.personName("per-nope")).toBe("per-nope");
  });

  it("raises NotFoundError for a missing person", () => {
    expect(() => store.requirePerson("per-nope")).toThrow(NotFoundError);
  });
});

describe("assignAsset", () => {
  it("issues an available asset and marks it in use", () => {
    const updated = store.assignAsset("ast-005", "per-007");

    expect(updated.assignedToId).toBe("per-007");
    expect(updated.status).toBe("in_use");
    expect(store.assetsAssignedTo("per-007").map((a) => a.id)).toContain("ast-005");
  });

  it("returns an asset to the pool and marks it available", () => {
    const updated = store.assignAsset("ast-001", null);

    expect(updated.assignedToId).toBeNull();
    expect(updated.status).toBe("available");
  });

  it("refuses to reassign a retired asset", () => {
    expect(() => store.assignAsset("ast-007", "per-002")).toThrow(
      InvalidTransitionError,
    );
  });

  it("refuses to assign to someone who does not exist, leaving the asset untouched", () => {
    expect(() => store.assignAsset("ast-005", "per-nope")).toThrow(NotFoundError);

    const asset = store.getAsset("ast-005");
    expect(asset?.assignedToId).toBeNull();
    expect(asset?.status).toBe("available");
  });

  it("raises NotFoundError for a missing asset", () => {
    expect(() => store.assignAsset("ast-nope", null)).toThrow(NotFoundError);
  });
});

describe("decideAccessRequest", () => {
  it("approves a pending request and records who decided, and when", () => {
    const updated = store.decideAccessRequest("req-001", "approved", "per-001", NOW);

    expect(updated.status).toBe("approved");
    expect(updated.decidedById).toBe("per-001");
    expect(updated.decidedAt).toBe(NOW.toISOString());
  });

  it("denies a pending request", () => {
    const updated = store.decideAccessRequest("req-002", "denied", "per-006", NOW);
    expect(updated.status).toBe("denied");
  });

  it("treats decisions as final rather than letting an approval be flipped", () => {
    store.decideAccessRequest("req-001", "approved", "per-001", NOW);

    expect(() =>
      store.decideAccessRequest("req-001", "denied", "per-006", NOW),
    ).toThrow(InvalidTransitionError);
    expect(store.getAccessRequest("req-001")?.status).toBe("approved");
  });

  it("rejects a decision on an already-decided seed request", () => {
    expect(() =>
      store.decideAccessRequest("req-004", "denied", "per-001", NOW),
    ).toThrow(InvalidTransitionError);
  });

  it("rejects an unknown approver without changing the request", () => {
    expect(() =>
      store.decideAccessRequest("req-001", "approved", "per-nope", NOW),
    ).toThrow(NotFoundError);
    expect(store.getAccessRequest("req-001")?.status).toBe("pending");
  });

  it("raises NotFoundError for a missing request", () => {
    expect(() =>
      store.decideAccessRequest("req-nope", "approved", "per-001", NOW),
    ).toThrow(NotFoundError);
  });
});

describe("shared instance", () => {
  it("is pinned to globalThis in every environment", () => {
    // Next.js evaluates this module once per server bundle, so a store that is
    // only pinned outside production silently splits in two: writes from a
    // server action land on a different object than the one the page reads.
    const pinned = (
      globalThis as typeof globalThis & { __certaintiAdminStore?: AdminStore }
    ).__certaintiAdminStore;

    expect(pinned).toBe(sharedStore);
  });
});

describe("reset", () => {
  it("restores the seed fixture", () => {
    store.decideAccessRequest("req-001", "approved", "per-001", NOW);
    store.reset();

    expect(store.getAccessRequest("req-001")?.status).toBe("pending");
  });
});
