"use client";
import { useState } from "react";
import type { Permission, Role } from "@/lib/api/types";
import { SearchInput, Badge, Field, Notice } from "@/components/ui/shared";
import { Dialog } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useChange } from "@/lib/api/hooks";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
const schema = z.object({
  justification: z.string().trim().min(12, "Provide at least 12 characters"),
});
export function PermissionMatrix({
  permissions,
  role,
  editable,
  onSuccess,
}: {
  permissions: Permission[];
  role: Role;
  editable: boolean;
  onSuccess: (message: string) => void;
}) {
  const [search, setSearch] = useState(""),
    [selected, setSelected] = useState<Permission | null>(null);
  const visible = permissions.filter((p) =>
    `${p.code} ${p.module}`.toLowerCase().includes(search.toLowerCase()),
  );
  const groups = [...new Set(visible.map((p) => p.module))];
  return (
    <>
      <div className="filter-toolbar">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search the permission matrix…"
        />
        <span className="muted">
          {role.permissions.length} approved permissions
        </span>
      </div>
      <div className="permission-matrix">
        {groups.map((group) => (
          <fieldset key={group}>
            <legend>{group}</legend>
            {visible
              .filter((p) => p.module === group)
              .map((p) => (
                <label key={p.id} className="permission-row">
                  <input
                    type="checkbox"
                    checked={role.permissions.includes(p.code)}
                    disabled={!editable || role.status !== "ACTIVE"}
                    onChange={() => setSelected(p)}
                  />
                  <span>
                    <code>{p.code}</code>
                    <small>{p.description}</small>
                  </span>
                  {p.sensitive && <Badge tone="amber">Sensitive</Badge>}
                </label>
              ))}
          </fieldset>
        ))}
        {!visible.length && (
          <p className="empty-state">No matching permissions.</p>
        )}
      </div>
      <Dialog
        open={!!selected}
        onOpenChange={(v) => {
          if (!v) setSelected(null);
        }}
        title="Request permission change"
        description="The approved mapping remains unchanged until an independent review."
      >
        {selected && (
          <PermissionChange
            role={role}
            permission={selected}
            close={() => setSelected(null)}
            onSuccess={onSuccess}
          />
        )}
      </Dialog>
    </>
  );
}
function PermissionChange({
  role,
  permission,
  close,
  onSuccess,
}: {
  role: Role;
  permission: Permission;
  close: () => void;
  onSuccess: (message: string) => void;
}) {
  const mutation = useChange(),
    form = useForm<z.infer<typeof schema>>({
      resolver: zodResolver(schema),
      defaultValues: { justification: "" },
    });
  const revoke = role.permissions.includes(permission.code);
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit(async (values) => {
        try {
          const r = await mutation.mutateAsync({
            path: "access-requests",
            body: {
              change: {
                kind: revoke
                  ? "REVOKE_ROLE_PERMISSION"
                  : "GRANT_ROLE_PERMISSION",
                roleId: role.id,
                permission: permission.code,
              },
              justification: values.justification,
            },
          });
          onSuccess(r.message);
          close();
        } catch {}
      })}
    >
      <div className="dialog-body stack">
        <div className="info-banner">
          {revoke ? "Revoke" : "Grant"} <code>{permission.code}</code>{" "}
          {revoke ? "from" : "to"} {role.name}
        </div>
        <Field
          label="Business justification"
          error={form.formState.errors.justification?.message}
        >
          <textarea rows={3} {...form.register("justification")} />
        </Field>
        <Notice error={mutation.error} />
      </div>
      <div className="dialog-footer">
        <Button variant="outline" type="button" onClick={close}>
          Cancel
        </Button>
        <Button disabled={mutation.isPending}>
          {mutation.isPending ? "Submitting…" : "Submit for approval"}
        </Button>
      </div>
    </form>
  );
}
