import { useState } from "react";
import { CONTENTFLOW_LOGO } from "../../constants/brand";
import { appProductMeta } from "../../constants/appProject";
import { useAuth } from "../../context/AuthContext";
import { IconEye } from "../shared/icons";

const PRODUCT = appProductMeta();

export default function LoginPage() {
  const { signIn } = useAuth();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signIn(username.trim(), password);
    } catch (err) {
      setError(err?.message || "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <img
            className="login-mark"
            src={CONTENTFLOW_LOGO}
            alt=""
            width={44}
            height={44}
          />
          <div>
            <h1 className="login-title">{PRODUCT.name}</h1>
            <p className="login-subtitle">Sign in to continue</p>
          </div>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="login-username">
            Username
          </label>
          <input
            id="login-username"
            className="login-input"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <label className="login-label" htmlFor="login-password">
            Password
          </label>
          <div className="login-password-wrap">
            <input
              id="login-password"
              className="login-input login-input--password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              className="login-password-toggle"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
              title={showPassword ? "Hide password" : "Show password"}
            >
              <IconEye revealed={showPassword} />
            </button>
          </div>

          {error ? (
            <p className="login-error" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            className="btn btn-primary login-submit"
            disabled={submitting}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
