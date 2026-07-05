/**
 * The single raw-token store shared by the SessionProvider and the API_Client
 * auth middleware.
 *
 * It owns the persisted Access_Token (localStorage-backed, hydrated lazily),
 * notifies subscribers on change so the Session can re-derive claims, and
 * exposes an "unauthenticated" hook the router registers so a terminal 401 /
 * refresh failure can route the Operator to `/login` (Req 3.3, 3.6).
 *
 * Keeping the token in one module lets the transport (middleware) read the
 * live token without importing React, and keeps token + Session consistent.
 */

const STORAGE_KEY = "agentforge.token";

type Listener = (token: string | null) => void;

// `undefined` means "not yet hydrated from storage".
let inMemory: string | null | undefined = undefined;
const listeners = new Set<Listener>();
let unauthenticatedHandler: (() => void) | null = null;

function hydrate(): string | null {
  if (inMemory !== undefined) return inMemory;
  try {
    inMemory = localStorage.getItem(STORAGE_KEY);
  } catch {
    inMemory = null;
  }
  return inMemory;
}

function emit(): void {
  const value = inMemory ?? null;
  for (const l of listeners) l(value);
}

/** The current stored raw token, or `null`. */
export function getToken(): string | null {
  return hydrate();
}

/** Store a token (persisted) and notify subscribers. */
export function setToken(token: string): void {
  inMemory = token;
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    /* storage unavailable — in-memory value still applies */
  }
  emit();
}

/** Clear the token (persisted) and notify subscribers. */
export function clearToken(): void {
  inMemory = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  emit();
}

/** Subscribe to token changes; returns an unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Register the handler invoked when the session becomes unauthenticated. */
export function setUnauthenticatedHandler(cb: (() => void) | null): void {
  unauthenticatedHandler = cb;
}

/** Clear the token and route the Operator to the login view (Req 3.3, 3.6). */
export function handleUnauthenticated(): void {
  clearToken();
  unauthenticatedHandler?.();
}

/** Test-only: reset the module state between tests. */
export function __resetTokenStoreForTests(): void {
  inMemory = undefined;
  listeners.clear();
  unauthenticatedHandler = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
