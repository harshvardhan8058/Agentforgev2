/**
 * `RegisterView`: self-registration bootstrapping a new Organization + owner
 * (Req 2.3, 2.4, 2.6).
 *
 * Submits the self-registration form to `POST /auth/register-self` through the
 * single `apiClient`; on `201` it stores the returned Access_Token for the
 * Session via `useSession.login` (remembering it by `org_id` for the org
 * switcher) and routes into the console. Submission is blocked while any field
 * is empty (Req 2.4), each missing field flagged and tied to its validation
 * message. Any error is surfaced via the uniform `ErrorBanner` while staying on
 * the register view.
 *
 * Premium UX matches `LoginView`: the split-screen branded surface, a password
 * reveal toggle, an in-button loading state, a success toast, keyboard submit
 * and visible focus rings — WCAG 2.1 AA. A strength meter gives feedback while
 * the password is typed; it is advisory only and never blocks submission, since
 * the API owns the actual password policy and the client must not invent a
 * stricter one that would reject a password the backend accepts.
 */
import type { JSX } from "react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { useSession } from "../../auth/useSession";
import { rememberOrgToken } from "../../auth/orgTokenStore";
import { rememberOrgName } from "../../auth/orgNameStore";
import { decodeClaims } from "../../auth/token";
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

/** Advisory password strength on a 0-3 scale, plus a label for the meter. */
function scorePassword(password: string): { score: number; label: string } {
  if (password.length === 0) return { score: 0, label: "" };
  const variety =
    Number(/[a-z]/.test(password)) +
    Number(/[A-Z]/.test(password)) +
    Number(/\d/.test(password)) +
    Number(/[^A-Za-z0-9]/.test(password));
  if (password.length < 8) return { score: 1, label: "Too short" };
  if (password.length >= 14 && variety >= 3) return { score: 3, label: "Strong" };
  if (variety >= 2) return { score: 2, label: "Good" };
  return { score: 1, label: "Weak" };
}

const METER_TONES = ["bg-danger", "bg-warning", "bg-success"] as const;

/** A three-segment strength meter. Presentational; the label carries the text. */
function StrengthMeter({ password }: { password: string }): JSX.Element | null {
  const { score, label } = scorePassword(password);
  if (score === 0) return null;

  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className="flex flex-1 gap-1">
        {[1, 2, 3].map((segment) => (
          <span
            key={segment}
            className={`h-1 flex-1 rounded-full ${
              segment <= score ? METER_TONES[score - 1] : "bg-border"
            }`}
          />
        ))}
      </span>
      <span className="text-xs text-text-muted" aria-live="polite">
        {label}
      </span>
    </div>
  );
}

export function RegisterView(): JSX.Element {
  const { login } = useSession();
  const navigate = useNavigate();
  const { toast } = useToast();

  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ClientError | null>(null);

  const orgMissing = orgName.trim().length === 0;
  const emailMissing = email.trim().length === 0;
  const passwordMissing = password.length === 0;

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setAttempted(true);
    // Block submission while any field is empty (Req 2.4).
    if (orgMissing || emailMissing || passwordMissing) return;

    setSubmitting(true);
    setError(null);
    try {
      const data = await runRequest<TokenResponse>(() =>
        apiClient.POST("/auth/register-self", {
          body: {
            org_name: orgName.trim(),
            email: email.trim(),
            password,
          },
        }),
      );
      rememberOrgToken(data.access_token);
      // Remember the chosen org name so the workspace shows it (not a raw id).
      const claims = decodeClaims(data.access_token);
      if (claims) rememberOrgName(claims.org_id, orgName.trim());
      login(data.access_token);
      toast({ title: "Account created", tone: "success" });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err as ClientError);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      testId="register-view"
      title="Create your workspace"
      subtitle="Set up a new AgentForge organization in seconds. You'll be the owner."
      footer={
        <>
          Already have an account?{" "}
          <Link
            to="/login"
            className="font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          >
            Sign in
          </Link>
        </>
      }
    >
      <form className="flex flex-col gap-5" onSubmit={onSubmit} noValidate>
        {error && <ErrorBanner error={error} />}

        <AuthField
          id="register-org"
          label="Organization name"
          error={
            attempted && orgMissing ? "Enter an organization name to continue." : null
          }
        >
          {(wiring) => (
            <Input
              {...wiring}
              name="org_name"
              // Focusing the first field on a dedicated single-purpose auth page
              // is an expected pattern and not a WCAG failure.
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="Acme Inc."
              className="h-11"
            />
          )}
        </AuthField>

        <AuthField
          id="register-email"
          label="Email"
          error={attempted && emailMissing ? "Enter your email to continue." : null}
        >
          {(wiring) => (
            <Input
              {...wiring}
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="h-11"
            />
          )}
        </AuthField>

        <div className="flex flex-col gap-2">
          <PasswordField
            id="register-password"
            label="Password"
            error={
              attempted && passwordMissing ? "Choose a password to continue." : null
            }
            name="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Choose a strong password"
          />
          <StrengthMeter password={password} />
        </div>

        <Button
          type="submit"
          size="lg"
          loading={submitting}
          disabled={submitting}
          className="mt-1 w-full"
          data-testid="register-submit"
        >
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
