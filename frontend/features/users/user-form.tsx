"use client";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useList, useChange } from "@/lib/api/hooks";
import { userSchema, type UserInput } from "@/lib/validation/schemas";
import type { User } from "@/lib/api/types";
import { Dialog } from "@/components/ui/dialog";
import { Field, Notice } from "@/components/ui/shared";
import { Button } from "@/components/ui/button";
import { ShieldCheck } from "lucide-react";
const profileSchema = userSchema.pick({
  name: true,
  email: true,
  employeeReference: true,
});
export function UserForm({
  open,
  onOpenChange,
  user,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user?: User;
  onSuccess: (message: string) => void;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={user ? "Edit user profile" : "Create a new user"}
      description={
        user
          ? "Update permitted employee information."
          : "Provision an employee identity within your administrative boundary."
      }
      wide
    >
      {open &&
        (user ? (
          <ProfileForm
            user={user}
            close={() => onOpenChange(false)}
            onSuccess={onSuccess}
          />
        ) : (
          <CreateUserForm
            close={() => onOpenChange(false)}
            onSuccess={onSuccess}
          />
        ))}
    </Dialog>
  );
}
export function CreateUserForm({
  close,
  onSuccess,
}: {
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const roles = useList("roles", { pageSize: 100 }),
    teams = useList("teams", { pageSize: 100 }),
    mutation = useChange();
  const form = useForm<UserInput>({
    resolver: zodResolver(userSchema),
    defaultValues: {
      name: "",
      username: "",
      email: "",
      employeeReference: "",
      roleId: "ROLE-1",
      teamId: "TEAM-001",
      scopeType: "OWN",
      status: "PENDING_ACTIVATION",
    },
  });
  const selectedRole = useWatch({ control: form.control, name: "roleId" });
  const selected = roles.data?.items.find((r) => r.id === selectedRole);
  async function submit(values: UserInput) {
    try {
      const result = await mutation.mutateAsync({
        path: "users",
        body: values,
      });
      onSuccess(result.message);
      close();
    } catch {}
  }
  return (
    <form onSubmit={form.handleSubmit(submit)} noValidate>
      <div className="dialog-body">
        <div className="form-grid">
          <Field label="Full name" error={form.formState.errors.name?.message}>
            <input placeholder="e.g. Ayesha Khan" {...form.register("name")} />
          </Field>
          <Field
            label="Username"
            error={form.formState.errors.username?.message}
          >
            <input placeholder="ayesha.khan" {...form.register("username")} />
          </Field>
          <Field
            label="Work email"
            error={form.formState.errors.email?.message}
          >
            <input
              type="email"
              placeholder="employee@example.test"
              {...form.register("email")}
            />
          </Field>
          <Field
            label="Employee reference"
            error={form.formState.errors.employeeReference?.message}
          >
            <input
              placeholder="EMP-1025"
              {...form.register("employeeReference")}
            />
          </Field>
          <Field
            label="Initial role"
            error={form.formState.errors.roleId?.message}
          >
            <select {...form.register("roleId")}>
              {roles.data?.items
                .filter((r) => r.status === "ACTIVE")
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                    {r.privileged ? " · Approval required" : ""}
                  </option>
                ))}
            </select>
          </Field>
          <Field
            label="Collection team"
            error={form.formState.errors.teamId?.message}
          >
            <select {...form.register("teamId")}>
              {teams.data?.items
                .filter((t) => t.status === "ACTIVE")
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field
            label="Initial access scope"
            error={form.formState.errors.scopeType?.message}
          >
            <select {...form.register("scopeType")}>
              <option value="OWN">Own · assigned user only</option>
              <option value="TEAM">Team · selected team</option>
              <option value="BRANCH">Branch · selected team’s branch</option>
            </select>
          </Field>
          <Field
            label="Account status"
            error={form.formState.errors.status?.message}
          >
            <select {...form.register("status")}>
              <option value="PENDING_ACTIVATION">Pending activation</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </select>
          </Field>
        </div>
        <div className="info-banner">
          <ShieldCheck size={17} />
          <span>
            {selected?.privileged
              ? "This role requires independent approval. The account will have no role or scope until approved. Assign scope separately after approval."
              : "Identity provider handles credentials. No password is created here."}
          </span>
        </div>
        <Notice error={mutation.error ?? roles.error ?? teams.error} />
      </div>
      <div className="dialog-footer">
        <Button type="button" variant="outline" onClick={close}>
          Cancel
        </Button>
        <Button
          disabled={
            mutation.isPending ||
            roles.isPending ||
            teams.isPending ||
            roles.isError ||
            teams.isError
          }
        >
          {mutation.isPending ? "Creating…" : "Create user"}
        </Button>
      </div>
    </form>
  );
}
function ProfileForm({
  user,
  close,
  onSuccess,
}: {
  user: User;
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const mutation = useChange();
  const form = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: user,
  });
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit(async (data) => {
        try {
          const r = await mutation.mutateAsync({
            path: `users/${user.id}`,
            body: data,
            method: "PATCH",
          });
          onSuccess(r.message);
          close();
        } catch {}
      })}
    >
      <div className="dialog-body form-grid">
        <Field label="Full name" error={form.formState.errors.name?.message}>
          <input {...form.register("name")} />
        </Field>
        <Field label="Work email" error={form.formState.errors.email?.message}>
          <input type="email" {...form.register("email")} />
        </Field>
        <Field
          label="Employee reference"
          error={form.formState.errors.employeeReference?.message}
        >
          <input {...form.register("employeeReference")} />
        </Field>
        <Notice error={mutation.error} />
      </div>
      <div className="dialog-footer">
        <Button type="button" variant="outline" onClick={close}>
          Cancel
        </Button>
        <Button disabled={mutation.isPending}>
          {mutation.isPending ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </form>
  );
}
