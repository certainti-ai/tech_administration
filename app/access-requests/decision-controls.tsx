"use client";

import { useActionState } from "react";
import { decideAccessRequest, type DecisionState } from "./actions";

const INITIAL: DecisionState = {};

/**
 * One form per decision.
 *
 * The decision travels as a hidden input rather than as the submit button's
 * `name`/`value`: React does not carry the submitter's name/value into the
 * FormData it hands to a `useActionState` action, so a shared form with two
 * named buttons silently submits no decision at all.
 */
function DecisionButton({
  requestId,
  decision,
  label,
  emphasis,
}: {
  requestId: string;
  decision: "approved" | "denied";
  label: string;
  emphasis: boolean;
}) {
  const [state, formAction, pending] = useActionState(decideAccessRequest, INITIAL);

  return (
    <form action={formAction} className="flex flex-col items-start gap-1">
      <input type="hidden" name="id" value={requestId} />
      <input type="hidden" name="decision" value={decision} />
      <button
        type="submit"
        disabled={pending}
        className={[
          "rounded border border-line px-2.5 py-1 text-sm transition-colors hover:bg-page disabled:opacity-50",
          emphasis ? "font-medium text-ink" : "text-ink-2 hover:text-ink",
        ].join(" ")}
      >
        {pending ? "Saving…" : label}
      </button>
      {state.error ? (
        <p role="alert" className="max-w-48 text-sm" style={{ color: "var(--critical)" }}>
          {state.error}
        </p>
      ) : null}
    </form>
  );
}

export function DecisionControls({ requestId }: { requestId: string }) {
  return (
    <div className="flex items-start gap-2">
      <DecisionButton
        requestId={requestId}
        decision="approved"
        label="Approve"
        emphasis
      />
      <DecisionButton
        requestId={requestId}
        decision="denied"
        label="Deny"
        emphasis={false}
      />
    </div>
  );
}
