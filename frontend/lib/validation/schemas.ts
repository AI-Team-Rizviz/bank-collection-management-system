import { z } from "zod";
export const userSchema = z.object({
  name: z.string().trim().min(3, "Enter at least 3 characters").max(200),
  username: z
    .string()
    .regex(
      /^[a-z0-9][a-z0-9._-]{2,63}$/,
      "Use 3–64 lowercase letters, numbers, dots or underscores",
    ),
  email: z
    .email("Enter a valid email address")
    .transform((v) => v.toLowerCase()),
  employeeReference: z
    .string()
    .trim()
    .min(3, "Employee reference is required")
    .max(64),
  roleId: z.string().min(1, "Select an initial role"),
  teamId: z.string().min(1, "Select a team"),
  scopeType: z.enum(["OWN", "TEAM", "BRANCH"]),
  status: z.enum(["ACTIVE", "INACTIVE", "PENDING_ACTIVATION"]),
});
export type UserInput = z.input<typeof userSchema>;
export const teamSchema = z.object({
  name: z.string().trim().min(3).max(160),
  code: z
    .string()
    .regex(
      /^[A-Z0-9][A-Z0-9_-]{1,63}$/,
      "Use uppercase letters, numbers and hyphens",
    ),
  supervisorId: z.string().min(1, "Select a supervisor"),
  branch: z.enum(["LHR-001", "LHR-002", "FSD-001"]),
  region: z.literal("Punjab"),
  status: z.enum(["ACTIVE", "INACTIVE"]),
});
export type TeamInput = z.infer<typeof teamSchema>;
export const changeSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("ASSIGN_ROLE"),
    userId: z.string().min(1),
    roleId: z.string().min(1),
  }),
  z.object({
    kind: z.literal("REVOKE_ROLE"),
    userId: z.string().min(1),
    roleId: z.string().min(1),
  }),
  z.object({
    kind: z.literal("GRANT_SCOPE"),
    userId: z.string().min(1),
    roleId: z.string().min(1),
    scopeType: z.enum([
      "OWN",
      "TEAM",
      "BRANCH",
      "REGION",
      "PORTFOLIO",
      "GLOBAL",
    ]),
    reference: z.string().trim().min(1),
  }),
  z.object({
    kind: z.literal("GRANT_ROLE_PERMISSION"),
    roleId: z.string().min(1),
    permission: z.string().min(1),
  }),
  z.object({
    kind: z.literal("REVOKE_ROLE_PERMISSION"),
    roleId: z.string().min(1),
    permission: z.string().min(1),
  }),
  z.object({ kind: z.literal("DEACTIVATE_USER"), userId: z.string().min(1) }),
]);
export const requestSchema = z.object({
  change: changeSchema,
  justification: z
    .string()
    .trim()
    .min(12, "Provide a justification of at least 12 characters")
    .max(1000),
});
export const decisionSchema = z.object({
  comment: z
    .string()
    .trim()
    .min(5, "Add a review comment of at least 5 characters")
    .max(1000),
});
