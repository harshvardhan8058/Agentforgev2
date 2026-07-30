/**
 * `EvaluationsView`: the evaluation datasets + runs surface (`/evaluations`,
 * Req 14.1–14.5, 4.2).
 *
 * Creates datasets (`POST /evaluations/datasets`, gated behind `run_agents`)
 * showing the returned `dataset_id`; lists datasets (`GET /evaluations/datasets`)
 * with name + created-at; creates runs (`POST /evaluations/runs`, gated) with a
 * `dataset_id` + evaluators showing the aggregate + per-item scores; and opens
 * a persisted run (`GET /evaluations/runs/{id}`) showing `aggregate_score` +
 * per-item scores. A `404` presents the run as not found.
 */
import type { JSX } from "react";
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Plus } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { ExampleChips } from "../../components/ui/ExampleChips";
import { Skeleton } from "../../components/ui/Skeleton";
import { DATASET_NAME_EXAMPLES, EVALUATOR_EXAMPLES } from "../../lib/examples";
import { ScoreBars } from "./ScoreBars";
import {
  DatasetItemsEditor,
  emptyItem,
  toRequestItems,
  type DraftItem,
} from "./DatasetItemsEditor";

interface DatasetSummary {
  dataset_id: string;
  name: string;
  created_at: string;
  /** How many items the dataset holds; 0 means a run over it scores nothing. */
  item_count: number;
}
interface EvaluationItemScore {
  item_id: string;
  evaluator: string;
  score: number;
}
interface EvaluationRunResponse {
  run_id: string;
  dataset_id: string;
  aggregate_score: number;
  results: EvaluationItemScore[];
}

export function EvaluationsView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const canRun = role !== null && can(role, "run_agents");
  const datasetNameRef = useRef<HTMLInputElement>(null);

  const [datasetName, setDatasetName] = useState("");
  const [datasetItems, setDatasetItems] = useState<DraftItem[]>([emptyItem()]);
  const [runDatasetId, setRunDatasetId] = useState("");
  const [evaluators, setEvaluators] = useState("");
  const [viewRunId, setViewRunId] = useState("");
  const [openRunId, setOpenRunId] = useState<string | null>(null);

  const datasets = useQuery<DatasetSummary[], ClientError>({
    queryKey: orgScopedKey(orgId, "eval-datasets"),
    queryFn: () => runRequest<DatasetSummary[]>(() => apiClient.GET("/evaluations/datasets")),
  });

  const runDetail = useQuery<EvaluationRunResponse, ClientError>({
    enabled: openRunId !== null,
    retry: false,
    queryKey: orgScopedKey(orgId, "eval-run", openRunId),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/evaluations/runs/{run_id}", {
          params: { path: { run_id: openRunId as string } },
        }),
      );
      return { ...data, results: data.results ?? [] };
    },
  });

  const createDataset = useMutation<{ dataset_id: string; name: string }, ClientError, void>({
    mutationFn: () =>
      runRequest(() =>
        apiClient.POST("/evaluations/datasets", {
          // The items the operator actually entered. This used to be a hardcoded
          // empty list, which made every dataset unusable: a run scores each item
          // in the dataset, so zero items meant zero results and an aggregate of 0.
          body: { name: datasetName.trim(), items: toRequestItems(datasetItems) },
        }),
      ),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: orgScopedKey(orgId, "eval-datasets") });
      // Select the new dataset for the run form: it is invariably the one the
      // operator wants next, and its id is otherwise only obtainable by reading
      // it back off the list and retyping it.
      setRunDatasetId(created.dataset_id);
    },
  });

  const createRun = useMutation<EvaluationRunResponse, ClientError, void>({
    mutationFn: async () => {
      const data = await runRequest(() =>
        apiClient.POST("/evaluations/runs", {
          body: {
            dataset_id: runDatasetId.trim(),
            evaluators: evaluators
              .split(",")
              .map((e) => e.trim())
              .filter((e) => e.length > 0),
          },
        }),
      );
      return { ...data, results: data.results ?? [] };
    },
  });

  const datasetList = datasets.data ?? [];
  const runResult = createRun.data;
  const detail = runDetail.data;

  return (
    <div className="flex flex-col gap-6" data-testid="evaluations-view">
      <PageHeader
        eyebrow="Platform"
        icon={ClipboardList}
        title="Evaluations"
        description="Create datasets, run evaluators, and inspect scores."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Datasets: create + list. */}
        <div className="flex flex-col gap-4">
          <Can permission="run_agents">
            <Card data-testid="create-dataset-card">
              <CardHeader>
                <CardTitle className="text-base">New dataset</CardTitle>
              </CardHeader>
              <CardContent>
                <form
                  className="flex flex-col gap-3"
                  data-testid="create-dataset-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (datasetName.trim().length === 0) return;
                    createDataset.mutate();
                  }}
                >
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="dataset-name" className="text-sm font-medium text-text">
                      Name
                    </label>
                    <Input
                      id="dataset-name"
                      data-testid="dataset-name"
                      ref={datasetNameRef}
                      value={datasetName}
                      onChange={(e) => setDatasetName(e.target.value)}
                      placeholder="Onboarding policy QA"
                    />
                    <ExampleChips
                      examples={DATASET_NAME_EXAMPLES}
                      onPick={setDatasetName}
                      testId="dataset-name-examples"
                    />
                  </div>

                  <DatasetItemsEditor
                    items={datasetItems}
                    onChange={setDatasetItems}
                  />
                  <div>
                    <Button type="submit" data-testid="create-dataset-submit" loading={createDataset.isPending}>
                      Create dataset
                    </Button>
                  </div>
                  {createDataset.isError && (
                    <div data-testid="create-dataset-error">
                      <ErrorBanner error={createDataset.error} />
                    </div>
                  )}
                  {createDataset.data && (
                    <p className="text-sm text-success" data-testid="create-dataset-result">
                      Created dataset {createDataset.data.dataset_id}
                    </p>
                  )}
                </form>
              </CardContent>
            </Card>
          </Can>

          <Card data-testid="dataset-list-card">
            <CardHeader>
              <CardTitle className="text-base">Datasets</CardTitle>
            </CardHeader>
            <CardContent>
              {datasets.isLoading && <Skeleton className="h-24 w-full" data-testid="datasets-skeleton" />}
              {datasets.isError && <ErrorBanner error={datasets.error} onRetry={() => void datasets.refetch()} />}
              {datasets.data && datasetList.length === 0 && (
                <div data-testid="datasets-empty">
                  <EmptyState
                    title="No datasets yet"
                    message="Create a dataset to start measuring answer quality against curated examples."
                    icon={<ClipboardList className="h-8 w-8" />}
                    action={
                      canRun ? (
                        <Button
                          type="button"
                          data-testid="datasets-empty-cta"
                          onClick={() => datasetNameRef.current?.focus()}
                        >
                          <Plus className="h-4 w-4" aria-hidden="true" />
                          New dataset
                        </Button>
                      ) : undefined
                    }
                  />
                </div>
              )}
              {datasetList.length > 0 && (
                <ul className="flex flex-col gap-2" data-testid="dataset-list">
                  {datasetList.map((d) => (
                    <li
                      key={d.dataset_id}
                      data-testid={`dataset-${d.dataset_id}`}
                      className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2"
                    >
                      <span className="text-sm font-medium text-text" data-testid="dataset-name-cell">
                        {d.name}
                      </span>
                      <span className="flex items-center gap-2">
                        {/* An empty dataset can only ever score 0, so it is called
                            out rather than looking like any other row. */}
                        <Badge
                          tone={d.item_count > 0 ? "neutral" : "warning"}
                          data-testid="dataset-item-count-badge"
                        >
                          {d.item_count > 0
                            ? `${d.item_count} item${d.item_count === 1 ? "" : "s"}`
                            : "empty"}
                        </Badge>
                        <span className="text-xs text-text-muted" data-testid="dataset-created-at">
                          {d.created_at}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Runs: create + open + detail. */}
        <div className="flex flex-col gap-4">
          <Can permission="run_agents">
            <Card data-testid="create-run-card">
              <CardHeader>
                <CardTitle className="text-base">New run</CardTitle>
              </CardHeader>
              <CardContent>
                <form
                  className="flex flex-col gap-3"
                  data-testid="create-run-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (runDatasetId.trim().length === 0) return;
                    createRun.mutate();
                  }}
                >
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="run-dataset-id" className="text-sm font-medium text-text">
                      Dataset id
                    </label>
                    <Input
                      id="run-dataset-id"
                      data-testid="run-dataset-id"
                      value={runDatasetId}
                      onChange={(e) => setRunDatasetId(e.target.value)}
                      placeholder="Pick a dataset below, or paste an id"
                    />
                    {/* A dataset id is a generated identifier, so requiring it to
                        be transcribed by hand from the list alongside was the
                        single worst interaction in this view. These chips are
                        built from the datasets that actually exist. */}
                    {datasetList.length > 0 && (
                      <ExampleChips
                        label="Your datasets"
                        examples={datasetList.map((d) => ({
                          label: d.name,
                          value: d.dataset_id,
                        }))}
                        onPick={setRunDatasetId}
                        testId="run-dataset-id-examples"
                      />
                    )}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label htmlFor="run-evaluators" className="text-sm font-medium text-text">
                      Evaluators (comma-separated)
                    </label>
                    <Input
                      id="run-evaluators"
                      data-testid="run-evaluators"
                      value={evaluators}
                      onChange={(e) => setEvaluators(e.target.value)}
                      placeholder="exact_match, contains, heuristic"
                    />
                    {/* The three deterministic evaluators the platform registers;
                        nothing in the UI otherwise reveals the valid names. */}
                    <ExampleChips
                      examples={EVALUATOR_EXAMPLES}
                      onPick={setEvaluators}
                      testId="run-evaluators-examples"
                    />
                  </div>
                  <div>
                    <Button type="submit" data-testid="create-run-submit" loading={createRun.isPending}>
                      Run evaluation
                    </Button>
                  </div>
                  {createRun.isError && (
                    <div data-testid="create-run-error">
                      <ErrorBanner error={createRun.error} />
                    </div>
                  )}
                  {runResult && (
                    <div className="flex flex-col gap-2" data-testid="run-result">
                      <p className="text-sm text-text" data-testid="run-aggregate">
                        Aggregate score: {runResult.aggregate_score}
                      </p>
                      <ScoreBars
                        aggregate={runResult.aggregate_score}
                        results={runResult.results}
                        testId="run-result-scores"
                      />
                    </div>
                  )}
                </form>
              </CardContent>
            </Card>
          </Can>

          <Card data-testid="open-run-card">
            <CardHeader>
              <CardTitle className="text-base">Open a run</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                className="flex items-end gap-3"
                data-testid="open-run-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (viewRunId.trim().length === 0) return;
                  setOpenRunId(viewRunId.trim());
                }}
              >
                <div className="flex flex-1 flex-col gap-1.5">
                  <label htmlFor="view-run-id" className="text-sm font-medium text-text">
                    Run id
                  </label>
                  <Input
                    id="view-run-id"
                    data-testid="view-run-id"
                    value={viewRunId}
                    onChange={(e) => setViewRunId(e.target.value)}
                    placeholder="Paste a run id"
                  />
                </div>
                <Button type="submit" data-testid="open-run-submit">
                  Open
                </Button>
              </form>

              {/* The run just created is the one an Operator almost always wants
                  to open next, and its id is otherwise only readable from the
                  panel alongside. */}
              {runResult && (
                <div className="mt-2">
                  <ExampleChips
                    label="Last run"
                    examples={[
                      { label: runResult.run_id, value: runResult.run_id },
                    ]}
                    onPick={setViewRunId}
                    testId="view-run-id-examples"
                  />
                </div>
              )}

              {runDetail.isLoading && openRunId !== null && (
                <Skeleton className="mt-3 h-24 w-full" data-testid="run-detail-skeleton" />
              )}
              {runDetail.isError && (
                <div className="mt-3" data-testid="run-detail-error">
                  <ErrorBanner error={runDetail.error} />
                </div>
              )}
              {detail && (
                <div className="mt-3 flex flex-col gap-2" data-testid="run-detail">
                  <p className="text-sm text-text" data-testid="run-detail-aggregate">
                    Aggregate score: {detail.aggregate_score}
                  </p>
                  <ScoreBars
                    aggregate={detail.aggregate_score}
                    results={detail.results}
                    testId="run-detail-scores"
                  />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
