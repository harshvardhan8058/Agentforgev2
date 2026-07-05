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
 * Premium UX matches `LoginView`: centered glass card, in-button loading state,
 * success toast, keyboard submit, visible focus rings, WCAG 2.1 AA. Motion is
 * instant under test.
 */
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

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

interface TokenResponse {
  access_token: string;
  token_type: "bearer";
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
      subtitle="Set up a new AgentForge organization in seconds."
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
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        {error && <ErrorBanner error={error} />}

        <div className="flex flex-col gap-1.5">
          <label htmlFor="register-org" className="text-sm font-medium text-text">
            Organization name
          </label>
          <Input
            id="register-org"
            name="org_name"
            autoFocus
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
            aria-invalid={attempted && orgMissing}
            aria-describedby={attempted && orgMissing ? "register-org-error" : undefined}
            placeholder="Acme Inc."
          />
          {attempted && orgMissing && (
            <p id="register-org-error" className="text-xs text-danger" role="alert">
              Enter an organization name to continue.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="register-email" className="text-sm font-medium text-text">
            Email
          </label>
          <Input
            id="register-email"
            name="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={attempted && emailMissing}
            aria-describedby={
              attempted && emailMissing ? "register-email-error" : undefined
            }
            placeholder="you@company.com"
          />
          {attempted && emailMissing && (
            <p id="register-email-error" className="text-xs text-danger" role="alert">
              Enter your email to continue.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="register-password" className="text-sm font-medium text-text">
            Password
          </label>
          <Input
            id="register-password"
            name="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={attempted && passwordMissing}
            aria-describedby={
              attempted && passwordMissing ? "register-password-error" : undefined
            }
            placeholder="Choose a strong password"
          />
          {attempted && passwordMissing && (
            <p id="register-password-error" className="text-xs text-danger" role="alert">
              Choose a password to continue.
            </p>
          )}
        </div>

        <Button
          type="submit"
          size="lg"
          loading={submitting}
          disabled={submitting}
          className="mt-2 w-full"
          data-testid="register-submit"
        >
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
