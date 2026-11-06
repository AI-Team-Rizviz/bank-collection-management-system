"use client";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, UsersRound, Pencil, UserMinus } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { Team, ListParams } from "@/lib/api/types";
import { teamSchema, type TeamInput } from "@/lib/validation/schemas";
import { useList, useChange } from "@/lib/api/hooks";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import { DataTable } from "@/components/tables/data-table";
import {
  PageHeader,
  QueryState,
  Badge,
  Notice,
  SearchInput,
  Field,
  Avatar,
} from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
export function TeamsPage() {
  const [params, setParams] = useState<ListParams>({ page: 1, pageSize: 8 }),
    [edit, setEdit] = useState<Team | null | undefined>(undefined),
    [members, setMembers] = useState<Team | null>(null),
    [message, setMessage] = useState("");
  const query = useList("teams", params),
    users = useList("users", { pageSize: 100 }),
    session = useSession();
  const editable = can(session, "iam.team.manage");
  const columns: ColumnDef<Team>[] = [
    {
      accessorKey: "name",
      header: "Collection team",
      enableSorting: true,
      cell: ({ row }) => (
        <div className="person-cell">
          <span className="role-icon">
            <UsersRound size={19} />
          </span>
          <span>
            <strong>{row.original.name}</strong>
            <small className="mono">{row.original.code}</small>
          </span>
        </div>
      ),
    },
    {
      id: "supervisor",
      header: "Supervisor",
      cell: ({ row }) =>
        users.data?.items.find((u) => u.id === row.original.supervisorId)
          ?.name ?? row.original.supervisorId,
    },
    {
      id: "members",
      header: "Members",
      cell: ({ row }) => row.original.memberIds.length,
    },
    { accessorKey: "branch", header: "Branch" },
    { accessorKey: "region", header: "Region" },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <Badge>{getValue<string>()}</Badge>,
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => (
        <div className="inline">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setMembers(row.original)}
          >
            Members
          </Button>
          {editable && (
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Edit ${row.original.name}`}
              onClick={() => setEdit(row.original)}
            >
              <Pencil size={15} />
            </Button>
          )}
        </div>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Collection teams"
        description="Organize supervisors and members within approved branches and regions."
        actions={
          editable && (
            <Button onClick={() => setEdit(null)}>
              <Plus size={16} />
              Create team
            </Button>
          )
        }
      />
      <Notice message={message} />
      <section className="panel">
        <div className="filter-toolbar">
          <SearchInput
            value={params.search ?? ""}
            onChange={(v) => setParams({ ...params, search: v, page: 1 })}
            placeholder="Search teams…"
          />
          <span className="scope-note">Administrative boundary: Punjab</span>
        </div>
        <QueryState query={query}>
          {query.data && (
            <DataTable
              data={query.data}
              columns={columns}
              params={params}
              onParams={setParams}
            />
          )}
        </QueryState>
      </section>
      <Dialog
        open={edit !== undefined}
        onOpenChange={(v) => {
          if (!v) setEdit(undefined);
        }}
        title={edit ? "Edit collection team" : "Create collection team"}
        description="Manage a team within the Punjab administrative boundary."
      >
        {edit !== undefined && (
          <TeamForm
            team={edit}
            close={() => setEdit(undefined)}
            onSuccess={setMessage}
          />
        )}
      </Dialog>
      <Dialog
        open={!!members}
        onOpenChange={(v) => {
          if (!v) setMembers(null);
        }}
        title={members?.name ?? "Team members"}
        description="Manage employee membership within this collection team."
        wide
      >
        {members && (
          <TeamMembers
            team={query.data?.items.find((t) => t.id === members.id) ?? members}
            editable={editable}
            onSuccess={setMessage}
          />
        )}
      </Dialog>
    </>
  );
}
function TeamForm({
  team,
  close,
  onSuccess,
}: {
  team: Team | null;
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const users = useList("users", {
      role: "ROLE-2",
      status: "ACTIVE",
      pageSize: 100,
    }),
    mutation = useChange();
  const form = useForm<TeamInput>({
    resolver: zodResolver(teamSchema),
    defaultValues: team
      ? {
          name: team.name,
          code: team.code,
          supervisorId: team.supervisorId,
          branch: team.branch as TeamInput["branch"],
          region: "Punjab",
          status: team.status,
        }
      : {
          name: "",
          code: "",
          supervisorId: "",
          branch: "LHR-001",
          region: "Punjab",
          status: "ACTIVE",
        },
  });
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit(async (values) => {
        try {
          const r = await mutation.mutateAsync({
            path: team ? `teams/${team.id}` : "teams",
            method: team ? "PATCH" : "POST",
            body: values,
          });
          onSuccess(r.message);
          close();
        } catch {}
      })}
    >
      <div className="dialog-body form-grid">
        <Field label="Team name" error={form.formState.errors.name?.message}>
          <input {...form.register("name")} />
        </Field>
        <Field label="Team code" error={form.formState.errors.code?.message}>
          <input placeholder="LHR-RECOVERY" {...form.register("code")} />
        </Field>
        <Field
          label="Supervisor"
          error={form.formState.errors.supervisorId?.message}
        >
          <select {...form.register("supervisorId")}>
            <option value="">Select supervisor</option>
            {users.data?.items.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Branch">
          <select {...form.register("branch")}>
            <option>LHR-001</option>
            <option>LHR-002</option>
            <option>FSD-001</option>
          </select>
        </Field>
        <Field label="Region">
          <input value="Punjab" readOnly />
        </Field>
        <Field label="Status">
          <select {...form.register("status")}>
            <option value="ACTIVE">Active</option>
            <option value="INACTIVE">Inactive</option>
          </select>
        </Field>
        <Notice error={mutation.error} />
      </div>
      <div className="dialog-footer">
        <Button type="button" variant="outline" onClick={close}>
          Cancel
        </Button>
        <Button disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save team"}
        </Button>
      </div>
    </form>
  );
}
function TeamMembers({
  team,
  editable,
  onSuccess,
}: {
  team: Team;
  editable: boolean;
  onSuccess: (message: string) => void;
}) {
  const users = useList("users", { pageSize: 100 }),
    mutation = useChange();
  const [userId, setUserId] = useState(""),
    [remove, setRemove] = useState<string | null>(null);
  async function change(id: string, remove: boolean) {
    try {
      const r = await mutation.mutateAsync({
        path: `teams/${team.id}/members`,
        body: { userId: id, remove },
      });
      setUserId("");
      setRemove(null);
      onSuccess(r.message);
    } catch {}
  }
  return (
    <div className="dialog-body stack">
      <div className="info-banner">
        {team.branch} · {team.region} · Supervisor:{" "}
        {users.data?.items.find((u) => u.id === team.supervisorId)?.name ??
          team.supervisorId}
      </div>
      <QueryState query={users}>
        <div className="member-list">
          {team.memberIds.map((id) => {
            const user = users.data?.items.find((u) => u.id === id);
            return (
              <div className="member-row" key={id}>
                <Avatar name={user?.name ?? id} small />
                <span>
                  <strong>{user?.name ?? id}</strong>
                  <small>
                    {id === team.supervisorId ? "Supervisor" : user?.email}
                  </small>
                </span>
                {editable && (
                  <Button
                    size="icon"
                    variant="ghost"
                    disabled={id === team.supervisorId || mutation.isPending}
                    aria-label={`Remove ${user?.name}`}
                    onClick={() => setRemove(id)}
                  >
                    <UserMinus size={16} />
                  </Button>
                )}
              </div>
            );
          })}
        </div>
      </QueryState>
      {editable && (
        <div className="inline">
          <Field label="Add team member">
            <select value={userId} onChange={(e) => setUserId(e.target.value)}>
              <option value="">Select an employee</option>
              {users.data?.items
                .filter((u) => !team.memberIds.includes(u.id))
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
            </select>
          </Field>
          <Button
            className="align-bottom"
            disabled={!userId || mutation.isPending}
            onClick={() => change(userId, false)}
          >
            Add member
          </Button>
        </div>
      )}
      {remove && (
        <div className="confirmation-inline">
          <p>
            Remove {users.data?.items.find((u) => u.id === remove)?.name} from
            this team?
          </p>
          <Button size="sm" variant="outline" onClick={() => setRemove(null)}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={mutation.isPending}
            onClick={() => change(remove, true)}
          >
            Confirm removal
          </Button>
        </div>
      )}
      <Notice error={mutation.error} />
    </div>
  );
}
