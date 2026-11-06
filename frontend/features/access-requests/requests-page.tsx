"use client";
import { useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import { useList } from "@/lib/api/hooks";
import type { AccessRequest, ListParams } from "@/lib/api/types";
import {
  PageHeader,
  Badge,
  QueryState,
  SearchInput,
  Notice,
} from "@/components/ui/shared";
import { DataTable } from "@/components/tables/data-table";
import { Button } from "@/components/ui/button";
import { date } from "@/lib/utils";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import { ChangeForm } from "./change-form";
import { RequestDetails } from "./request-details";
export function RequestsPage() {
  const [params, setParams] = useState<ListParams>({ page: 1, pageSize: 8 }),
    [selected, setSelected] = useState<AccessRequest | null>(null),
    [create, setCreate] = useState(false),
    [message, setMessage] = useState("");
  const query = useList("access-requests", params),
    session = useSession();
  const columns: ColumnDef<AccessRequest>[] = [
    {
      accessorKey: "id",
      header: "Request ID",
      cell: ({ row }) => (
        <button
          className="text-link mono"
          onClick={() => setSelected(row.original)}
        >
          {row.original.id}
        </button>
      ),
    },
    {
      id: "type",
      header: "Requested change",
      cell: ({ row }) => (
        <div className="cell-stack">
          <strong>
            {row.original.change.kind.replaceAll("_", " ").toLowerCase()}
          </strong>
          <small>{row.original.proposedAccess}</small>
        </div>
      ),
    },
    { accessorKey: "target", header: "Target user / role" },
    { accessorKey: "requesterName", header: "Requested by" },
    {
      accessorKey: "submittedAt",
      header: "Submitted",
      enableSorting: true,
      cell: ({ getValue }) => date(getValue<string>()),
    },
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <Badge>{getValue<string>()}</Badge>,
    },
    {
      accessorKey: "risk",
      header: "Sensitivity",
      cell: ({ getValue }) => (
        <Badge tone={getValue() === "High" ? "amber" : "gray"}>
          {getValue<string>()}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setSelected(row.original)}
        >
          Review
        </Button>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="Access requests"
        description="Review access changes with independent approval and a complete audit trail."
        actions={
          can(session, "iam.access.request") && (
            <Button onClick={() => setCreate(true)}>
              <Plus size={16} />
              New request
            </Button>
          )
        }
      />
      <div className="governance-banner">
        <ShieldCheck size={22} />
        <div>
          <strong>Every privilege has a checkpoint.</strong>
          <p>
            Requests are applied only after independent review. You cannot
            approve your own requests.
          </p>
        </div>
        <span>MAKER–CHECKER ENFORCED</span>
      </div>
      <Notice message={message} />
      <section className="panel">
        <div className="filter-toolbar">
          <SearchInput
            value={params.search ?? ""}
            onChange={(v) => setParams({ ...params, search: v, page: 1 })}
            placeholder="Search requests…"
          />
          <select
            aria-label="Filter request status"
            value={params.status ?? ""}
            onChange={(e) =>
              setParams({ ...params, status: e.target.value, page: 1 })
            }
          >
            <option value="">All statuses</option>
            <option value="PENDING">Pending review</option>
            <option value="APPLIED">Approved & applied</option>
            <option value="REJECTED">Rejected</option>
          </select>
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
      <ChangeForm
        open={create}
        onOpenChange={setCreate}
        onSuccess={setMessage}
      />
      <RequestDetails
        request={selected}
        onClose={() => setSelected(null)}
        onSuccess={setMessage}
      />
    </>
  );
}
