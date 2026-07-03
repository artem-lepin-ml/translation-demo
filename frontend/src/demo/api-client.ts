/**
 * api-client.ts — rev-4 wire-DTO types + typed fetch client for every §2 endpoint.
 *
 * Base path: '/api' (same-origin; Vite proxies /api → localhost:8000).
 * All types match §1 of 2026-06-30-demo-contracts.md verbatim.
 */

// ─── §1 shared ───────────────────────────────────────────────────────────────

export type Verdict = 'green' | 'yellow' | 'red';
export type CriterionId = string;
export type IssueStatus = 'open' | 'accepted' | 'dismissed' | 'outdated';
export type Severity = 'minor' | 'major';

export interface WikidataRef {
  qid: string;
  label: string;
  description: string;
  url: string;
}

// ─── §1 Term ─────────────────────────────────────────────────────────────────

export interface Term {
  id: string;
  paragraphId: number;
  sourceSurface: string;
  sourceLemma: string;
  context: string;
  charStart: number;
  charEnd: number;
  // signal 1: Wikidata grounding difficulty
  difficulty: Verdict;
  grounded: WikidataRef | null;
  candidates: WikidataRef[];
  // signal 2: translation pair accuracy
  targetSurface: string | null;
  pairAccuracy: Verdict | null;
  recommended: string | null;
  note: string;
}

// ─── §1 Criterion ────────────────────────────────────────────────────────────

export interface Criterion {
  id: CriterionId;
  name: string;
  modelName: string;
  prompt: string;
  scaleMin: number;
  scaleMax: number;
  weight: number;
  color: string;
  enabled: boolean;
}

// ─── §1 Issue ────────────────────────────────────────────────────────────────

export interface Issue {
  id: string;
  paragraphId: number;
  criterionId: CriterionId;
  targetFragment: string;
  sourceFragment: string;
  explanation: string;
  suggestion: string;
  severity: Severity;
  mqmCategory: string | null;
  status: IssueStatus;
}

// ─── §1 Score ────────────────────────────────────────────────────────────────

export interface Score {
  criterionId: CriterionId;
  value: number;
  summary: string;
  criteriaKey?: string;
}

// ─── §1 Paragraph ────────────────────────────────────────────────────────────

export interface Paragraph {
  id: number;
  idx: number;
  source: string;
  target: string;
  scores: Score[];
  scoresPrev: Score[] | null;
  scoresBaseline: Score[] | null;
  aggregate: number | null;
  aggregateBaseline: number | null;
  /** Client-side only: set by applyEvalToParag from EvaluateResponse.aggregatePrev (rev-4 §5.1). Not present on load. */
  aggregatePrev?: number | null;
  issues: Issue[];
  terms: Term[];
}

// ─── §1 Document ─────────────────────────────────────────────────────────────

export interface DocumentSummary {
  id: number;
  title: string;
  sourceLang: string;
  targetLang: string;
  nParagraphs: number;
  origin: 'seed' | 'upload';
}

export interface PrecomputeStatus {
  status: 'running' | 'done' | 'stopped' | 'skipped';
  done: number;
  planned: number;
  /** Paragraphs that actually got a written score (vs merely attempted).
   * `done === planned && succeeded === 0` means every precompute call failed
   * (e.g. missing API key) — the caller should surface that, not stay silent. */
  succeeded: number;
}

export interface Document extends DocumentSummary {
  sourceModel: string;
  aggregate: number | null;
  paragraphs: Paragraph[];
  precompute?: PrecomputeStatus | null;
}

// ─── §1 ModelRegistryEntryPublic ─────────────────────────────────────────────

export interface ModelRegistryEntryPublic {
  name: string;
  baseUrl: string;
  apiKeyMasked: string;
  params: Record<string, unknown>;
}

export interface ModelRegistryEntry {
  name: string;
  baseUrl: string;
  apiKey: string;
  params: Record<string, unknown>;
}

// ─── §2 test-model response ──────────────────────────────────────────────────

export interface TestModelResult {
  ok: boolean;
  extracted: string[];
  reference: string[];
  matched: number;
  total: number;
  share: number;
  tokens: { prompt: number; completion: number; reasoning: number };
  costUsd: number | null;
  latencyMs: number;
  message: string;
}

// ─── §2 evaluate response ────────────────────────────────────────────────────

export interface EvaluateResponse {
  scores: Score[];
  scoresPrev: Score[] | null;
  scoresBaseline: Score[] | null;
  aggregate: number;
  aggregateBaseline: number | null;
  aggregatePrev: number | null;
  issues: Issue[];
  failedCriterionIds: CriterionId[];
  cached: boolean;
  cachedAt: string | null;
  docVersion: number;
}

// ─── §2 create-document body ─────────────────────────────────────────────────

export interface ParagraphPair {
  source: string;
  target: string;
}

export interface CreateDocumentBody {
  title: string;
  sourceLang: string;
  targetLang: string;
  precompute: boolean;
  paragraphs: ParagraphPair[];
}

// ─── §2 apply-edit response ──────────────────────────────────────────────────

export interface ApplyEditResponse {
  target: string;
  issue: Issue;
  /** Other open issues in the same paragraph whose fragment the edit overlapped;
   *  server has already flipped these to status='outdated'. */
  siblingIssues: Issue[];
}

// ─── §2 budget snapshot ──────────────────────────────────────────────────────

export interface BudgetSnapshot {
  spentUsd: number;
  capUsd: number;
  calls: number;
  callCap: number;
}

// ─── fetch helpers ───────────────────────────────────────────────────────────

const BASE = '/api';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} → ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PUT ${path} → ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new Error(`DELETE ${path} → ${res.status}`);
}

// ─── §2 document endpoints ───────────────────────────────────────────────────

export function getDocuments(): Promise<DocumentSummary[]> {
  return get('/documents');
}

export function getDocument(id: number): Promise<Document> {
  return get(`/documents/${id}`);
}

export function resetDocument(id: number): Promise<Document> {
  return post(`/documents/${id}/reset`);
}

export function createDocument(body: CreateDocumentBody): Promise<Document> {
  return post('/documents', body);
}

export function deleteDocument(id: number): Promise<void> {
  return del(`/documents/${id}`);
}

export async function extractText(file: File): Promise<{ text: string; nParagraphs: number }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/documents/extract-text`, { method: 'POST', body: form });
  if (!res.ok) {
    const text = await res.text();
    throw Object.assign(new Error(`extract-text → ${res.status}: ${text}`), { status: res.status });
  }
  return res.json() as Promise<{ text: string; nParagraphs: number }>;
}

// ─── §2 paragraph endpoints ──────────────────────────────────────────────────

export function patchParagraph(id: number, target: string): Promise<Paragraph> {
  return patch(`/paragraphs/${id}`, { target });
}

export function evaluate(
  id: number,
  criterionIds?: CriterionId[],
): Promise<EvaluateResponse> {
  return post(`/paragraphs/${id}/evaluate`, criterionIds ? { criterionIds } : undefined);
}

export function applyEdit(id: number, issueId: string): Promise<ApplyEditResponse> {
  return post(`/paragraphs/${id}/apply-edit`, { issueId });
}

export function patchIssueStatus(
  id: string,
  status: 'open' | 'dismissed' | 'outdated',
): Promise<Issue> {
  return patch(`/issues/${id}`, { status });
}

export function postTerms(id: number): Promise<Term[]> {
  return post(`/paragraphs/${id}/terms`);
}

// ─── §2 criteria CRUD ────────────────────────────────────────────────────────

export function getCriteria(): Promise<Criterion[]> {
  return get('/criteria');
}

export function createCriterion(criterion: Criterion): Promise<Criterion> {
  return post('/criteria', criterion);
}

export function updateCriterion(id: CriterionId, criterion: Criterion): Promise<Criterion> {
  return put(`/criteria/${id}`, criterion);
}

export function deleteCriterion(id: CriterionId): Promise<void> {
  return del(`/criteria/${id}`);
}

// ─── §2 models CRUD ──────────────────────────────────────────────────────────

export function getModels(): Promise<ModelRegistryEntryPublic[]> {
  return get('/models');
}

export function createModel(entry: ModelRegistryEntry): Promise<ModelRegistryEntryPublic> {
  return post('/models', entry);
}

export function updateModel(
  name: string,
  entry: Partial<ModelRegistryEntry>,
): Promise<ModelRegistryEntryPublic> {
  return put(`/models/${encodeURIComponent(name)}`, entry);
}

export function deleteModel(name: string): Promise<void> {
  return del(`/models/${encodeURIComponent(name)}`);
}

export function testModel(name: string, effort?: string): Promise<TestModelResult> {
  return post(`/models/${encodeURIComponent(name)}/test`, effort ? { effort } : undefined);
}

// ─── §2 budget endpoint ──────────────────────────────────────────────────────

export function getBudget(): Promise<BudgetSnapshot> {
  return get('/budget');
}

// ─── §2 grounding-config endpoint ─────────────────────────────────────────────

export interface GroundingConfig {
  modelName: string | null;
  prompt: string;
  params: Record<string, unknown>;
}

export function getGroundingConfig(): Promise<GroundingConfig> {
  return get('/grounding-config');
}

export function updateGroundingConfig(cfg: GroundingConfig): Promise<GroundingConfig> {
  return put('/grounding-config', cfg);
}
