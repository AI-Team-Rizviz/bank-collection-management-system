import { beforeEach, it, expect, vi } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Providers } from "@/app/providers";
import { mockSession } from "@/mocks/fixtures";
import { MockIamService } from "@/mocks/service";
import { ApiError } from "@/lib/api/error";
import type { ListParams, Session } from "@/lib/api/types";
import { Dashboard } from "@/features/dashboard/dashboard";
import { UsersPage } from "@/features/users/users-page";
import { CreateUserForm } from "@/features/users/user-form";
import { RoleDetail } from "@/features/roles/role-detail";
import { TeamsPage } from "@/features/teams/teams-page";
import { RequestsPage } from "@/features/access-requests/requests-page";
import { AuditPage } from "@/features/audit/audit-page";
import { QueryState } from "@/components/ui/shared";
let service: MockIamService;
beforeEach(() => {
  service = new MockIamService();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      try {
        const url = new URL(input, "http://localhost:3000");
        const result = await service.handle(
          init?.method ?? "GET",
          url.pathname.replace("/api/v1/", ""),
          mockSession,
          Object.fromEntries(url.searchParams) as ListParams,
          init?.body ? JSON.parse(String(init.body)) : {},
        );
        return Response.json(result);
      } catch (error) {
        return Response.json(
          { message: (error as Error).message },
          { status: error instanceof ApiError ? error.status : 422 },
        );
      }
    }),
  );
});
function mount(node: React.ReactNode, session: Session = mockSession) {
  return render(<Providers session={session}>{node}</Providers>);
}
it("renders computed dashboard KPIs and working quick actions", async () => {
  mount(<Dashboard />);
  const card = await screen.findByRole("link", { name: /Total users/ });
  expect(within(card).getByText("24")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /View roles/ })).toHaveAttribute(
    "href",
    "/admin/roles",
  );
});
it("filters the user table and paginates through API results", async () => {
  const user = userEvent.setup();
  mount(<UsersPage />);
  await screen.findByText("1–8 of 24 records");
  await user.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("9–16 of 24 records");
  await user.type(
    screen.getByRole("textbox", { name: /Search name/ }),
    "Fatima Khan",
  );
  await screen.findByText("1–1 of 1 records");
  expect(screen.getByText("Fatima Khan")).toBeInTheDocument();
  expect(screen.queryByText("Ahmed Raza")).not.toBeInTheDocument();
});
it("validates the user form before creating an account", async () => {
  const user = userEvent.setup();
  mount(<CreateUserForm close={vi.fn()} onSuccess={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Create user" }));
  expect(
    await screen.findByText("Enter at least 3 characters"),
  ).toBeInTheDocument();
  expect(service.db.users).toHaveLength(24);
});
it("renders role details and requests a permission change without changing the mapping", async () => {
  const user = userEvent.setup();
  mount(<RoleDetail id="ROLE-1" />);
  await screen.findByRole("heading", { name: "Collection Agent" });
  const checkbox = screen.getByRole("checkbox", { name: /report.read/ });
  expect(checkbox).not.toBeChecked();
  await user.click(checkbox);
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Business justification" }),
    "Reporting for assigned work only",
  );
  await user.click(screen.getByRole("button", { name: "Submit for approval" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "independent review",
  );
  expect(checkbox).not.toBeChecked();
});
it("supports team membership management", async () => {
  const user = userEvent.setup();
  mount(<TeamsPage />);
  await screen.findByText("Lahore Central Collections");
  await user.click(screen.getAllByRole("button", { name: "Members" })[0]);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Ahmed Raza")).toBeInTheDocument();
  await user.selectOptions(
    within(dialog).getByRole("combobox", { name: "Add team member" }),
    "USER-006",
  );
  await user.click(within(dialog).getByRole("button", { name: "Add member" }));
  await waitFor(() =>
    expect(service.db.teams[0].memberIds).toContain("USER-006"),
  );
});
it("explains self-approval restrictions and hides approval controls", async () => {
  const user = userEvent.setup();
  mount(<RequestsPage />);
  await screen.findByText("AR-1046");
  const row = screen.getByText("AR-1046").closest("tr")!;
  await user.click(within(row).getByRole("button", { name: "Review" }));
  expect(
    await screen.findByText(/You submitted this request/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Approve & apply" }),
  ).not.toBeInTheDocument();
});
it("filters audit records by outcome", async () => {
  const user = userEvent.setup();
  mount(<AuditPage />);
  await screen.findByText("1–8 of 32 records");
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Filter result" }),
    "DENIED",
  );
  await screen.findByText("1–4 of 4 records");
  expect(screen.queryByText("Success")).not.toBeInTheDocument();
});
it("hides unauthorized user creation", async () => {
  mount(<UsersPage />, { ...mockSession, permissions: ["iam.user.read"] });
  await screen.findByText("1–8 of 24 records");
  expect(
    screen.queryByRole("button", { name: "Create user" }),
  ).not.toBeInTheDocument();
});
it("renders service errors and offers retry", () => {
  const retry = vi.fn();
  mount(
    <QueryState
      query={{
        isPending: false,
        isError: true,
        error: new Error("IAM unavailable"),
        refetch: retry,
      }}
    >
      <p>Loaded</p>
    </QueryState>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("IAM unavailable");
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});
it("renders API empty states", async () => {
  service.db.users = [];
  mount(<UsersPage />);
  expect(await screen.findByText("No records found")).toBeInTheDocument();
});
