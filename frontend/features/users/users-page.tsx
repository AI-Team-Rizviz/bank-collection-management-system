"use client";
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Plus, SlidersHorizontal, ArrowUpRight } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { useList } from "@/lib/api/hooks";
import type { ListParams, User } from "@/lib/api/types";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import { date } from "@/lib/utils";
import {
  Avatar,
  Badge,
  PageHeader,
  QueryState,
  SearchInput,
  Notice,
} from "@/components/ui/shared";
import { DataTable } from "@/components/tables/data-table";
import { Button } from "@/components/ui/button";
import { UserForm } from "./user-form";
export function UsersPage() {
  const searchParams = useSearchParams();
  const [params, setParams] = useState<ListParams>({
      page: 1,
      pageSize: 8,
      status: searchParams.get("status") ?? "",
    }),
    [create, setCreate] = useState(false),
    [message, setMessage] = useState("");
  const users = useList("users", params),
    roles = useList("roles", { pageSize: 100 }),
    teams = useList("teams", { pageSize: 100 });
  const session = useSession();
  const columns: ColumnDef<User>[] = [
    {
      accessorKey: "name",
      header: "User",
      enableSorting: true,
      cell: ({ row }) => (
        <Link href={`/admin/users/${row.original.id}`} className="person-cell">
          <Avatar name={row.original.name} />
          <span>
            <strong>{row.original.name}</strong>
            <small>{row.original.id}</small>
          </span>
        </Link>
      ),
    },
    { accessorKey: "username", header: "Username", enableSorting: true },
    {
      accessorKey: "email",
      header: "Email",
      cell: ({ getValue }) => (
        <span className="muted">{getValue<string>()}</span>
      ),
    },
    {
      id: "roles",
      header: "Assigned roles",
      cell: ({ row }) => (
        <div className="role-tags">
          {row.original.roleIds.length ? (
            row.original.roleIds.map((id) => (
              <span className="role-tag" key={id}>
                {roles.data?.items.find((r) => r.id === id)?.name ?? id}
              </span>
            ))
          ) : (
            <span className="muted">Pending assignment</span>
          )}
        </div>
      ),
    },
    {
      id: "team",
      header: "Team",
      cell: ({ row }) =>
        teams.data?.items
          .find((t) => t.id === row.original.teamId)
          ?.name.replace(" Collections", "") ?? "Unassigned",
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <Badge>{getValue<string>()}</Badge>,
    },
    {
      accessorKey: "lastLogin",
      header: "Last login",
      enableSorting: true,
      cell: ({ getValue }) => (
        <span className="muted nowrap">{date(getValue<string>())}</span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Link
          className="icon-button"
          href={`/admin/users/${row.original.id}`}
          aria-label={`View ${row.original.name}`}
        >
          <ArrowUpRight size={17} />
        </Link>
      ),
    },
  ];
  function filter(key: keyof ListParams, value: string) {
    setParams({ ...params, [key]: value, page: 1 });
  }
  return (
    <>
      <PageHeader
        title="User management"
        description="Manage employee identities, account status and approved access."
        actions={
          can(session, "iam.user.create") && (
            <Button onClick={() => setCreate(true)}>
              <Plus size={16} />
              Create user
            </Button>
          )
        }
      />
      <Notice message={message} />
      <section className="panel">
        <div className="section-tabs">
          <span className="selected">
            All users <b>{users.data?.total ?? "—"}</b>
          </span>
          <span className="scope-note">
            <SlidersHorizontal size={14} /> Punjab region
          </span>
        </div>
        <div className="filter-toolbar">
          <SearchInput
            value={params.search ?? ""}
            onChange={(v) => filter("search", v)}
            placeholder="Search name, username or email…"
          />
          <div className="filters">
            <select
              aria-label="Filter by role"
              value={params.role ?? ""}
              onChange={(e) => filter("role", e.target.value)}
            >
              <option value="">All roles</option>
              {roles.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by status"
              value={params.status ?? ""}
              onChange={(e) => filter("status", e.target.value)}
            >
              <option value="">All statuses</option>
              {["ACTIVE", "INACTIVE", "SUSPENDED", "PENDING_ACTIVATION"].map(
                (s) => (
                  <option key={s} value={s}>
                    {s.replaceAll("_", " ")}
                  </option>
                ),
              )}
            </select>
            <select
              aria-label="Filter by team"
              value={params.team ?? ""}
              onChange={(e) => filter("team", e.target.value)}
            >
              <option value="">All teams</option>
              {teams.data?.items.map((t) => (
                <option value={t.id} key={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <QueryState query={users}>
          {users.data && (
            <DataTable
              data={users.data}
              columns={columns}
              params={params}
              onParams={setParams}
            />
          )}
        </QueryState>
      </section>
      <div className="footnote">
        Access is limited to your delegated organizational boundary. Privileged
        assignments require independent approval.
      </div>
      <UserForm open={create} onOpenChange={setCreate} onSuccess={setMessage} />
    </>
  );
}
