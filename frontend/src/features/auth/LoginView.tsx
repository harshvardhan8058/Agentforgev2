/**
 * `LoginView`: authenticate an Operator (Req 2.1, 2.2, 2.4, 2.6).
 *
 * Submits valid credentials to `POST /auth/login` through the single
 * `apiClient`, stores the returned Access_Token for the Session via
 * `useSession.login` (also remembering it by `org_id` for the org switcher),
 * and routes into the console. A `401 auth_failed` renders the AppError
 * envelope message via the uniform `ErrorBanner` while keeping the Operator on
 * the login view. Submission is blocked while email or password is empty
 * (Req 2.4), with the missing field flagged and tied to its validation message.
 *
 * Premium UX: a split-screen branded auth surface, a password reveal toggle, an
 * in-button loading state, a non-blocking success toast, keyboard submit
 * (Enter), visible focus rings, and labelled fields tied to validation —
 * WCAG 2.1 AA. Validation appears only after a submit attempt, so a first-time
 * visitor is never shown errors for fields they have not reached yet, and it
 * clears as soon as the field is filled rather than waiting for a second
 * submit. Motion is instant under test.
 */
import type { JSX } from "react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { useSession } from "../../auth/useSession";
import { rememberOrgToken } from "../../auth/orgTokenStore";
import { useToast } from "../../hooks/useToast";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { ErrorBanner } from "../../components/ErrorBanner";
import { AuthLayout } from "./AuthLayout";
import { AuthField, PasswordField } from "./AuthField";

interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

export function LoginView(): JSX.Element {
  const { login } = useSession();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ClientError | null>(null);

  const emailMissing = email.trim().length === 0;
  const passwordMissing = password.length === 0;

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setAttempted(true);
    // Block submission on an empty email or password (Req 2.4).
    if (emailMissing || passwordMissing) return;

    setSubmitting(true);
    setError(null);
    try {
      const data = await runRequest<TokenResponse>(() =>
        apiClient.POST("/auth/login", {
          body: { email: email.trim(), password },
        }),
      );
      rememberOrgToken(data.access_token);
      login(data.access_token);
      toast({ title: "Signed in", tone: "success" });
      navigate("/", { replace: true });
    } catch (err) {
      // On 401 auth_failed (and any other error) show the envelope message and
      // stay on the login view (Req 2.2).
      setError(err as ClientError);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      testId="login-view"
      title="Welcome back"
      subtitle="Sign in to continue to your AgentForge workspace."
      footer={
        <>
          New to AgentForge?{" "}
          <Link
            to="/register"
            className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            Create an account
          </Link>
        </>
      }
    >
      <form className="flex flex-col gap-5" onSubmit={onSubmit} noValidate>
        {error && <ErrorBanner error={error} />}

        <AuthField
          id="login-email"
          label="Email"
          error={attempted && emailMissing ? "Enter your email to continue." : null}
        >
          {(wiring) => (
            <Input
              {...wiring}
              name="email"
              type="email"
              autoComplete="email"
              // Focusing the first field on a dedicated single-purpose auth page
              // is an expected pattern and not a WCAG failure.
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="h-11"
            />
          )}
        </AuthField>

        <PasswordField
          id="login-password"
          label="Password"
          error={
            attempted && passwordMissing ? "Enter your password to continue." : null
          }
          name="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter your password"
        />

        <Button
          type="submit"
          size="lg"
          loading={submitting}
          disabled={submitting}
          className="mt-1 w-full"
          data-testid="login-submit"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
