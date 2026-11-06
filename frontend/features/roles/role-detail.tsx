"use client";
import Link from "next/link";
import { useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";
import { ArrowLeft, LockKeyhole } from "lucide-react";
import { useRole } from "@/lib/api/hooks";
import {
  PageHeader,
  QueryState,
  Notice,
  Badge,
  Panel,
  Avatar,
  EmptyState,
} from "@/components/ui/shared";
import { PermissionMatrix } from "./permission-matrix";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import { date } from "@/lib/utils";
export function RoleDetail({ id }: { id: string }) {
  const query = useRole(id),
    session = useSession();
  const [message, setMessage] = useState("");
  const d = query.data;
  return (
    <>
      <Link className="back-link" href="/admin/roles">
        <ArrowLeft size={14} />
        All roles
      </Link>
      <QueryState query={query}>
        {d && (
          <>
            <PageHeader
              title={d.role.name}
              description={d.role.description}
              actions={
                <>
                  <Badge>{d.role.status}</Badge>
                  <span className="role-tag">{d.role.phase}</span>
                </>
              }
            />
            <Notice message={message} />
            <div className="info-banner">
              <LockKeyhole size={18} />
              {d.role.privileged
                ? "Privileged role. Assignments and permission changes require independent approval."
                : "Protected system role. Permission changes require independent approval."}
            </div>
            <div className="detail-grid panel padded role-facts">
              <div>
                <small>Role code</small>
                <strong className="mono">{d.role.code}</strong>
              </div>
              <div>
                <small>Assigned users</small>
                <strong>{d.users.length}</strong>
              </div>
              <div>
                <small>Definition</small>
                <strong>System-defined · deletion protected</strong>
              </div>
              <div>
                <small>Scope restriction</small>
                <strong>
                  {d.role.id === "ROLE-6"
                    ? "IAM administration only · no case access"
                    : "Approved organizational assignments only"}
                </strong>
              </div>
            </div>
            <Tabs.Root defaultValue="permissions">
              <Tabs.List className="tabs-list" aria-label="Role details">
                <Tabs.Trigger value="permissions">
                  Permission matrix
                </Tabs.Trigger>
                <Tabs.Trigger value="users">
                  Assigned users ({d.users.length})
                </Tabs.Trigger>
                <Tabs.Trigger value="history">Change history</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="permissions">
                <Panel
                  title="Authorized permission mapping"
                  description="Select a permission to request a change. Checked permissions represent approved access."
                >
                  <PermissionMatrix
                    role={d.role}
                    permissions={d.permissions}
                    editable={can(session, "iam.permission.assign")}
                    onSuccess={setMessage}
                  />
                </Panel>
              </Tabs.Content>
              <Tabs.Content value="users">
                <Panel title="Users with this role">
                  <div className="padded stack">
                    {d.users.length ? (
                      d.users.map((u) => (
                        <Link
                          key={u.id}
                          href={`/admin/users/${u.id}`}
                          className="person-cell"
                        >
                          <Avatar name={u.name} />
                          <span>
                            <strong>{u.name}</strong>
                            <small>
                              {u.id} · {u.email}
                            </small>
                          </span>
                          <Badge>{u.status}</Badge>
                        </Link>
                      ))
                    ) : (
                      <EmptyState message="No users are assigned to this role." />
                    )}
                  </div>
                </Panel>
              </Tabs.Content>
              <Tabs.Content value="history">
                <Panel title="Role change history">
                  <div className="padded stack">
                    {d.audit.length ? (
                      d.audit.map((e) => (
                        <div key={e.id}>
                          <strong>{e.action}</strong>
                          <p>{e.description}</p>
                          <small>{date(e.timestamp, true)}</small>
                        </div>
                      ))
                    ) : (
                      <EmptyState message="No role changes recorded in this development session." />
                    )}
                  </div>
                </Panel>
              </Tabs.Content>
            </Tabs.Root>
          </>
        )}
      </QueryState>
    </>
  );
}
