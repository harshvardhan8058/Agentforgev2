/**
 * `SampleCorpusControl`: ingests the built-in sample corpus in one click.
 *
 * Retrieval is the centre of the product, and every retrieval surface is
 * useless against an empty corpus — a new Operator picks a query example, gets
 * "no relevant context", and concludes the feature is broken. Supplying a file
 * first is a real obstacle when you just want to see what the product does.
 *
 * The samples are the documents the query / agent / multi-agent examples ask
 * about (see `lib/examples`), so loading them makes every one of those presets
 * return a grounded, cited answer.
 *
 * It uses the same `POST /documents` multipart endpoint as a manual upload — no
 * seeding backdoor, no special-cased demo path, so what is demonstrated is the
 * real ingestion pipeline. That endpoint takes exactly one file per request, so
 * the documents are posted sequentially and progress is reported per file.
 * Gated behind `ingest_documents` by its caller.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileStack, Sparkles } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { useSession } from "../../auth/useSession";
import { orgScopedKey } from "../../api/queryKeys";
import { useToast } from "../../hooks/useToast";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { SAMPLE_DOCUMENTS, type SampleDocument } from "../../lib/examples";

interface IngestResult {
  chunk_count: number;
  document_id: string;
  filename: string;
  status: string;
  /** True when the document was already present and nothing new was written. */
  duplicate?: boolean;
}

/** Post one sample document through the real multipart ingest endpoint. */
async function ingestSample(sample: SampleDocument): Promise<IngestResult> {
  const file = new File([sample.content], sample.filename, {
    type: "text/markdown",
  });
  return runRequest<IngestResult>(() =>
    apiClient.POST("/documents", {
      body: {
        // The generated type models the binary field as a string; the File is
        // appended to the FormData below at runtime.
        file: file as unknown as string,
        filename: sample.filename,
      },
      bodySerializer: (body: { file: unknown; filename?: string | null }) => {
        const form = new FormData();
        form.append("file", body.file as Blob, sample.filename);
        if (body.filename) form.append("filename", body.filename);
        return form;
      },
    }),
  );
}

export function SampleCorpusControl(): JSX.Element {
  const { orgId } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [done, setDone] = useState(0);

  const load = useMutation<IngestResult[], ClientError, void>({
    mutationFn: async () => {
      setDone(0);
      const results: IngestResult[] = [];
      // Sequential because the endpoint accepts a single file per request.
      for (const sample of SAMPLE_DOCUMENTS) {
        results.push(await ingestSample(sample));
        setDone((count) => count + 1);
      }
      return results;
    },
    onSuccess: (results) => {
      const chunks = results.reduce((sum, r) => sum + r.chunk_count, 0);
      // Loading twice is a realistic slip during a demo; saying so is better than
      // implying six documents now exist.
      const added = results.filter((r) => !r.duplicate).length;
      toast({
        title: added === 0 ? "Sample corpus already loaded" : "Sample corpus loaded",
        description:
          added === 0
            ? "Every sample document was already in your corpus."
            : `${added} document${added === 1 ? "" : "s"} · ${chunks} chunks`,
        tone: added === 0 ? "info" : "success",
      });
      void queryClient.invalidateQueries({
        queryKey: orgScopedKey(orgId, "documents"),
      });
    },
  });

  const total = SAMPLE_DOCUMENTS.length;

  return (
    <div
      className="flex flex-col gap-3 rounded-lg border border-border bg-bg-subtle p-4"
      data-testid="sample-corpus-control"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-primary">
          <FileStack className="h-[18px] w-[18px]" aria-hidden="true" />
        </span>
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium text-text">
            No documents to hand? Load the sample corpus
          </p>
          <p className="text-xs leading-relaxed text-text-muted">
            {total} short documents that the query and agent examples ask about, so
            you get grounded, cited answers straight away.
          </p>
        </div>
      </div>

      <ul className="flex flex-col gap-1 pl-12" data-testid="sample-corpus-list">
        {SAMPLE_DOCUMENTS.map((sample) => (
          <li
            key={sample.filename}
            className="flex flex-wrap items-baseline gap-x-2 text-xs text-text-muted"
          >
            <span className="font-mono text-text">{sample.filename}</span>
            <span>{sample.summary}</span>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-3 pl-12">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          data-testid="load-sample-corpus"
          loading={load.isPending}
          disabled={load.isPending}
          onClick={() => load.mutate()}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          {load.isPending ? `Loading ${done + 1} of ${total}…` : "Load sample corpus"}
        </Button>
        {load.isSuccess && !load.isPending && (
          <span className="text-xs text-success" data-testid="sample-corpus-loaded">
            Loaded — try a question on the Query page.
          </span>
        )}
      </div>

      {load.isError && (
        <div className="pl-12" data-testid="sample-corpus-error">
          <ErrorBanner error={load.error} />
        </div>
      )}
    </div>
  );
}
