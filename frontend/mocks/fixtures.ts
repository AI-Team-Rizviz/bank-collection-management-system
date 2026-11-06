import type {
  User,
  Role,
  Team,
  Permission,
  Scope,
  AccessRequest,
  AuditEvent,
  Session,
} from "@/lib/api/types";
const codes = [
  "iam.user.read",
  "iam.user.create",
  "iam.user.update",
  "iam.user.deactivate",
  "iam.role.read",
  "iam.role.create",
  "iam.role.update",
  "iam.permission.read",
  "iam.permission.assign",
  "iam.user_role.assign",
  "iam.user_role.revoke",
  "iam.team.read",
  "iam.team.manage",
  "iam.access.request",
  "iam.access.approve",
  "iam.audit.read",
  "policy.read",
  "policy.create",
  "policy.update_draft",
  "policy.simulate",
  "policy.submit",
  "policy.approve",
  "policy.reject",
  "policy.activate",
  "case.read_assigned",
  "case.read_team",
  "case.read_portfolio",
  "case.assign",
  "ptp.create",
  "ptp.update",
  "delinquency.read",
  "communication.send",
  "report.read",
];
export const mockSession: Session = {
  id: "USER-001",
  name: "Ahmed Raza",
  email: "ahmed.raza@example.test",
  role: "System Administrator",
  permissions: codes.filter((c) => c.startsWith("iam.")),
  regions: ["Punjab"],
  mock: true,
};
export function seed() {
  const names = [
    "Collection Agent",
    "Collection Supervisor",
    "Collection Manager",
    "Policy Administrator",
    "Policy Approver",
    "System Administrator",
    "Recovery / Legal Officer",
    "Hardship / Restructuring Officer",
    "Compliance Officer / Auditor",
    "Portfolio / Business Executive",
  ];
  const roleCodes = [
    "COLLECTION_AGENT",
    "COLLECTION_SUPERVISOR",
    "COLLECTION_MANAGER",
    "POLICY_ADMINISTRATOR",
    "POLICY_APPROVER",
    "SYSTEM_ADMINISTRATOR",
    "RECOVERY_LEGAL_OFFICER",
    "HARDSHIP_RESTRUCTURING_OFFICER",
    "COMPLIANCE_AUDITOR",
    "PORTFOLIO_EXECUTIVE",
  ];
  const grants = [
    ["case.read_assigned", "ptp.create", "ptp.update", "communication.send"],
    ["case.read_team", "case.assign", "iam.team.read", "report.read"],
    ["case.read_portfolio", "case.assign", "report.read", "delinquency.read"],
    [
      "policy.read",
      "policy.create",
      "policy.update_draft",
      "policy.simulate",
      "policy.submit",
    ],
    ["policy.read", "policy.approve", "policy.reject", "policy.activate"],
    mockSession.permissions,
    [],
    [],
    ["iam.audit.read", "report.read"],
    ["report.read"],
  ];
  const roles: Role[] = names.map((name, i) => ({
    id: `ROLE-${i + 1}`,
    name,
    code: roleCodes[i],
    description: [
      "Manage assigned cases and customer commitments.",
      "Coordinate team workloads and collection activity.",
      "Oversee collection operations within approved portfolios.",
      "Draft and simulate collection strategies.",
      "Independently review and activate policy changes.",
      "Administer identities and approved access. No customer case access.",
      "Manage authorized recovery and legal activity.",
      "Support hardship and restructuring operations.",
      "Review compliance and read-only audit evidence.",
      "View approved portfolio performance reporting.",
    ][i],
    permissions: grants[i],
    privileged: [3, 4, 5].includes(i),
    system: true,
    phase: i < 6 ? "MVP" : "FUTURE",
    status: i < 6 ? "ACTIVE" : "INACTIVE",
    userCount: 0,
  }));
  const personNames = [
    "Ahmed Raza",
    "Fatima Khan",
    "Hassan Ali",
    "Ayesha Siddiqui",
    "Usman Malik",
    "Zainab Ahmed",
    "Bilal Sheikh",
    "Sara Iqbal",
    "Omar Farooq",
    "Maryam Aslam",
    "Saad Hussain",
    "Hina Tariq",
    "Ali Hamza",
    "Noor Fatima",
    "Danish Qureshi",
    "Amna Saleem",
    "Faisal Shah",
    "Mahnoor Akhtar",
    "Imran Akram",
    "Sana Javed",
    "Kamran Asif",
    "Rabia Naveed",
    "Talha Masood",
    "Iqra Anwar",
  ];
  const users: User[] = personNames.map((name, i) => ({
    id: `USER-${String(i + 1).padStart(3, "0")}`,
    name,
    username: name.toLowerCase().replaceAll(" ", "."),
    email: `${name.toLowerCase().replaceAll(" ", ".")}@example.test`,
    employeeReference: `EMP-${1000 + i}`,
    roleIds: [
      i === 0
        ? "ROLE-6"
        : i < 4
          ? "ROLE-2"
          : i === 4
            ? "ROLE-4"
            : i === 5
              ? "ROLE-5"
              : "ROLE-1",
    ],
    teamId: `TEAM-00${(i % 3) + 1}`,
    region: "Punjab",
    status:
      i === 10 || i === 17
        ? "INACTIVE"
        : i === 14
          ? "SUSPENDED"
          : i > 21
            ? "PENDING_ACTIVATION"
            : "ACTIVE",
    lastLogin: i < 22 ? `2026-11-0${(i % 5) + 1}T04:30:00Z` : undefined,
    createdAt: "2026-09-01T04:00:00Z",
  }));
  const teams: Team[] = ["Lahore Central", "Lahore North", "Faisalabad"].map(
    (name, i) => ({
      id: `TEAM-00${i + 1}`,
      name: `${name} Collections`,
      code: ["LHR-CENTRAL", "LHR-NORTH", "FSD-CENTRAL"][i],
      supervisorId: users[[3, 1, 2][i]].id,
      memberIds: users
        .filter((u) => u.teamId === `TEAM-00${i + 1}`)
        .map((u) => u.id),
      branch: ["LHR-001", "LHR-002", "FSD-001"][i],
      region: "Punjab",
      status: "ACTIVE",
      createdAt: "2026-08-01T04:00:00Z",
    }),
  );
  const permissions: Permission[] = codes.map((code, i) => ({
    id: `PERM-${i + 1}`,
    code,
    description: code.replaceAll(".", " · ").replaceAll("_", " "),
    module: code.startsWith("iam.user_role")
      ? "Role Management"
      : code.startsWith("iam.user")
        ? "User Management"
        : code.startsWith("iam.permission")
          ? "Permission Management"
          : code.startsWith("iam.role")
            ? "Role Management"
            : code.startsWith("iam.team")
              ? "Team Management"
              : code.startsWith("iam.access")
                ? "Access Governance"
                : code.startsWith("iam.audit")
                  ? "Audit"
                  : code.startsWith("policy")
                    ? "Policy Management"
                    : code.startsWith("case") || code.startsWith("ptp")
                      ? "Case Management"
                      : code.startsWith("report")
                        ? "Reporting"
                        : code.startsWith("delinquency")
                          ? "Delinquency Monitoring"
                          : "Communication",
    action: code.split(".").at(-1)!,
    sensitive: /assign|approve|activate|revoke|deactivate/.test(code),
    roleIds: roles.filter((r) => r.permissions.includes(code)).map((r) => r.id),
  }));
  const scopes: Scope[] = users.map((u, i) => ({
    id: `SCOPE-${i + 1}`,
    userId: u.id,
    roleId: u.roleIds[0],
    type: i < 4 ? "TEAM" : "OWN",
    reference: i < 4 ? u.teamId : u.id,
    region: u.region,
  }));
  const requests: AccessRequest[] = [
    { kind: "ASSIGN_ROLE", userId: "USER-008", roleId: "ROLE-4" },
    {
      kind: "GRANT_SCOPE",
      userId: "USER-003",
      roleId: "ROLE-2",
      scopeType: "REGION",
      reference: "Punjab",
    },
    { kind: "ASSIGN_ROLE", userId: "USER-009", roleId: "ROLE-6" },
    { kind: "REVOKE_ROLE", userId: "USER-015", roleId: "ROLE-1" },
  ].map((change, i) => ({
    id: `AR-${1048 - i}`,
    change: change as AccessRequest["change"],
    target: users.find((u) => u.id === change.userId)!.name,
    requestedBy: i === 2 ? "USER-001" : "USER-002",
    requesterName: i === 2 ? "Ahmed Raza" : "Fatima Khan",
    submittedAt: `2026-11-0${6 - i}T04:15:00Z`,
    status: "PENDING",
    risk: i === 3 ? "Standard" : "High",
    justification:
      "Access required for approved operational responsibilities in the Punjab region.",
    existingAccess: ["Collection Agent · Own scope"],
    proposedAccess:
      change.kind === "GRANT_SCOPE"
        ? "Region · Punjab"
        : roles.find((r) => r.id === change.roleId)!.name,
    history: [
      {
        actor: i === 2 ? "Ahmed Raza" : "Fatima Khan",
        decision: "Submitted",
        comment: "Pending independent review",
        at: `2026-11-0${6 - i}T04:15:00Z`,
      },
    ],
  }));
  const actions = [
    "User created",
    "Role assigned",
    "Access requested",
    "Team membership changed",
    "User deactivated",
    "Access approved",
    "Access rejected",
    "User updated",
  ];
  const audit: AuditEvent[] = Array.from({ length: 32 }, (_, i) => ({
    id: `EVT-${2304 - i}`,
    timestamp: new Date(Date.UTC(2026, 10, 6, 5, 45 - i * 37)).toISOString(),
    actor: i % 3 === 0 ? "Ahmed Raza" : "Fatima Khan",
    action: actions[i % 8],
    target: users[(i + 3) % users.length].id,
    result: i % 8 === 6 ? "DENIED" : "SUCCESS",
    source: "IAM administration",
    description: `${i % 3 === 0 ? "Ahmed Raza" : "Fatima Khan"}: ${actions[i % 8].toLowerCase()} for ${users[(i + 3) % users.length].name}.`,
  }));
  return { users, roles, teams, permissions, scopes, requests, audit };
}
export type Store = ReturnType<typeof seed>;
