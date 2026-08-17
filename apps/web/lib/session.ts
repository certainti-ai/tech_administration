/**
 * Stand-in for the authenticated user.
 *
 * There is no auth in this scaffold. Every action that records "who did this"
 * reads from here, so wiring up a real identity provider means changing this
 * one function rather than hunting for hard-coded ids. Until then, treat every
 * recorded approver as unverified.
 */
export function currentUserId(): string {
  return "per-001";
}
