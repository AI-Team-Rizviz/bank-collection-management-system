"use client";
import { useState } from "react";
import { History, LockKeyhole, ArrowUpRight } from "lucide-react";
import type { ColumnDef } from "@tanstack/react-table";
import type { AuditEvent, ListParams } from "@/lib/api/types";
import { useList } from "@/lib/api/hooks";
import { date } from "@/lib/utils";
import {
  PageHeader,
  QueryState,
  SearchInput,
  Badge,
} from "@/components/ui/shared";
import { DataTable } from "@/components/tables/data-table";
import { Dialog } from "@/components/ui/dialog";
export function AuditPage() {
  const [params, setParams] = useState<ListParams>({ page: 1, pageSize: 8 }),
    [selected, setSelected] = useState<AuditEvent | null>(null);
  const query = useList("audit-logs", params);
  function filter(key: keyof ListParams, value: string) {
    setParams({ ...params, [key]: value, page: 1 });
  }
  const columns: ColumnDef<AuditEvent>[] = [
    {
      accessorKey: "id",
      header: "Event ID",
      cell: ({ getValue }) => (
        <span className="mono muted">{getValue<string>()}</span>
      ),
    },
    {
      accessorKey: "timestamp",
      header: "Timestamp (PKT)",
      enableSorting: true,
      cell: ({ getValue }) => (
        <span className="nowrap">{date(getValue<string>(), true)}</span>
      ),
    },
    { accessorKey: "actor", header: "Actor", enableSorting: true },
    {
      accessorKey: "action",
      header: "Action",
      cell: ({ getValue }) => (
        <span className="inline">
          <History size={14} />
          {getValue<string>()}
        </span>
      ),
    },
    { accessorKey: "target", header: "Target" },
    {
      accessorKey: "result",
      header: "Result",
      cell: ({ getValue }) => <Badge>{getValue<string>()}</Badge>,
    },
    { accessorKey: "source", header: "Source" },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <button
          className="icon-button"
          aria-label={`Inspect ${row.original.id}`}
          onClick={() => setSelected(row.original)}
        >
          <ArrowUpRight size={16} />
        </button>
      ),
    },
  ];
  return (
    <>
      <PageHeader
        title="IAM audit logs"
        description="Trace identity and access changes with a read-only activity history."
      />
      <div className="info-banner">
        <LockKeyhole size={17} />
        Audit history is read-only. All business times are displayed in
        Asia/Karachi (PKT).
      </div>
      <section className="panel">
        <div className="filter-toolbar">
          <SearchInput
            value={params.search ?? ""}
            onChange={(v) => filter("search", v)}
            placeholder="Search audit activity…"
          />
          <div className="filters">
            <input
              aria-label="Filter by actor"
              placeholder="Actor name"
              value={params.actor ?? ""}
              onChange={(e) => filter("actor", e.target.value)}
            />
            <select
              aria-label="Filter action"
              value={params.action ?? ""}
              onChange={(e) => filter("action", e.target.value)}
            >
              <option value="">All actions</option>
              {[
                "User created",
                "User updated",
                "User deactivated",
                "Role assigned",
                "Access requested",
                "Access approved",
                "Access rejected",
                "Team membership changed",
                "Self-approval blocked",
                "Scope revoked",
                "Team updated",
              ].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
            <select
              aria-label="Filter result"
              value={params.result ?? ""}
              onChange={(e) => filter("result", e.target.value)}
            >
              <option value="">All results</option>
              <option>SUCCESS</option>
              <option>DENIED</option>
              <option>FAILURE</option>
            </select>
          </div>
        </div>
        <div className="date-filters">
          <label>
            From{" "}
            <input
              type="date"
              aria-label="From date"
              value={params.from ?? ""}
              onChange={(e) => filter("from", e.target.value)}
            />
          </label>
          <label>
            To{" "}
            <input
              type="date"
              aria-label="To date"
              min={params.from}
              value={params.to ?? ""}
              onChange={(e) => filter("to", e.target.value)}
            />
          </label>
          {(params.from ||
            params.to ||
            params.actor ||
            params.action ||
            params.result ||
            params.search) && (
            <button
              className="text-link"
              onClick={() => setParams({ page: 1, pageSize: params.pageSize })}
            >
              Reset filters
            </button>
          )}
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
        open={!!selected}
        onOpenChange={(v) => {
          if (!v) setSelected(null);
        }}
        title={selected?.id ?? "Audit event"}
        description="Immutable identity and access activity record."
      >
        {selected && (
          <div className="dialog-body stack">
            <Badge>{selected.result}</Badge>
            <h3>{selected.action}</h3>
            <p>{selected.description}</p>
            <div className="detail-grid">
              <div>
                <small>Actor</small>
                <strong>{selected.actor}</strong>
              </div>
              <div>
                <small>Target entity</small>
                <strong>{selected.target}</strong>
              </div>
              <div>
                <small>Source</small>
                <strong>{selected.source}</strong>
              </div>
              <div>
                <small>Business time</small>
                <strong>{date(selected.timestamp, true)} PKT</strong>
              </div>
              <div>
                <small>API timestamp (UTC)</small>
                <code>{selected.timestamp}</code>
              </div>
            </div>
            <div className="info-banner">
              This record is read-only. No credentials or tokens are included.
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
