/**
 * `Markdown`: the safe markdown renderer with inline citations.
 *
 * Renders GitHub-flavored markdown via **react-markdown** + **remark-gfm**,
 * sanitized with **rehype-sanitize**, and with on-demand code-block syntax
 * highlighting via **rehype-highlight**. A custom text transform turns each
 * inline `[n]` marker into a **citation link** to its source
 * `{ document_id, chunk_id }` using the pure `extractCitations` mapping
 * (Property 15); out-of-range / non-reference markers stay inert.
 */
import type { JSX } from "react";
import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import rehypeHighlight from "rehype-highlight";

import type { Citation } from "../../api/domain";
import { cn } from "../../lib/cn";
import { stripDecisionEnvelope } from "../../lib/agentText";
import { extractCitations } from "./extractCitations";

/** A single rendered citation link. */
function CitationLink({
  index,
  marker,
  citation,
}: {
  index: number;
  marker: string;
  citation: Citation;
}): JSX.Element {
  return (
    <a
      href={`#citation-${index}`}
      data-testid={`citation-${index}`}
      data-citation-index={index}
      data-document-id={citation.document_id}
      data-chunk-id={citation.chunk_id}
      title={`Source: ${citation.document_id} · ${citation.chunk_id}`}
      className="mx-0.5 inline-flex items-center rounded bg-primary/15 px-1 text-xs font-medium text-primary no-underline align-baseline hover:bg-primary/25"
    >
      {marker}
    </a>
  );
}

/** Replace `[n]` markers in a text run with citation links (or inert text). */
function renderTextWithCitations(
  text: string,
  citations: readonly Citation[],
  keyPrefix: string,
): ReactNode[] {
  return extractCitations(text, citations).map((segment, i) => {
    if (segment.kind === "text") {
      return segment.text;
    }
    return (
      <CitationLink
        key={`${keyPrefix}-cite-${i}`}
        index={segment.index}
        marker={segment.marker}
        citation={segment.citation}
      />
    );
  });
}

/** Recursively transform string leaves of a node tree, leaving elements intact. */
function processChildren(
  children: ReactNode,
  citations: readonly Citation[],
  keyPrefix: string,
): ReactNode {
  const mapped = Children.toArray(children).map((child, i) => {
    if (typeof child === "string") {
      return renderTextWithCitations(child, citations, `${keyPrefix}-${i}`);
    }
    return child;
  });
  return mapped;
}

/**
 * Build the `components` map that intercepts common inline-text containers so
 * their `[n]` markers become citation links. Code blocks are left untouched so
 * highlighting is not disturbed.
 */
function buildComponents(citations: readonly Citation[]): Components {
  const wrap =
    (Tag: "p" | "li" | "td" | "th") =>
    ({ children }: { children?: ReactNode }) => (
      <Tag>{processChildren(children, citations, Tag)}</Tag>
    );

  return {
    p: wrap("p"),
    li: wrap("li"),
    td: wrap("td"),
    th: wrap("th"),
  };
}

export function Markdown({
  content,
  citations = [],
  className,
  "data-testid": testId = "markdown",
}: {
  content: string;
  citations?: readonly Citation[];
  className?: string;
  "data-testid"?: string;
}): JSX.Element {
  return (
    <div
      data-testid={testId}
      className={cn(
        "af-markdown max-w-none text-sm leading-relaxed text-text",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize, [rehypeHighlight, { ignoreMissing: true }]]}
        components={buildComponents(citations)}
      >
        {/* This component renders model-generated prose exclusively, so it is
            the one place where a leaked decision envelope can be caught for
            every caller at once. The transform is identity for anything that is
            not envelope-shaped — see lib/agentText. */}
        {stripDecisionEnvelope(content)}
      </ReactMarkdown>
    </div>
  );
}

/** Exported for reuse/testing: is `node` a rendered citation link element? */
export function isCitationElement(node: ReactNode): boolean {
  return (
    isValidElement(node) &&
    typeof node.props === "object" &&
    node.props !== null &&
    "data-citation-index" in (node.props as Record<string, unknown>)
  );
}
