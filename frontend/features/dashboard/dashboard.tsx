"use client";
import { useState } from "react";
import Link from "next/link";
import {
  Users,
  UserRoundCheck,
  UserRoundX,
  ShieldCheck,
  ClipboardCheck,
  UsersRound,
  Plus,
  ArrowUpRight,
  CalendarDays,
  ArrowRight,
  LockKeyhole,
  Check,
  Activity,
  UserPlus,
  KeyRound,
  Layers3,
} from "lucide-react";
import { useDashboard } from "@/lib/api/hooks";
import { useSession } from "@/app/providers";
import { can } from "@/lib/auth/policy";
import type { AccessRequest } from "@/lib/api/types";
import {
  PageHeader,
  Panel,
  Badge,
  QueryState,
  Notice,
  Avatar,
  ViewLink,
  EmptyState,
} from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { UserForm } from "@/features/users/user-form";
import { RequestDetails } from "@/features/access-requests/request-details";
import { date } from "@/lib/utils";
export function Dashboard() {
  const query = useDashboard(),
    session = useSession();
  const [create, setCreate] = useState(false),
    [selected, setSelected] = useState<AccessRequest | null>(null),
    [message, setMessage] = useState("");
  const d = query.data;
  return (
    <>
      <PageHeader
        eyebrow="YOUR ADMINISTRATION WORKSPACE"
        title="System overview"
        description="A clear view of your identities, access and administration activity."
        actions={
          <>
            <span className="date-pill">
              <CalendarDays size={15} />
              {date(new Date().toISOString())}
            </span>
            {can(session, "iam.user.create") && (
              <Button onClick={() => setCreate(true)}>
                <Plus size={16} />
                Create user
              </Button>
            )}
          </>
        }
      />
      <div className="welcome-strip">
        <div>
          <span className="online-dot" />
          <strong>Welcome back, {session.name.split(" ")[0]}.</strong>
          <span> Here’s what needs your attention today.</span>
        </div>
        <span className="boundary-chip">
          <ScanIcon />
          Punjab region
        </span>
      </div>
      <Notice message={message} />
      <QueryState query={query}>
        {d && (
          <>
            <div className="stats-grid">
              {[
                {
                  label: "Total users",
                  value: d.totalUsers,
                  icon: Users,
                  detail: "Across your administrative region",
                  href: "users",
                },
                {
                  label: "Active users",
                  value: d.activeUsers,
                  icon: UserRoundCheck,
                  detail: `${Math.round((d.activeUsers / d.totalUsers) * 100)}% of all user accounts`,
                  href: "users?status=ACTIVE",
                },
                {
                  label: "Inactive / suspended",
                  value: d.inactiveUsers,
                  icon: UserRoundX,
                  detail: "Accounts with restricted access",
                  href: "users",
                },
                {
                  label: "Defined roles",
                  value: d.totalRoles,
                  icon: ShieldCheck,
                  detail: "6 MVP · 4 future roles",
                  href: "roles",
                },
                {
                  label: "Pending requests",
                  value: d.pendingRequests,
                  icon: ClipboardCheck,
                  detail: "Awaiting independent review",
                  href: "access-requests",
                  highlight: true,
                },
                {
                  label: "Active teams",
                  value: d.activeTeams,
                  icon: UsersRound,
                  detail: "Within your delegated boundary",
                  href: "teams",
                },
              ].map(({ label, value, icon: Icon, detail, href, highlight }) => (
                <Link
                  href={`/admin/${href}`}
                  key={label}
                  className={`stat-card ${highlight ? "stat-highlight" : ""}`}
                >
                  <div className="stat-label">
                    {label}
                    <Icon size={16} />
                  </div>
                  <div className="stat-value">
                    {value.toLocaleString("en-PK")}
                    <ArrowUpRight size={15} />
                  </div>
                  <p>{detail}</p>
                </Link>
              ))}
            </div>
            <div className="dashboard-main-grid">
              <Panel
                title="Pending approvals"
                description="Access changes awaiting an independent decision"
                action={
                  <ViewLink href="/admin/access-requests">
                    View all requests
                  </ViewLink>
                }
              >
                <div className="table-scroll">
                  <table className="approvals-table">
                    <thead>
                      <tr>
                        <th>REQUEST / USER</th>
                        <th>REQUESTED CHANGE</th>
                        <th>STATUS</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {d.requests.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <div className="person-cell">
                              <Avatar name={r.target} small />
                              <span>
                                <strong>{r.target}</strong>
                                <small className="mono">{r.id}</small>
                              </span>
                            </div>
                          </td>
                          <td>
                            <div className="cell-stack">
                              <strong>{r.proposedAccess}</strong>
                              <small>
                                {r.requesterName} · {date(r.submittedAt)}
                              </small>
                            </div>
                          </td>
                          <td>
                            <Badge>PENDING</Badge>
                          </td>
                          <td>
                            <button
                              aria-label={`Review ${r.id}`}
                              className="table-arrow"
                              onClick={() => setSelected(r)}
                            >
                              <ArrowUpRight size={17} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!d.requests.length && (
                    <EmptyState message="All requests have been reviewed." />
                  )}
                </div>
                <div className="panel-note">
                  <LockKeyhole size={13} />
                  Privileged access is applied only after approval.
                </div>
              </Panel>
              <Panel
                title="User status"
                description="Account distribution in your region"
                action={<span className="tiny-label">LIVE SNAPSHOT</span>}
              >
                <div className="status-chart">
                  <div
                    className="donut"
                    role="img"
                    aria-label={d.statuses
                      .map((s) => `${s.status}: ${s.count}`)
                      .join(", ")}
                    style={{
                      background: `conic-gradient(#16866e 0 ${(d.activeUsers / d.totalUsers) * 100}%, #c6cdd3 ${(d.activeUsers / d.totalUsers) * 100}% ${((d.activeUsers + d.statuses[1].count) / d.totalUsers) * 100}%, #d49b53 ${((d.activeUsers + d.statuses[1].count) / d.totalUsers) * 100}% ${((d.totalUsers - d.statuses[3].count) / d.totalUsers) * 100}%, #8ba6b9 ${((d.totalUsers - d.statuses[3].count) / d.totalUsers) * 100}% 100%)`,
                    }}
                  >
                    <div>
                      <strong>{d.totalUsers}</strong>
                      <small>Total users</small>
                    </div>
                  </div>
                </div>
                <div className="status-legend">
                  {d.statuses.map((s, i) => (
                    <div key={s.status}>
                      <span className={`legend-dot legend-${i}`} />
                      <span>
                        {s.status === "PENDING_ACTIVATION"
                          ? "Pending activation"
                          : s.status.charAt(0) +
                            s.status.slice(1).toLowerCase()}
                      </span>
                      <strong>{s.count}</strong>
                      <small>
                        {Math.round((s.count / d.totalUsers) * 100)}%
                      </small>
                    </div>
                  ))}
                </div>
              </Panel>
            </div>
            <div className="quick-actions">
              <div>
                <span className="quick-icon">
                  <Layers3 size={18} />
                </span>
                <div>
                  <strong>Quick actions</strong>
                  <small>Your everyday administration tools</small>
                </div>
              </div>
              <div className="quick-links">
                {can(session, "iam.user.create") && (
                  <button onClick={() => setCreate(true)}>
                    <UserPlus size={16} />
                    Create user
                    <ArrowUpRight size={14} />
                  </button>
                )}
                <Link href="/admin/roles">
                  <KeyRound size={16} />
                  View roles
                  <ArrowUpRight size={14} />
                </Link>
                <Link href="/admin/teams">
                  <UsersRound size={16} />
                  Manage teams
                  <ArrowUpRight size={14} />
                </Link>
                <Link href="/admin/access-requests">
                  <ClipboardCheck size={16} />
                  Review requests
                  <ArrowUpRight size={14} />
                </Link>
              </div>
            </div>
            <div className="dashboard-bottom-grid">
              <Panel
                title="Recent IAM activity"
                description="The latest identity and access events"
                action={
                  <ViewLink href="/admin/audit-logs">View audit log</ViewLink>
                }
              >
                <div className="activity-list">
                  {d.activity.map((e, i) => (
                    <div className="activity-row" key={e.id}>
                      <span
                        className={`activity-icon ${i === 2 ? "activity-amber" : ""}`}
                      >
                        {i % 2 ? (
                          <ShieldCheck size={16} />
                        ) : (
                          <Activity size={16} />
                        )}
                      </span>
                      <div>
                        <strong>{e.action}</strong>
                        <p>{e.description}</p>
                      </div>
                      <time>
                        {date(e.timestamp, true)}
                        <small>Asia/Karachi</small>
                      </time>
                    </div>
                  ))}
                </div>
              </Panel>
              <section className="governance-card">
                <span className="governance-icon">
                  <ShieldCheck size={25} />
                </span>
                <div className="eyebrow">BUILT-IN GOVERNANCE</div>
                <h2>
                  Controlled access.
                  <br />
                  Accountable changes.
                </h2>
                <p>
                  Keep every identity within its approved role and
                  organizational boundary.
                </p>
                <ul>
                  <li>
                    <Check size={15} />
                    Independent approval for sensitive changes
                  </li>
                  <li>
                    <Check size={15} />
                    Region and portfolio scope controls
                  </li>
                  <li>
                    <Check size={15} />
                    Read-only, traceable IAM audit history
                  </li>
                </ul>
                <Link href="/admin/settings">
                  View IAM configuration
                  <ArrowRight size={16} />
                </Link>
                <div className="governance-foot">
                  <LockKeyhole size={12} />
                  Administrative access excludes customer records.
                </div>
              </section>
            </div>
          </>
        )}
      </QueryState>
      <UserForm open={create} onOpenChange={setCreate} onSuccess={setMessage} />
      <RequestDetails
        request={selected}
        onClose={() => setSelected(null)}
        onSuccess={setMessage}
      />
    </>
  );
}
function ScanIcon() {
  return <span className="mini-grid">⊞</span>;
}
