import { test, expect } from "@playwright/test";
test("administrator lifecycle and approval boundary", async ({ page }) => {
  const name = `Nadia Test Employee ${Date.now()}`;
  await page.goto("/admin/dashboard");
  await expect(
    page.getByRole("heading", { name: "System overview" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Total users/ })).toBeVisible();
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "User management", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create user", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Full name").fill(name);
  await dialog.getByLabel("Username").fill(`nadia.test.${Date.now()}`);
  await dialog
    .getByLabel("Work email")
    .fill(`nadia.${Date.now()}@example.test`);
  await dialog.getByLabel("Employee reference").fill(`EMP-${Date.now()}`);
  await dialog.getByLabel("Initial role").selectOption("ROLE-1");
  await dialog.getByLabel("Account status").selectOption("ACTIVE");
  await dialog
    .getByRole("button", { name: "Create user", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("User created");
  await page.getByRole("textbox", { name: /Search name/ }).fill(name);
  await page
    .getByRole("link", { name: new RegExp(name) })
    .first()
    .click();
  await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Assign role", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Role", { exact: true })
    .selectOption("ROLE-2");
  await page
    .getByRole("dialog")
    .getByLabel("Business justification")
    .fill("Approved team supervisor training responsibilities");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Assign role", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Role assignment updated",
  );
  await page.getByRole("button", { name: "Assign role", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Role", { exact: true })
    .selectOption("ROLE-6");
  await page
    .getByRole("dialog")
    .getByLabel("Business justification")
    .fill("Temporary approved administrative responsibilities");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Assign role", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("pending approval");
  await page
    .getByRole("link", { name: /Access requests/ })
    .first()
    .click();
  const row = page.getByRole("row").filter({ hasText: name }).first();
  await row.getByRole("button", { name: "Review" }).click();
  await expect(page.getByText(/You submitted this request/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve & apply" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("link", { name: "Audit logs", exact: true }).click();
  const filteredAudit = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/audit-logs" &&
      url.searchParams.get("search") === name &&
      response.ok()
    );
  });
  await page.getByRole("textbox", { name: /Search audit/ }).fill(name);
  await filteredAudit;
  await expect(
    page.getByRole("cell", { name: "User created", exact: true }),
  ).toBeVisible();
});
test("all administration routes load and mobile navigation works", async ({
  page,
}) => {
  for (const [route, title] of [
    ["dashboard", "System overview"],
    ["users", "User management"],
    ["roles", "Roles & responsibilities"],
    ["permissions", "Permission catalog"],
    ["teams", "Collection teams"],
    ["access-scopes", "Access scopes"],
    ["access-requests", "Access requests"],
    ["audit-logs", "IAM audit logs"],
    ["settings", "IAM configuration"],
  ]) {
    await page.goto(`/admin/${route}`);
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await expect(page.locator(".error-state")).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/dashboard");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "Users", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "User management" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
