"use server";

import { revalidatePath } from "next/cache";
import { InvalidTransitionError, NotFoundError, store } from "@/lib/store";
import { currentUserId } from "@/lib/session";

export interface DecisionState {
  error?: string;
}

/**
 * Approve or deny a pending access request.
 *
 * Server actions are public endpoints, so the decision is re-read from the form
 * and validated here rather than trusted from the client. Invalid transitions
 * come back as a message on the page instead of an unhandled exception.
 */
export async function decideAccessRequest(
  _previous: DecisionState,
  formData: FormData,
): Promise<DecisionState> {
  const id = formData.get("id");
  const decision = formData.get("decision");

  if (typeof id !== "string" || id.length === 0) {
    return { error: "Missing request id." };
  }
  if (decision !== "approved" && decision !== "denied") {
    return { error: "Decision must be either approve or deny." };
  }

  try {
    store.decideAccessRequest(id, decision, currentUserId(), new Date());
  } catch (error) {
    if (error instanceof NotFoundError || error instanceof InvalidTransitionError) {
      return { error: error.message };
    }
    throw error;
  }

  revalidatePath("/access-requests");
  revalidatePath("/");
  return {};
}
