import Link from "next/link";
export default function NotFound() {
  return (
    <main className="auth-screen">
      <h1>Page not found</h1>
      <p>This page is not part of the administration workspace.</p>
      <Link href="/admin/dashboard">Return to overview</Link>
    </main>
  );
}
