"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).catch(() => null);
    if (response?.ok) {
      router.replace("/admin/dashboard");
      router.refresh();
      return;
    }
    setError(
      (await response?.json().catch(() => null))?.message ??
        "Unable to sign in",
    );
    setBusy(false);
  }
  return (
    <main className="auth-screen">
      <div className="brand-mark">C</div>
      <h1>Sign in to Bank CMS</h1>
      <p>Enter your username and password.</p>
      <form onSubmit={submit} style={{ display: "grid", gap: 12, width: 320 }}>
        <label>
          IAM username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value.trim())}
            placeholder="sysadmin001"
            autoFocus
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
