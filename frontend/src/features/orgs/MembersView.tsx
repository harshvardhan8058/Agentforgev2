/**
 * `MembersView`: org member & team management, gated behind `manage_members`
 * (Req 4.4, 1.6).
 *
 * Binds ONLY to the shipped `/orgs/*` contracts that exist in the OpenAPI
 * schema:
 *  - `POST /orgs/{org_id}/members`                    — add an existing user by email under a Role
 *  - `POST /orgs/{org_id}/teams`                      — create an org-scoped team
 *  - `POST /orgs/{org_id}/teams/{team_id}/members`    — add a user to a team by email
 *
 * The backend ships **no** list/update/remove member or team contracts, so —
 * per Req 1.6 — this view deliberately OMITS listing, editing, and removing
 * members/teams rather than inventing a capability with no contract. Newly
 * created teams are remembered in local component state only (not persisted) so
 * the "add team member" control can target them.
 *
 * All controls are wrapped in `<Can permission="manage_members">`, so when the
 * Session Role lacks the permission they are absent from the DOM.
 *
 * Premium UX: cards, toasts, confirm feedback, responsive layout, WCAG AA.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, UserPlus, Users } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { can, type Permission } from "../../auth/rbac";
import type { Role } from "../../auth/token";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { MEMBER_EMAIL_EXAMPLES, TEAM_NAME_EXAMPLES } from "../../lib/examples";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../components/ui/DropdownMenu";

const MANAGE_MEMBERS: Permission = "manage_members";
const ASSIGNABLE_ROLES: readonly Role[] = ["owner", "admin", "member", "viewer"];

interface CreatedTeam {
  team_id: string;
  name: string;
}

interface AddMemberResponse {
  org_id: string;
  role: Role;
  user_id: string;
}
interface CreateTeamResponse {
  name: string;
  team_id: string;
}
interface AddTeamMemberResponse {
  team_id: string;
  user_id: string;
}

export function MembersView(): JSX.Element {
  const { orgId, role } = useSession();
  const { toast } = useToast();
  const permitted = role !== null && can(role, MANAGE_MEMBERS);

  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<Role>("member");
  const [teamName, setTeamName] = useState("");
  const [teams, setTeams] = useState<CreatedTeam[]>([]);
  const [teamMemberEmail, setTeamMemberEmail] = useState("");
  const [selectedTeamId, setSelectedTeamId] = useState<string>("");

  const addMember = useMutation<AddMemberResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<AddMemberResponse>(() =>
        apiClient.POST("/orgs/{org_id}/members", {
          params: { path: { org_id: orgId! } },
          body: { email: memberEmail.trim(), role: memberRole },
        }),
      ),
    onSuccess: () => {
      toast({ title: "Member added", description: memberEmail.trim(), tone: "success" });
      setMemberEmail("");
    },
  });

  const createTeam = useMutation<CreateTeamResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<CreateTeamResponse>(() =>
        apiClient.POST("/orgs/{org_id}/teams", {
          params: { path: { org_id: orgId! } },
          body: { name: teamName.trim() },
        }),
      ),
    onSuccess: (data) => {
      toast({ title: "Team created", description: data.name, tone: "success" });
      setTeams((current) => [...current, { team_id: data.team_id, name: data.name }]);
      if (selectedTeamId === "") setSelectedTeamId(data.team_id);
      setTeamName("");
    },
  });

  const addTeamMember = useMutation<AddTeamMemberResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<AddTeamMemberResponse>(() =>
        apiClient.POST("/orgs/{org_id}/teams/{team_id}/members", {
          params: { path: { org_id: orgId!, team_id: selectedTeamId } },
          body: { email: teamMemberEmail.trim() },
        }),
      ),
    onSuccess: () => {
      toast({ title: "Added to team", description: teamMemberEmail.trim(), tone: "success" });
      setTeamMemberEmail("");
    },
  });

  if (!permitted) {
    return (
      <div data-testid="members-view">
        <EmptyState
          title="Member management unavailable"
          message="Your role does not permit managing members or teams for this organization."
          icon={<Users className="h-8 w-8" />}
        />
      </div>
    );
  }

  const selectedTeam = teams.find((t) => t.team_id === selectedTeamId) ?? null;

  return (
    <div className="flex flex-col gap-6" data-testid="members-view">
      <PageHeader
        eyebrow="Administration"
        icon={Users}
        title="Members & Teams"
        description="Add members to your organization, create teams, and assign members to teams."
      />

      <Can permission={MANAGE_MEMBERS}>
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Add member */}
          <Card data-testid="add-member-card">
            <CardHeader>
              <CardTitle>Add a member</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="member-email" className="text-sm font-medium text-text">
                  Email
                </label>
                <Input
                  id="member-email"
                  type="email"
                  value={memberEmail}
                  onChange={(e) => setMemberEmail(e.target.value)}
                  placeholder="teammate@company.com"
                />
                <ExampleChips
                  examples={MEMBER_EMAIL_EXAMPLES}
                  onPick={setMemberEmail}
                  testId="member-email-examples"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="member-role" className="text-sm font-medium text-text">
                  Role
                </label>
                <DropdownMenu>
                  <DropdownMenuTrigger
                    id="member-role"
                    data-testid="member-role-trigger"
                    className="inline-flex h-10 w-40 items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-sm capitalize text-text hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                  >
                    {memberRole}
                  </DropdownMenuTrigger>
                  <DropdownMenuContent>
                    {ASSIGNABLE_ROLES.map((r) => (
                      <DropdownMenuItem
                        key={r}
                        data-testid={`member-role-${r}`}
                        onSelect={() => setMemberRole(r)}
                      >
                        <span className="capitalize">{r}</span>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <Button
                type="button"
                data-testid="add-member-submit"
                loading={addMember.isPending}
                disabled={memberEmail.trim().length === 0}
                onClick={() => addMember.mutate()}
              >
                <UserPlus className="h-4 w-4" aria-hidden="true" />
                Add member
              </Button>
              {addMember.isError && <ErrorBanner error={addMember.error} />}
            </CardContent>
          </Card>

          {/* Create team */}
          <Card data-testid="create-team-card">
            <CardHeader>
              <CardTitle>Create a team</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="team-name" className="text-sm font-medium text-text">
                  Team name
                </label>
                <Input
                  id="team-name"
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  placeholder="Platform"
                />
                <ExampleChips
                  examples={TEAM_NAME_EXAMPLES}
                  onPick={setTeamName}
                  testId="team-name-examples"
                />
              </div>
              <Button
                type="button"
                data-testid="create-team-submit"
                loading={createTeam.isPending}
                disabled={teamName.trim().length === 0}
                onClick={() => createTeam.mutate()}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Create team
              </Button>
              {createTeam.isError && <ErrorBanner error={createTeam.error} />}
            </CardContent>
          </Card>

          {/* Add team member */}
          <Card data-testid="add-team-member-card">
            <CardHeader>
              <CardTitle>Add a member to a team</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {teams.length === 0 ? (
                <p className="text-sm text-text-muted">
                  Create a team first to assign members to it.
                </p>
              ) : (
                <>
                  <div className="flex flex-col gap-1.5">
                    <label
                      htmlFor="team-select"
                      className="text-sm font-medium text-text"
                    >
                      Team
                    </label>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        id="team-select"
                        data-testid="team-select-trigger"
                        className="inline-flex h-10 min-w-[10rem] items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-sm text-text hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                      >
                        {selectedTeam ? selectedTeam.name : "Select a team"}
                      </DropdownMenuTrigger>
                      <DropdownMenuContent>
                        {teams.map((t) => (
                          <DropdownMenuItem
                            key={t.team_id}
                            data-testid={`team-option-${t.team_id}`}
                            onSelect={() => setSelectedTeamId(t.team_id)}
                          >
                            {t.name}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label
                      htmlFor="team-member-email"
                      className="text-sm font-medium text-text"
                    >
                      Email
                    </label>
                    <Input
                      id="team-member-email"
                      type="email"
                      value={teamMemberEmail}
                      onChange={(e) => setTeamMemberEmail(e.target.value)}
                      placeholder="teammate@company.com"
                    />
                    <ExampleChips
                      examples={MEMBER_EMAIL_EXAMPLES}
                      onPick={setTeamMemberEmail}
                      testId="team-member-email-examples"
                    />
                  </div>
                  <Button
                    type="button"
                    data-testid="add-team-member-submit"
                    loading={addTeamMember.isPending}
                    disabled={
                      teamMemberEmail.trim().length === 0 || selectedTeamId === ""
                    }
                    onClick={() => addTeamMember.mutate()}
                  >
                    <UserPlus className="h-4 w-4" aria-hidden="true" />
                    Add to team
                  </Button>
                  {addTeamMember.isError && <ErrorBanner error={addTeamMember.error} />}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </Can>
    </div>
  );
}
