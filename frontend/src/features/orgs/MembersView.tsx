/**
 * `MembersView`: org member & team administration, gated behind `manage_members`
 * (Req 4.4, 1.6).
 *
 * Binds to the full `/orgs/*` administrative contract:
 *  - `GET    /orgs/{org_id}/members`                            — the roster (email + role)
 *  - `POST   /orgs/{org_id}/members`                            — add an existing user by email
 *  - `PATCH  /orgs/{org_id}/members/{user_id}`                  — reassign a member's role
 *  - `DELETE /orgs/{org_id}/members/{user_id}`                  — remove a member
 *  - `GET|POST /orgs/{org_id}/teams`                            — list / create teams
 *  - `DELETE /orgs/{org_id}/teams/{team_id}`                    — delete a team
 *  - `GET|POST /orgs/{org_id}/teams/{team_id}/members`           — list / add team members
 *  - `DELETE /orgs/{org_id}/teams/{team_id}/members/{user_id}`   — remove a team member
 *
 * Every list is server state keyed through `orgScopedKey`, so switching the
 * active Org_Context re-scopes and re-fetches the roster rather than showing a
 * previous tenant's members. Mutations invalidate exactly the lists they can
 * change.
 *
 * All controls sit inside `<Can permission="manage_members">`, so a Session Role
 * without the permission has them **absent from the DOM**, not disabled. The
 * backend refuses a change that would leave the org with no owner
 * (`last_owner`); that response is surfaced verbatim through `ErrorBanner`
 * rather than pre-empted client-side, because the server holds the authoritative
 * roster.
 *
 * Premium UX: skeleton loaders, explicit empty states, destructive-action
 * confirmation dialogs, toasts, responsive two-column layout, WCAG AA.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, UserMinus, UserPlus, Users } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import type { Role } from "../../auth/token";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTrigger,
} from "../../components/ui/Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSelectTrigger,
} from "../../components/ui/DropdownMenu";
import { Input } from "../../components/ui/Input";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatWhen } from "../../lib/formatWhen";
import { MEMBER_EMAIL_EXAMPLES, TEAM_NAME_EXAMPLES } from "../../lib/examples";

const MANAGE_MEMBERS: Permission = "manage_members";
const ASSIGNABLE_ROLES: readonly Role[] = ["owner", "admin", "member", "viewer"];

/**
 * `GET /orgs/{org_id}/members` row (mirrors the generated `MemberSummary`).
 *
 * `email` is absent/null only when no user record backs the membership, which
 * Postgres makes referentially impossible; the row is still rendered.
 */
interface MemberSummary {
  user_id: string;
  email?: string | null;
  role: Role;
  created_at: string;
}

/** `GET /orgs/{org_id}/teams` row. */
interface TeamSummary {
  team_id: string;
  name: string;
  created_at: string;
}

/** `POST /orgs/{org_id}/members` response — the roster is refetched for the rest. */
interface AddMemberResponse {
  user_id: string;
  org_id: string;
  role: Role;
}

/**
 * `POST /orgs/{org_id}/teams` response — the same fields as a `TeamSummary` row,
 * so the created team can be placed into the cached list immediately.
 */
type CreateTeamResponse = TeamSummary;

/** `POST /orgs/{org_id}/teams/{team_id}/members` response. */
interface AddTeamMemberResponse {
  team_id: string;
  user_id: string;
}

/** `GET /orgs/{org_id}/teams/{team_id}/members` row. */
interface TeamMemberSummary {
  user_id: string;
  email?: string | null;
  created_at: string;
}

/** A member whose display name could not be resolved still shows as a row. */
function displayName(email: string | null | undefined): string {
  return email ?? "Unknown user";
}

export function MembersView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const permitted = role !== null && can(role, MANAGE_MEMBERS);
  const enabled = permitted && orgId !== null;

  const [memberEmail, setMemberEmail] = useState("");
  const [memberRole, setMemberRole] = useState<Role>("member");
  const [teamName, setTeamName] = useState("");
  const [teamMemberEmail, setTeamMemberEmail] = useState("");
  const [pickedTeamId, setPickedTeamId] = useState<string | null>(null);

  const membersKey = orgScopedKey(orgId, "members");
  const teamsKey = orgScopedKey(orgId, "teams");

  const members = useQuery<MemberSummary[], ClientError>({
    queryKey: membersKey,
    enabled,
    queryFn: () =>
      runRequest<MemberSummary[]>(() =>
        apiClient.GET("/orgs/{org_id}/members", {
          params: { path: { org_id: orgId! } },
        }),
      ),
  });

  const teams = useQuery<TeamSummary[], ClientError>({
    queryKey: teamsKey,
    enabled,
    queryFn: () =>
      runRequest<TeamSummary[]>(() =>
        apiClient.GET("/orgs/{org_id}/teams", {
          params: { path: { org_id: orgId! } },
        }),
      ),
  });

  const teamList = teams.data ?? [];
  // Derive the selection instead of syncing it in an effect: a team deleted
  // elsewhere simply falls out of the list and the first remaining team takes
  // over, with no stale id left pointing at a resource that no longer exists.
  //
  // The `teamList[0]` fallback only applies when nothing is picked. Falling back
  // whenever the picked id is merely ABSENT would silently retarget the detail
  // card — and the "Add to team" write inside it — at a different team for as
  // long as the list lagged the selection, which is exactly the state a fresh
  // create produces. `createTeam` therefore seeds the cache rather than relying
  // on the refetch landing first.
  const selectedTeam =
    (pickedTeamId === null
      ? teamList[0]
      : teamList.find((t) => t.team_id === pickedTeamId)) ?? null;
  const selectedTeamId = selectedTeam?.team_id ?? null;
  const teamMembersKey = orgScopedKey(orgId, "team-members", selectedTeamId);

  const teamMembers = useQuery<TeamMemberSummary[], ClientError>({
    queryKey: teamMembersKey,
    enabled: enabled && selectedTeamId !== null,
    queryFn: () =>
      runRequest<TeamMemberSummary[]>(() =>
        apiClient.GET("/orgs/{org_id}/teams/{team_id}/members", {
          params: { path: { org_id: orgId!, team_id: selectedTeamId! } },
        }),
      ),
  });

  function refreshMembers(): void {
    void queryClient.invalidateQueries({ queryKey: membersKey });
  }
  function refreshTeams(): void {
    void queryClient.invalidateQueries({ queryKey: teamsKey });
  }
  function refreshTeamMembers(): void {
    void queryClient.invalidateQueries({ queryKey: teamMembersKey });
  }
  /**
   * Invalidate EVERY team roster in this org (prefix match), for changes whose
   * server-side effect is not confined to the selected team — removing a member
   * drops them from all of the org's teams, so invalidating only the visible one
   * would leave the others showing a member who is gone.
   */
  function refreshAllTeamMembers(): void {
    void queryClient.invalidateQueries({
      queryKey: orgScopedKey(orgId, "team-members"),
    });
  }

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
      refreshMembers();
    },
  });

  const changeRole = useMutation<
    MemberSummary,
    ClientError,
    { userId: string; nextRole: Role }
  >({
    mutationFn: ({ userId, nextRole }) =>
      runRequest<MemberSummary>(() =>
        apiClient.PATCH("/orgs/{org_id}/members/{user_id}", {
          params: { path: { org_id: orgId!, user_id: userId } },
          body: { role: nextRole },
        }),
      ),
    onSuccess: (data) => {
      toast({
        title: "Role updated",
        description: `${displayName(data.email)} is now ${data.role}`,
        tone: "success",
      });
      refreshMembers();
    },
  });

  const removeMember = useMutation<void, ClientError, MemberSummary>({
    mutationFn: (member) =>
      runRequest<void>(() =>
        apiClient.DELETE("/orgs/{org_id}/members/{user_id}", {
          params: { path: { org_id: orgId!, user_id: member.user_id } },
        }),
      ),
    onSuccess: (_data, member) => {
      toast({
        title: "Member removed",
        description: displayName(member.email),
        tone: "success",
      });
      refreshMembers();
      // Removing a member also drops their team memberships server-side — in every
      // team of this org, not just the one on screen.
      refreshAllTeamMembers();
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
    onSuccess: (created) => {
      toast({ title: "Team created", description: created.name, tone: "success" });
      // Place the created team into the cached list before selecting it. Without
      // this the selection would name a team the list does not yet contain, and a
      // failed refetch (queries do not retry) would leave the detail card bound to
      // nothing after a success toast. The server's own values are used — nothing
      // about the row is invented client-side.
      queryClient.setQueryData<TeamSummary[]>(teamsKey, (current) =>
        current === undefined
          ? [created]
          : current.some((t) => t.team_id === created.team_id)
            ? current
            : [...current, created],
      );
      setPickedTeamId(created.team_id);
      setTeamName("");
      refreshTeams();
    },
  });

  const deleteTeam = useMutation<void, ClientError, TeamSummary>({
    mutationFn: (team) =>
      runRequest<void>(() =>
        apiClient.DELETE("/orgs/{org_id}/teams/{team_id}", {
          params: { path: { org_id: orgId!, team_id: team.team_id } },
        }),
      ),
    onSuccess: (_data, team) => {
      toast({ title: "Team deleted", description: team.name, tone: "success" });
      // Drop the selection so it falls back to the first remaining team rather
      // than naming a team that no longer exists.
      if (pickedTeamId === null || pickedTeamId === team.team_id) {
        setPickedTeamId(null);
      }
      queryClient.setQueryData<TeamSummary[]>(teamsKey, (current) =>
        current?.filter((t) => t.team_id !== team.team_id),
      );
      refreshTeams();
      refreshAllTeamMembers();
    },
  });

  const addTeamMember = useMutation<AddTeamMemberResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<AddTeamMemberResponse>(() =>
        apiClient.POST("/orgs/{org_id}/teams/{team_id}/members", {
          params: { path: { org_id: orgId!, team_id: selectedTeamId! } },
          body: { email: teamMemberEmail.trim() },
        }),
      ),
    onSuccess: () => {
      toast({
        title: "Added to team",
        description: teamMemberEmail.trim(),
        tone: "success",
      });
      setTeamMemberEmail("");
      refreshTeamMembers();
    },
  });

  const removeTeamMember = useMutation<void, ClientError, TeamMemberSummary>({
    mutationFn: (member) =>
      runRequest<void>(() =>
        apiClient.DELETE("/orgs/{org_id}/teams/{team_id}/members/{user_id}", {
          params: {
            path: {
              org_id: orgId!,
              team_id: selectedTeamId!,
              user_id: member.user_id,
            },
          },
        }),
      ),
    onSuccess: (_data, member) => {
      toast({
        title: "Removed from team",
        description: displayName(member.email),
        tone: "success",
      });
      refreshTeamMembers();
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

  const roster = members.data ?? [];

  return (
    <div className="flex flex-col gap-6" data-testid="members-view">
      <PageHeader
        eyebrow="Administration"
        icon={Users}
        title="Members & Teams"
        description="Add and remove organization members, change their roles, and organize them into teams."
      />

      <Can permission={MANAGE_MEMBERS}>
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)]">
          {/* --- left column: creation forms ---
              The section heading is not decoration: the cards below carry <h3>
              titles, so without an <h2> here the document would jump h1 -> h3
              (axe `heading-order`, WCAG 1.3.1). */}
          <section
            className="flex flex-col gap-3"
            aria-labelledby="provisioning-heading"
          >
            <h2
              id="provisioning-heading"
              className="text-sm font-semibold uppercase tracking-wide text-text-muted"
            >
              Add members &amp; teams
            </h2>
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
                    <DropdownMenuSelectTrigger
                      id="member-role"
                      data-testid="member-role-trigger"
                      className="w-40 capitalize"
                      value={memberRole}
                    />
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
          </section>

          {/* --- right column: the roster and team detail --- */}
          <div className="flex min-w-0 flex-col gap-6">
            <section className="flex flex-col gap-3" aria-labelledby="roster-heading">
              <h2
                id="roster-heading"
                className="text-sm font-semibold uppercase tracking-wide text-text-muted"
              >
                Organization members
              </h2>

              {members.isError && (
                <ErrorBanner error={members.error} onRetry={() => members.refetch()} />
              )}

              {members.isLoading && (
                <div className="flex flex-col gap-2" data-testid="members-loading">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              )}

              {!members.isLoading && !members.isError && roster.length === 0 && (
                <EmptyState
                  title="No members yet"
                  message="Add an existing user by email to give them access to this organization."
                  icon={<Users className="h-8 w-8" />}
                />
              )}

              {roster.length > 0 && (
                <ul className="flex flex-col gap-2" data-testid="members-list">
                  {roster.map((member) => (
                    <li key={member.user_id}>
                      <Card>
                        <CardContent className="flex flex-wrap items-center gap-3 py-4">
                          <span className="truncate text-sm font-medium text-text">
                            {displayName(member.email)}
                          </span>
                          <Badge tone="primary" className="capitalize">
                            {member.role}
                          </Badge>
                          <span className="text-xs text-text-muted">
                            joined {formatWhen(member.created_at)}
                          </span>
                          <span className="ml-auto" />
                          <DropdownMenu>
                            <DropdownMenuSelectTrigger
                              aria-label={`Change role for ${displayName(member.email)}`}
                              data-testid={`member-role-trigger-${member.user_id}`}
                              className="w-32 capitalize"
                              value={member.role}
                            />
                            <DropdownMenuContent>
                              {ASSIGNABLE_ROLES.map((r) => (
                                <DropdownMenuItem
                                  key={r}
                                  data-testid={`set-role-${member.user_id}-${r}`}
                                  onSelect={() =>
                                    r !== member.role &&
                                    changeRole.mutate({
                                      userId: member.user_id,
                                      nextRole: r,
                                    })
                                  }
                                >
                                  <span className="capitalize">{r}</span>
                                </DropdownMenuItem>
                              ))}
                            </DropdownMenuContent>
                          </DropdownMenu>
                          <Dialog>
                            <DialogTrigger asChild>
                              <Button
                                type="button"
                                variant="danger"
                                size="sm"
                                data-testid={`remove-member-${member.user_id}`}
                              >
                                <UserMinus className="h-4 w-4" aria-hidden="true" />
                                Remove
                              </Button>
                            </DialogTrigger>
                            <DialogContent
                              title="Remove member?"
                              description={`${displayName(member.email)} loses access to this organization and is removed from its teams. Their account and other organizations are unaffected.`}
                            >
                              <div className="flex justify-end gap-2">
                                <DialogClose asChild>
                                  <Button type="button" variant="secondary" size="sm">
                                    Cancel
                                  </Button>
                                </DialogClose>
                                <DialogClose asChild>
                                  <Button
                                    type="button"
                                    variant="danger"
                                    size="sm"
                                    data-testid={`confirm-remove-member-${member.user_id}`}
                                    onClick={() => removeMember.mutate(member)}
                                  >
                                    Remove member
                                  </Button>
                                </DialogClose>
                              </div>
                            </DialogContent>
                          </Dialog>
                        </CardContent>
                      </Card>
                    </li>
                  ))}
                </ul>
              )}

              {changeRole.isError && <ErrorBanner error={changeRole.error} />}
              {removeMember.isError && <ErrorBanner error={removeMember.error} />}
            </section>

            <section className="flex flex-col gap-3" aria-labelledby="teams-heading">
              <h2
                id="teams-heading"
                className="text-sm font-semibold uppercase tracking-wide text-text-muted"
              >
                Teams
              </h2>

              {teams.isError && (
                <ErrorBanner error={teams.error} onRetry={() => teams.refetch()} />
              )}

              {teams.isLoading && (
                <div className="flex flex-col gap-2" data-testid="teams-loading">
                  <Skeleton className="h-10 w-full" />
                </div>
              )}

              {!teams.isLoading && !teams.isError && teamList.length === 0 && (
                <EmptyState
                  title="No teams yet"
                  message="Create a team to group members by function or project."
                  icon={<Users className="h-8 w-8" />}
                />
              )}

              {teamList.length > 0 && (
                <>
                  <ul
                    className="flex flex-wrap gap-2"
                    data-testid="teams-list"
                    aria-label="Teams"
                  >
                    {teamList.map((team) => {
                      const active = team.team_id === selectedTeamId;
                      return (
                        <li key={team.team_id}>
                          <Button
                            type="button"
                            variant={active ? "primary" : "secondary"}
                            size="sm"
                            aria-pressed={active}
                            data-testid={`team-tab-${team.team_id}`}
                            onClick={() => setPickedTeamId(team.team_id)}
                          >
                            {team.name}
                          </Button>
                        </li>
                      );
                    })}
                  </ul>

                  {selectedTeam && (
                    <Card data-testid="team-detail-card">
                      <CardHeader className="flex flex-row items-center justify-between gap-3">
                        <CardTitle>{selectedTeam.name}</CardTitle>
                        <Dialog>
                          <DialogTrigger asChild>
                            <Button
                              type="button"
                              variant="danger"
                              size="sm"
                              data-testid={`delete-team-${selectedTeam.team_id}`}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                              Delete team
                            </Button>
                          </DialogTrigger>
                          <DialogContent
                            title="Delete team?"
                            description={`"${selectedTeam.name}" and its member assignments are removed. The members themselves keep their organization access.`}
                          >
                            <div className="flex justify-end gap-2">
                              <DialogClose asChild>
                                <Button type="button" variant="secondary" size="sm">
                                  Cancel
                                </Button>
                              </DialogClose>
                              <DialogClose asChild>
                                <Button
                                  type="button"
                                  variant="danger"
                                  size="sm"
                                  data-testid={`confirm-delete-team-${selectedTeam.team_id}`}
                                  onClick={() => deleteTeam.mutate(selectedTeam)}
                                >
                                  Delete team
                                </Button>
                              </DialogClose>
                            </div>
                          </DialogContent>
                        </Dialog>
                      </CardHeader>
                      <CardContent className="flex flex-col gap-4">
                        <div className="flex flex-col gap-1.5">
                          <label
                            htmlFor="team-member-email"
                            className="text-sm font-medium text-text"
                          >
                            Add a member to this team
                          </label>
                          <div className="flex flex-wrap items-start gap-2">
                            <Input
                              id="team-member-email"
                              type="email"
                              className="min-w-[14rem] flex-1"
                              value={teamMemberEmail}
                              onChange={(e) => setTeamMemberEmail(e.target.value)}
                              placeholder="teammate@company.com"
                            />
                            <Button
                              type="button"
                              data-testid="add-team-member-submit"
                              loading={addTeamMember.isPending}
                              disabled={teamMemberEmail.trim().length === 0}
                              onClick={() => addTeamMember.mutate()}
                            >
                              <UserPlus className="h-4 w-4" aria-hidden="true" />
                              Add to team
                            </Button>
                          </div>
                          <ExampleChips
                            examples={MEMBER_EMAIL_EXAMPLES}
                            onPick={setTeamMemberEmail}
                            testId="team-member-email-examples"
                          />
                        </div>

                        {teamMembers.isError && (
                          <ErrorBanner
                            error={teamMembers.error}
                            onRetry={() => teamMembers.refetch()}
                          />
                        )}

                        {teamMembers.isLoading && (
                          <Skeleton className="h-10 w-full" />
                        )}

                        {!teamMembers.isLoading &&
                          !teamMembers.isError &&
                          (teamMembers.data ?? []).length === 0 && (
                            <p
                              className="text-sm text-text-muted"
                              data-testid="team-members-empty"
                            >
                              No members in this team yet.
                            </p>
                          )}

                        {(teamMembers.data ?? []).length > 0 && (
                          <ul
                            className="flex flex-col divide-y divide-border"
                            data-testid="team-members-list"
                          >
                            {(teamMembers.data ?? []).map((member) => (
                              <li
                                key={member.user_id}
                                className="flex flex-wrap items-center gap-3 py-2"
                              >
                                <span className="truncate text-sm text-text">
                                  {displayName(member.email)}
                                </span>
                                <span className="text-xs text-text-muted">
                                  added {formatWhen(member.created_at)}
                                </span>
                                <span className="ml-auto" />
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  data-testid={`remove-team-member-${member.user_id}`}
                                  onClick={() => removeTeamMember.mutate(member)}
                                >
                                  <UserMinus className="h-4 w-4" aria-hidden="true" />
                                  Remove
                                </Button>
                              </li>
                            ))}
                          </ul>
                        )}

                        {addTeamMember.isError && (
                          <ErrorBanner error={addTeamMember.error} />
                        )}
                        {removeTeamMember.isError && (
                          <ErrorBanner error={removeTeamMember.error} />
                        )}
                        {deleteTeam.isError && <ErrorBanner error={deleteTeam.error} />}
                      </CardContent>
                    </Card>
                  )}
                </>
              )}
            </section>
          </div>
        </div>
      </Can>
    </div>
  );
}
