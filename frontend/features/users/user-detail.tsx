"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import Link from "next/link";
import * as Tabs from "@radix-ui/react-tabs";
import { ArrowLeft, Pencil, ShieldCheck, UserRoundX, Plus } from "lucide-react";
import { useUser, useChange, useList } from "@/lib/api/hooks";
import {
  PageHeader,
  QueryState,
  Avatar,
  Badge,
  Panel,
  Notice,
  Field,
  EmptyState,
} from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { UserForm } from "./user-form";
import { ChangeForm } from "@/features/access-requests/change-form";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import { date } from "@/lib/utils";
const roleSchema = z.object({
  roleId: z.string().min(1),
  justification: z.string().trim().min(12, "Provide at least 12 characters"),
});
export function UserDetail({ id }: { id: string }) {
  const query = useUser(id),
    mutation = useChange(),
    session = useSession();
  const [edit, setEdit] = useState(false),
    [change, setChange] = useState(false),
    [assign, setAssign] = useState(false),
    [confirm, setConfirm] = useState(false),
    [message, setMessage] = useState("");
  const data = query.data,
    user = data?.user;
  return (
    <>
      <Link className="back-link" href="/admin/users">
        <ArrowLeft size={14} />
        All users
      </Link>
      <QueryState query={query}>
        {user && data && (
          <>
            <PageHeader
              title={user.name}
              description={`${user.id} · Employee ${user.employeeReference}`}
              actions={
                <>
                  {can(session, "iam.user.update") && (
                    <Button variant="outline" onClick={() => setEdit(true)}>
                      <Pencil size={15} />
                      Edit profile
                    </Button>
                  )}
                  {can(session, "iam.user_role.assign") && (
                    <Button onClick={() => setAssign(true)}>
                      <Plus size={15} />
                      Assign role
                    </Button>
                  )}
                </>
              }
            />
            <Notice message={message} />
            <div className="profile-summary panel">
              <Avatar name={user.name} />
              <div>
                <h2>{user.name}</h2>
                <p>{user.email}</p>
              </div>
              <Badge>{user.status}</Badge>
              <div className="profile-summary-meta">
                <small>Last login (PKT)</small>
                <strong>{date(user.lastLogin, true)}</strong>
              </div>
            </div>
            <Tabs.Root defaultValue="overview">
              <Tabs.List className="tabs-list" aria-label="User details">
                <Tabs.Trigger value="overview">Overview & access</Tabs.Trigger>
                <Tabs.Trigger value="activity">Audit activity</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="overview">
                <div className="detail-columns">
                  <Panel title="Employee information">
                    <div className="detail-grid padded">
                      <div>
                        <small>Username</small>
                        <strong>{user.username}</strong>
                      </div>
                      <div>
                        <small>Region</small>
                        <strong>{user.region}</strong>
                      </div>
                      <div>
                        <small>Employee reference</small>
                        <strong>{user.employeeReference}</strong>
                      </div>
                      <div>
                        <small>Created</small>
                        <strong>{date(user.createdAt)}</strong>
                      </div>
                    </div>
                  </Panel>
                  <Panel
                    title="Approved roles"
                    description="Effective permissions derive from these assignments."
                  >
                    <div className="padded stack">
                      {data.roles.length ? (
                        data.roles.map((r) => (
                          <div className="list-item" key={r.id}>
                            <ShieldCheck size={18} />
                            <Link href={`/admin/roles/${r.id}`}>{r.name}</Link>
                            {can(session, "iam.user_role.revoke") && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => setChange(true)}
                              >
                                Request revocation
                              </Button>
                            )}
                          </div>
                        ))
                      ) : (
                        <EmptyState message="No approved roles. Review pending access requests." />
                      )}
                    </div>
                  </Panel>
                  <Panel
                    title="Effective permissions"
                    description="Resource permissions remain constrained by approved scopes."
                  >
                    <div className="permission-tags padded">
                      {data.permissions.length ? (
                        data.permissions.map((p) => <code key={p}>{p}</code>)
                      ) : (
                        <p className="muted">No effective permissions</p>
                      )}
                    </div>
                  </Panel>
                  <Panel
                    title="Scopes & team memberships"
                    action={
                      can(session, "iam.access.request") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setChange(true)}
                        >
                          Request change
                        </Button>
                      )
                    }
                  >
                    <div className="padded stack">
                      {data.scopes.map((s) => (
                        <div className="list-item" key={s.id}>
                          <Badge tone="gray">{s.type}</Badge>
                          <strong>{s.reference}</strong>
                          <small>{s.region}</small>
                        </div>
                      ))}
                      {data.teams.map((t) => (
                        <Link
                          href="/admin/teams"
                          key={t.id}
                          className="list-item text-link"
                        >
                          {t.name}
                        </Link>
                      ))}
                    </div>
                  </Panel>
                </div>
                {can(session, "iam.user.deactivate") &&
                  user.id !== session.id && (
                    <div className="danger-zone">
                      <div>
                        <h3>
                          {user.status === "ACTIVE"
                            ? "Deactivate account"
                            : "Reactivate account"}
                        </h3>
                        <p>
                          {data.roles.some((r) => r.privileged)
                            ? "Privileged deactivation requires independent approval."
                            : "Account status changes are applied and audited."}
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        onClick={() => setConfirm(true)}
                      >
                        <UserRoundX size={15} />
                        {user.status === "ACTIVE" ? "Deactivate" : "Reactivate"}
                      </Button>
                    </div>
                  )}
              </Tabs.Content>
              <Tabs.Content value="activity">
                <Panel title="Recent access changes & audit activity">
                  <div className="padded stack">
                    {data.audit.length ? (
                      data.audit.map((e) => (
                        <div className="audit-item" key={e.id}>
                          <span className="activity-icon">
                            <ShieldCheck size={15} />
                          </span>
                          <div>
                            <strong>{e.action}</strong>
                            <p>{e.description}</p>
                            <small>{date(e.timestamp, true)}</small>
                          </div>
                          <Badge>{e.result}</Badge>
                        </div>
                      ))
                    ) : (
                      <EmptyState message="No recorded activity for this user." />
                    )}
                  </div>
                </Panel>
              </Tabs.Content>
            </Tabs.Root>
            <UserForm
              open={edit}
              onOpenChange={setEdit}
              user={user}
              onSuccess={setMessage}
            />
            <ChangeForm
              open={change}
              onOpenChange={setChange}
              userId={id}
              onSuccess={setMessage}
            />
            <Dialog
              open={assign}
              onOpenChange={setAssign}
              title="Assign a user role"
              description="Ordinary roles apply immediately. Privileged roles require independent approval."
            >
              {assign && (
                <AssignRole
                  userId={id}
                  current={user.roleIds}
                  close={() => setAssign(false)}
                  onSuccess={setMessage}
                />
              )}
            </Dialog>
            <Dialog
              open={confirm}
              onOpenChange={setConfirm}
              title={`${user.status === "ACTIVE" ? "Deactivate" : "Reactivate"} ${user.name}?`}
              description="This action changes account access and will be recorded in the audit log."
            >
              <div className="dialog-body">
                <Notice error={mutation.error} />
                <p>Confirm the account status change for {user.id}.</p>
              </div>
              <div className="dialog-footer">
                <Button variant="outline" onClick={() => setConfirm(false)}>
                  Cancel
                </Button>
                <Button
                  disabled={mutation.isPending}
                  onClick={async () => {
                    try {
                      const result = await mutation.mutateAsync({
                        path: `users/${id}/${user.status === "ACTIVE" ? "deactivate" : "reactivate"}`,
                        body: {},
                      });
                      setMessage(result.message);
                      setConfirm(false);
                    } catch {}
                  }}
                >
                  {mutation.isPending ? "Submitting…" : "Confirm change"}
                </Button>
              </div>
            </Dialog>
          </>
        )}
      </QueryState>
    </>
  );
}
function AssignRole({
  userId,
  current,
  close,
  onSuccess,
}: {
  userId: string;
  current: string[];
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const roles = useList("roles", { pageSize: 100 }),
    mutation = useChange();
  const form = useForm<z.infer<typeof roleSchema>>({
    resolver: zodResolver(roleSchema),
    defaultValues: { roleId: "", justification: "" },
  });
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit(async (values) => {
        try {
          const r = await mutation.mutateAsync({
            path: `users/${userId}/roles`,
            body: {
              change: { kind: "ASSIGN_ROLE", userId, roleId: values.roleId },
              justification: values.justification,
            },
          });
          onSuccess(r.message);
          close();
        } catch {}
      })}
    >
      <div className="dialog-body stack">
        <Field label="Role" error={form.formState.errors.roleId?.message}>
          <select {...form.register("roleId")}>
            <option value="">Select a role</option>
            {roles.data?.items
              .filter((r) => r.status === "ACTIVE" && !current.includes(r.id))
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                  {r.privileged ? " · Approval required" : ""}
                </option>
              ))}
          </select>
        </Field>
        <Field
          label="Business justification"
          error={form.formState.errors.justification?.message}
        >
          <textarea rows={3} {...form.register("justification")} />
        </Field>
        <Notice error={mutation.error} />
      </div>
      <div className="dialog-footer">
        <Button type="button" variant="outline" onClick={close}>
          Cancel
        </Button>
        <Button disabled={mutation.isPending || roles.isPending}>
          {mutation.isPending ? "Submitting…" : "Assign role"}
        </Button>
      </div>
    </form>
  );
}
