import { type FormEvent, useState } from "react";
import { authApi } from "../api/client";
import { setToken } from "../lib/auth";

export function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { access_token } = await authApi.login(username, password);
      setToken(access_token);
      onLogin();
    } catch {
      setError("Invalid username or password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.backdrop}>
      <div style={styles.card}>
        <div style={styles.brandRow}>
          <span style={styles.logo}>$</span>
          <span style={styles.brandName}>Home Finance</span>
        </div>

        <h1 style={styles.heading}>Sign in</h1>
        <p style={styles.subheading}>Your household finance dashboard</p>

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Username
            <input
              style={styles.input}
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={loading}
            />
          </label>

          <label style={styles.label}>
            Password
            <input
              style={styles.input}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
            />
          </label>

          {error && <p style={styles.error}>{error}</p>}

          <button style={{ ...styles.btn, opacity: loading ? 0.6 : 1 }} type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  backdrop: {
    minHeight: "100vh",
    background: "var(--canvas)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
  },
  card: {
    background: "var(--surface)",
    border: "1px solid var(--surface-border)",
    borderRadius: "var(--radius-lg)",
    padding: "40px 48px",
    width: "100%",
    maxWidth: "400px",
  },
  brandRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "32px",
  },
  logo: {
    width: "36px",
    height: "36px",
    background: "var(--accent)",
    borderRadius: "10px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: "18px",
    fontWeight: 600,
    color: "#fff",
    flexShrink: 0,
    lineHeight: "36px",
    textAlign: "center",
  },
  brandName: {
    fontSize: "16px",
    fontWeight: 600,
    color: "var(--text-primary)",
    letterSpacing: "-0.01em",
  },
  heading: {
    margin: "0 0 4px",
    fontSize: "24px",
    fontWeight: 600,
    color: "var(--text-primary)",
    letterSpacing: "-0.02em",
  },
  subheading: {
    margin: "0 0 28px",
    fontSize: "14px",
    color: "var(--text-muted)",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "16px",
  },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    fontSize: "12px",
    fontWeight: 400,
    color: "var(--text-muted)",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  },
  input: {
    width: "100%",
    padding: "10px 14px",
    fontSize: "14px",
    background: "var(--surface-raised)",
    border: "1px solid var(--surface-border)",
    borderRadius: "var(--radius-md)",
    color: "var(--text-primary)",
    outline: "none",
    transition: "border-color 0.15s",
  },
  error: {
    margin: "0",
    fontSize: "13px",
    color: "var(--negative-text)",
    background: "var(--negative-bg)",
    padding: "8px 12px",
    borderRadius: "var(--radius-sm)",
  },
  btn: {
    marginTop: "4px",
    padding: "11px 0",
    fontSize: "14px",
    fontWeight: 600,
    background: "var(--accent)",
    color: "#fff",
    border: "none",
    borderRadius: "var(--radius-pill)",
    cursor: "pointer",
    transition: "opacity 0.15s",
  },
};
