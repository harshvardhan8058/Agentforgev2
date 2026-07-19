/**
 * `DocumentListView`: the org document corpus surface (`/documents`, Req 8.3,
 * 8.4, 8.5, 4.3).
 *
 * Lists `GET /documents` with each document's filename, content type, size,
 * status, chunk count, and created-at. Upload and delete controls are gated
 * behind `ingest_documents` via `<Can>` (Req 4.3) — absent from the DOM when
 * the Role lacks the permission. Delete calls `DELETE /documents/{id}` and,
 * optimistically, removes the row immediately, confirming via a toast and
 * rolling back on error. Skeleton loaders match the final layout; a rich empty
 * state is shown for zero documents; metadata reflows into stacked cards on
 * mobile and a token-spaced table on larger breakpoints.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Trash2 } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { UploadControl } from "./UploadControl";

interface DocumentSummary {
  chunk_count: number;
  content_type: string;
  created_at: string;
  document_id: string;
  filename: string;
  size_bytes: number;
  status: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentListView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const canIngest = role !== null && can(role, "ingest_documents");

  const queryKey = orgScopedKey(orgId, "documents");

  const list = useQuery<DocumentSummary[], ClientError>({
    queryKey,
    queryFn: () =>
      runRequest<DocumentSummary[]>(() => apiClient.GET("/documents")),
  });

  const remove = useMutation<
    void,
    ClientError,
    string,
    { previous: DocumentSummary[] | undefined }
  >({
    mutationFn: (documentId) =>
      runRequest<void>(() =>
        apiClient.DELETE("/documents/{document_id}", {
          params: { path: { document_id: documentId } },
        }),
      ),
    // Optimistic removal: drop the row immediately, rolling back on error.
    onMutate: async (documentId) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<DocumentSummary[]>(queryKey);
      queryClient.setQueryData<DocumentSummary[]>(queryKey, (current) =>
        (current ?? []).filter((d) => d.document_id !== documentId),
      );
      return { previous };
    },
    onError: (error, _documentId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKey, context.previous);
      }
      toast({
        title: "Delete failed",
        description: error.message,
        tone: "danger",
      });
    },
    onSuccess: () => {
      toast({ title: "Document deleted", tone: "success" });
    },
  });

  const documents = list.data ?? [];

  return (
    <div className="flex flex-col gap-6" data-testid="documents-view">
      <PageHeader
        eyebrow="Knowledge"
        icon={FileText}
        title="Documents"
        description="Manage the corpus your grounded queries draw from."
      />

      <Can permission="ingest_documents">
        <UploadControl />
      </Can>

      {list.isError && (
        <div data-testid="documents-error">
          <ErrorBanner error={list.error} onRetry={() => void list.refetch()} />
        </div>
      )}

      {list.isLoading && (
        <div className="flex flex-col gap-3" data-testid="documents-skeleton">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {!list.isLoading && !list.isError && documents.length === 0 && (
        <EmptyState
          title="No documents yet"
          message={
            canIngest
              ? "Upload a document above to start building your corpus."
              : "This organization has no documents yet."
          }
          icon={<FileText className="h-8 w-8" />}
        />
      )}

      {documents.length > 0 && (
        <div
          className="flex flex-col gap-3"
          data-testid="documents-list"
          role="list"
        >
          {documents.map((doc) => (
            <Card
              key={doc.document_id}
              role="listitem"
              data-testid={`document-row-${doc.document_id}`}
            >
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <FileText className="h-4 w-4 text-text-muted" aria-hidden="true" />
                    <span data-testid="document-filename">{doc.filename}</span>
                  </CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge tone="neutral" data-testid="document-status">
                      {doc.status}
                    </Badge>
                    <Can permission="ingest_documents">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete ${doc.filename}`}
                        data-testid={`document-delete-${doc.document_id}`}
                        onClick={() => remove.mutate(doc.document_id)}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </Can>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
                  <div className="flex flex-col">
                    <dt className="text-xs text-text-muted">Content type</dt>
                    <dd className="font-mono text-xs" data-testid="document-content-type">
                      {doc.content_type}
                    </dd>
                  </div>
                  <div className="flex flex-col">
                    <dt className="text-xs text-text-muted">Size</dt>
                    <dd data-testid="document-size">{formatBytes(doc.size_bytes)}</dd>
                  </div>
                  <div className="flex flex-col">
                    <dt className="text-xs text-text-muted">Chunks</dt>
                    <dd data-testid="document-chunk-count">{doc.chunk_count}</dd>
                  </div>
                  <div className="flex flex-col">
                    <dt className="text-xs text-text-muted">Created</dt>
                    <dd data-testid="document-created-at">{doc.created_at}</dd>
                  </div>
                </dl>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
