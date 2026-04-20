// Typed fetch wrappers.
//
// Server Components / Server Actions run inside the frontend container and
// should use `BACKEND_URL` (the compose-network name). Client components
// run in the browser and must use `NEXT_PUBLIC_API_URL`.

import type {
  CaseOut,
  Draft,
  DraftType,
  DocumentDetail,
  DocumentOut,
  EditOut,
  DraftContent,
  FactOut,
  MineResponse,
  PatternOut,
  TemplateOut,
} from "./types";

const SERVER_BASE = process.env.BACKEND_URL ?? "http://backend:8000";
const CLIENT_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const PUBLIC_API_BASE = CLIENT_BASE;

function baseUrl(): string {
  // On the server, `window` is undefined.
  return typeof window === "undefined" ? SERVER_BASE : CLIENT_BASE;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${baseUrl()}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status} ${res.statusText}: ${body.slice(0, 500)}`);
  }
  return (await res.json()) as T;
}

// --- Cases ---

export function listCases() {
  return fetchJson<CaseOut[]>("/api/cases");
}

export function getCase(id: number) {
  return fetchJson<CaseOut>(`/api/cases/${id}`);
}

export type CaseCreateInput = {
  case_number: string;
  borrower: string;
  property_address: string;
  county?: string | null;
  state?: string | null;
  servicer?: string | null;
  loan_number?: string | null;
  loan_amount?: number | null;
  loan_date?: string | null;     // YYYY-MM-DD
  default_date?: string | null;  // YYYY-MM-DD
  current_status?: string | null;
  notes?: string | null;
};

export function createCase(input: CaseCreateInput) {
  return fetchJson<CaseOut>("/api/cases", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// --- Documents ---

export function listDocuments(caseId: number) {
  return fetchJson<DocumentOut[]>(`/api/cases/${caseId}/documents`);
}

export function getDocument(documentId: number) {
  return fetchJson<DocumentDetail>(`/api/documents/${documentId}`);
}

// --- Facts ---

export function listFacts(caseId: number) {
  return fetchJson<FactOut[]>(`/api/cases/${caseId}/facts`);
}

// --- Drafts ---

export function listDraftsForCase(caseId: number) {
  return fetchJson<Draft[]>(`/api/cases/${caseId}/drafts`);
}

export function getDraft(draftId: number) {
  return fetchJson<Draft>(`/api/drafts/${draftId}`);
}

export function createDraft(caseId: number, draftType: DraftType) {
  return fetchJson<Draft>(`/api/cases/${caseId}/drafts`, {
    method: "POST",
    body: JSON.stringify({ draft_type: draftType }),
  });
}

// --- Edits ---

export function saveEdit(
  draftId: number,
  operator_version: DraftContent,
  rationale?: string,
) {
  return fetchJson<EditOut>(`/api/drafts/${draftId}/edits`, {
    method: "POST",
    body: JSON.stringify({
      operator_id: "ui-operator",
      operator_version,
      rationale: rationale ?? null,
    }),
  });
}

export function listEdits(draftId: number) {
  return fetchJson<EditOut[]>(`/api/drafts/${draftId}/edits`);
}

// --- Pipeline ---

export function runProcess(caseId: number) {
  return fetchJson<Record<string, unknown>>(`/api/cases/${caseId}/process`, {
    method: "POST",
  });
}

// --- Learning ---

export function listPatterns() {
  return fetchJson<PatternOut[]>(`/api/learning/patterns`);
}

export function listTemplates() {
  return fetchJson<TemplateOut[]>(`/api/learning/templates`);
}

export function runMiner() {
  return fetchJson<MineResponse>(`/api/learning/mine`, { method: "POST" });
}
