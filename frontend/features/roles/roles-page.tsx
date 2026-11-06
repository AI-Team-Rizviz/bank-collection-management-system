"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ShieldCheck, LockKeyhole } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { Role, ListParams } from "@/lib/api/types";
import { useList } from "@/lib/api/hooks";
import { DataTable } from "@/components/tables/data-table";
import {
  PageHeader,
  QueryState,
  Badge,
  SearchInput,
} from "@/components/ui/shared";
export function RolesPage() {
  const [params, setParams] = useState<ListParams>({ page: 1, pageSize: 16 });
  const query = useList("roles", params);
  const columns: ColumnDef<Role>[] = [
    {
      accessorKey: "name",
      header: "Role",
      enableSorting: true,
      cell: ({ row }) => (
        <Link className="person-cell" href={`/admin/roles/${row.original.id}`}>
          <span className="role-icon">
            <ShieldCheck size={19} />
          </span>
          <span>
            <strong>{row.original.name}</strong>
            <small className="mono">{row.original.code}</small>
          </span>
        </Link>
      ),
    },
    {
      accessorKey: "description",
      header: "Description",
      cell: ({ getValue }) => (
        <span className="description-cell">{getValue<string>()}</span>
      ),
    },
    { accessorKey: "userCount", header: "Users", enableSorting: true },
    {
      id: "permissions",
      header: "Permissions",
      cell: ({ row }) => row.original.permissions.length,
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <Badge>{getValue<string>()}</Badge>,
    },
    {
      accessorKey: "phase",
      header: "Phase",
      cell: ({ getValue }) => (
        <span className="role-tag">{getValue<string>()}</span>
      ),
    },
    {
      id: "type",
      header: "Definition",
      cell: () => (
        <span className="muted inline">
          <LockKeyhole size={13} />
          System-defined
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Link
          className="icon-button"
          href={`/admin/roles/${row.original.id}`}
          aria-label={`View ${row.original.name}`}
        >
          <ArrowUpRight size={17} />
        </Link>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Roles & responsibilities"
        description="Ten predefined roles. Clear responsibilities. Controlled privileges."
      />
      <div className="info-banner">
        <ShieldCheck size={18} />
        System-defined roles are protected from deletion. All permission changes
        require independent approval.
      </div>
      <section className="panel">
        <div className="filter-toolbar">
          <SearchInput
            value={params.search ?? ""}
            onChange={(v) => setParams({ ...params, search: v, page: 1 })}
            placeholder="Search roles or permissions…"
          />
          <span className="muted">6 MVP roles · 4 future roles</span>
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
    </>
  );
}
