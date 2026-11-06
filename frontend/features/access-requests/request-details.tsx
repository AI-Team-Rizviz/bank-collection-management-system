"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type { z } from "zod";
import { ShieldCheck, ArrowRight, LockKeyhole } from "lucide-react";
import { useSession } from "@/app/providers";
import { useChange, useList } from "@/lib/api/hooks";
import type { AccessRequest } from "@/lib/api/types";
import { decisionSchema } from "@/lib/validation/schemas";
import { can } from "@/lib/auth/policy";
import { date } from "@/lib/utils";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Field, Notice } from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
export function RequestDetails({
  request,
  onClose,
  onSuccess,
}: {
  request: AccessRequest | null;
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  return (
    <Dialog
      open={!!request}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
      title={request ? `Access request ${request.id}` : "Access request"}
      description="Review the change, business justification and approval history."
      wide
    >
      {request && (
        <RequestReview
          key={request.id}
          request={request}
          onSuccess={onSuccess}
          close={onClose}
        />
      )}
    </Dialog>
  );
}
function RequestReview({
  request,
  close,
  onSuccess,
}: {
  request: AccessRequest;
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const session = useSession(),
    mutation = useChange();
  const audit = useList("audit-logs", { search: request.id, pageSize: 8 });
  const form = useForm<z.infer<typeof decisionSchema>>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { comment: "" },
  });
  const own = request.requestedBy === session.id;
  const allowed =
    can(session, "iam.access.approve") && !own && request.status === "PENDING";
  async function decide(action: "approve" | "reject") {
    const valid = await form.trigger();
    if (!valid) return;
    try {
      const result = await mutation.mutateAsync({
        path: `access-requests/${request.id}/${action}`,
        body: form.getValues(),
      });
      onSuccess(result.message);
      close();
    } catch {}
  }
  return (
    <>
      <div className="dialog-body stack">
        <div className="request-meta">
          <Badge>{request.status}</Badge>
          <Badge tone={request.risk === "High" ? "amber" : "gray"}>
            {request.risk} sensitivity
          </Badge>
          <span>{date(request.submittedAt, true)} PKT</span>
        </div>
        <div className="detail-grid">
          <div>
            <small>Target identity / role</small>
            <strong>{request.target}</strong>
          </div>
          <div>
            <small>Requested by</small>
            <strong>{request.requesterName}</strong>
          </div>
          <div>
            <small>Request type</small>
            <strong>{request.change.kind.replaceAll("_", " ")}</strong>
          </div>
          <div>
            <small>Approver</small>
            <strong>
              {request.history.length > 1
                ? request.history.at(-1)?.actor
                : "Awaiting independent review"}
            </strong>
          </div>
        </div>
        <div className="access-comparison">
          <div>
            <small>EXISTING ACCESS</small>
            {request.existingAccess.length ? (
              request.existingAccess.map((s) => <p key={s}>{s}</p>)
            ) : (
              <p>No approved access</p>
            )}
          </div>
          <ArrowRight size={19} />
          <div>
            <small>PROPOSED CHANGE</small>
            <p>{request.proposedAccess}</p>
          </div>
        </div>
        <div>
          <h3>Business justification</h3>
          <p className="muted">{request.justification}</p>
        </div>
        <div>
          <h3>Approval history</h3>
          {request.history.map((h, i) => (
            <div className="history-item" key={i}>
              <ShieldCheck size={16} />
              <div>
                <strong>
                  {h.decision} · {h.actor}
                </strong>
                <p>{h.comment}</p>
                <small>{date(h.at, true)} PKT</small>
              </div>
            </div>
          ))}
        </div>
        {audit.data && audit.data.total > 0 && (
          <div>
            <h3>Related audit records</h3>
            {audit.data.items.map((e) => (
              <p className="muted" key={e.id}>
                {e.id} · {e.description}
              </p>
            ))}
          </div>
        )}
        {!allowed && (
          <div className="info-banner">
            <LockKeyhole size={17} />
            {own
              ? "You submitted this request. An independent authorized approver must review it."
              : request.status !== "PENDING"
                ? "This request has been reviewed. The decision is recorded in the audit log."
                : "Your session does not include access approval permission."}
          </div>
        )}
        {allowed && (
          <Field
            label="Review comment"
            error={form.formState.errors.comment?.message}
          >
            <textarea
              rows={3}
              placeholder="Record your review rationale…"
              {...form.register("comment")}
            />
          </Field>
        )}
        <Notice error={mutation.error} />
      </div>
      <div className="dialog-footer">
        <Button variant="outline" onClick={close}>
          Close
        </Button>
        {allowed && (
          <>
            <Button
              variant="destructive"
              disabled={mutation.isPending}
              onClick={() => decide("reject")}
            >
              Reject request
            </Button>
            <Button
              disabled={mutation.isPending}
              onClick={() => decide("approve")}
            >
              {mutation.isPending ? "Submitting…" : "Approve & apply"}
            </Button>
          </>
        )}
      </div>
    </>
  );
}
