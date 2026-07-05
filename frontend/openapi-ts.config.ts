/**
 * OpenAPI type-generation configuration.
 *
 * Declares the single source of truth for the typed API surface: the committed
 * `openapi.json` (dumped from the backend FastAPI app's `app.openapi()`) is the
 * input, and the generated `src/api/schema.d.ts` is the output consumed by the
 * `openapi-fetch` client (Req 1.3).
 *
 * The `codegen` npm script runs `openapi-typescript` with these same paths:
 *   openapi-typescript ./openapi.json --output ./src/api/schema.d.ts
 *
 * `schema.d.ts` is a GENERATED artifact and must never be hand-edited; regenerate
 * it from the backend schema instead. Regenerating `openapi.json` itself is done
 * from the backend (see frontend/README.md), keeping the client from ever drifting
 * from the shipped contracts.
 */
export interface OpenApiCodegenConfig {
  /** Input OpenAPI schema, committed alongside the frontend. */
  readonly input: string;
  /** Generated TypeScript types output (do not hand-edit). */
  readonly output: string;
}

const config: OpenApiCodegenConfig = {
  input: "./openapi.json",
  output: "./src/api/schema.d.ts",
};

export default config;
