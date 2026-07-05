/**
 * `UploadControl`: the premium document-upload surface (Req 8.1, 8.2, 8.5, 4.3).
 *
 * A drag-and-drop drop-zone with hover/active affordances plus a
 * click-to-browse fallback, uploading via `POST /documents` (multipart) and
 * surfacing the returned `document_id` / `filename` / `chunk_count` / `status`.
 * While a file is in flight a per-file progress indicator is shown. Document
 * error envelopes (413/415/400/422/500) are surfaced uniformly via
 * `ErrorBanner`. The whole control is gated behind `ingest_documents` by its
 * caller (`<Can>`), so it is absent from the DOM when the Role lacks it.
 */
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, UploadCloud } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { useSession } from "../../auth/useSession";
import { orgScopedKey } from "../../api/queryKeys";
import { useToast } from "../../hooks/useToast";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent } from "../../components/ui/Card";
import { cn } from "../../lib/cn";

interface IngestResult {
  chunk_count: number;
  document_id: string;
  filename: string;
  status: string;
}

export function UploadControl(): JSX.Element {
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [lastResult, setLastResult] = useState<IngestResult | null>(null);

  const upload = useMutation<IngestResult, ClientError, File>({
    mutationFn: (file) =>
      runRequest<IngestResult>(() =>
        apiClient.POST("/documents", {
          body: {
            // The generated type models the binary field as a string; at
            // runtime the File is appended to the FormData below.
            file: file as unknown as string,
            filename: file.name,
          },
          bodySerializer: (body: { file: unknown; filename?: string | null }) => {
            const form = new FormData();
            form.append("file", body.file as Blob, file.name);
            if (body.filename) form.append("filename", body.filename);
            return form;
          },
        }),
      ),
    onSuccess: (data) => {
      setLastResult(data);
      toast({
        title: "Document ingested",
        description: `${data.filename} · ${data.chunk_count} chunks`,
        tone: "success",
      });
      void queryClient.invalidateQueries({
        queryKey: orgScopedKey(orgId, "documents"),
      });
    },
  });

  function handleFiles(files: FileList | null): void {
    if (!files || files.length === 0) return;
    upload.mutate(files[0]);
  }

  return (
    <div className="flex flex-col gap-3" data-testid="upload-control">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload a document"
        data-testid="drop-zone"
        data-drag-active={dragActive || undefined}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border bg-bg-subtle p-8 text-center transition-colors",
          "hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
          dragActive && "border-primary bg-primary/5",
        )}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragActive(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        <UploadCloud className="h-8 w-8 text-text-muted" aria-hidden="true" />
        <p className="text-sm font-medium text-text">
          Drag &amp; drop a file here, or click to browse
        </p>
        <p className="text-xs text-text-muted">
          Uploads to your organization&apos;s corpus.
        </p>
        <input
          ref={inputRef}
          type="file"
          data-testid="file-input"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {upload.isPending && (
        <div
          className="flex flex-col gap-1.5"
          data-testid="upload-progress"
          role="status"
          aria-live="polite"
        >
          <span className="text-xs text-text-muted">Uploading…</span>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-raised">
            <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
          </div>
        </div>
      )}

      {upload.isError && (
        <div data-testid="upload-error">
          <ErrorBanner error={upload.error} />
        </div>
      )}

      {lastResult && !upload.isPending && (
        <Card data-testid="upload-result">
          <CardContent className="flex flex-col gap-2 pt-6">
            <div className="flex items-center gap-2 text-sm font-medium text-text">
              <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
              Ingested
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-text-muted">Document ID</dt>
              <dd className="font-mono text-xs" data-testid="result-document-id">
                {lastResult.document_id}
              </dd>
              <dt className="text-text-muted">Filename</dt>
              <dd data-testid="result-filename">{lastResult.filename}</dd>
              <dt className="text-text-muted">Chunks</dt>
              <dd data-testid="result-chunk-count">{lastResult.chunk_count}</dd>
              <dt className="text-text-muted">Status</dt>
              <dd data-testid="result-status">
                <Badge tone="success">{lastResult.status}</Badge>
              </dd>
            </dl>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
