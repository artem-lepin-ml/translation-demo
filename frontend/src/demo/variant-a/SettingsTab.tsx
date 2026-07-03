import { Fragment, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getBudget } from '../api-client';
import type { BudgetSnapshot, Criterion, ModelRegistryEntryPublic, TestModelResult } from '../api-client';
import type { DemoStore } from '../store';

interface Props {
  criteria: Criterion[];
  models: ModelRegistryEntryPublic[];
  onUpdateCriterion: DemoStore['saveCriterion'];
  onAddCriterion: DemoStore['addCriterion'];
  onRemoveCriterion: DemoStore['removeCriterion'];
  onSaveModel: DemoStore['saveModel'];
  onAddModel: DemoStore['addModel'];
  onRemoveModel: DemoStore['removeModel'];
  onTestModel: DemoStore['testModel'];
}

// Evaluator palette already in use by the seed criteria (seed.py CRITERIA) —
// pick the first hue below not already assigned to an existing criterion.
const EVALUATOR_PALETTE = [
  '#4d8dff', '#2ad4c8', '#b072ff', '#fb923c', '#f25cc1', '#a3e635', '#38bdf8', '#f43f5e',
];

function unusedColor(criteria: Criterion[]): string {
  const used = new Set(criteria.map((c) => c.color));
  return EVALUATOR_PALETTE.find((c) => !used.has(c)) ?? EVALUATOR_PALETTE[0];
}

/** Clamp a weight input to [0, 1], rejecting NaN/negative (server also enforces 0..1). */
function clampWeight(raw: string): number {
  const v = parseFloat(raw);
  if (Number.isNaN(v)) return 0;
  return Math.min(1, Math.max(0, v));
}

interface TestState {
  loading: boolean;
  expanded: boolean;
  result: TestModelResult | null;
}

function defaultTestState(): TestState {
  return { loading: false, expanded: false, result: null };
}

export default function SettingsTab({
  criteria,
  models,
  onUpdateCriterion,
  onAddCriterion,
  onRemoveCriterion,
  onSaveModel,
  onAddModel,
  onRemoveModel,
  onTestModel,
}: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null); // collapsed by default
  // Per-criterion error surfaced inline in EvaluatorEditor — covers both a
  // failed Remove and a failed field edit (Name/Color/Model/Weight).
  const [fieldError, setFieldError] = useState<{ id: string; message: string } | null>(null);

  const [testState, setTestState] = useState<Record<string, TestState>>({});
  const [editing, setEditing] = useState<ModelRegistryEntryPublic | null>(null);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [showAddEvaluator, setShowAddEvaluator] = useState(false);
  const [showAddModel, setShowAddModel] = useState(false);
  const [expandedParams, setExpandedParams] = useState<Record<string, boolean>>({});
  // Synchronous re-entry guard: the button's `disabled={loading}` updates only on
  // re-render, so rapid double/triple-clicks can fire several real (paid) calls
  // before React disables it. This ref blocks re-entry in the same tick.
  const inFlight = useRef<Set<string>>(new Set());

  // Refresh the budget snapshot each time the Settings tab mounts (real-money
  // spend is otherwise invisible in the UI — the backend has no push channel).
  useEffect(() => {
    getBudget().then(setBudget).catch(() => setBudget(null));
  }, []);

  function stateFor(name: string): TestState {
    return testState[name] ?? defaultTestState();
  }

  async function handleTest(name: string) {
    if (inFlight.current.has(name)) return;
    inFlight.current.add(name);
    setTestState((s) => ({ ...s, [name]: { ...stateFor(name), loading: true, expanded: true } }));
    try {
      const result = await onTestModel(name);
      setTestState((s) => ({ ...s, [name]: { loading: false, expanded: true, result } }));
    } catch (e) {
      setTestState((s) => ({
        ...s,
        [name]: {
          loading: false,
          expanded: true,
          result: {
            ok: false,
            extracted: [],
            reference: [],
            matched: 0,
            total: 0,
            share: 0,
            tokens: { prompt: 0, completion: 0, reasoning: 0 },
            costUsd: null,
            latencyMs: 0,
            message: String(e),
          },
        },
      }));
    } finally {
      inFlight.current.delete(name);
    }
  }

  async function handleRemoveModel(name: string) {
    if (!window.confirm(`Delete “${name}”?`)) return;
    try {
      await onRemoveModel(name);
    } catch {
      // any error is a no-op here — the row simply stays (no silent fail).
    }
  }

  async function handleEnabledToggle(c: Criterion, enabled: boolean) {
    try {
      await onUpdateCriterion({ ...c, enabled });
    } catch (e) {
      setFieldError({ id: c.id, message: String(e) });
    }
  }

  return (
    <div className="va-tab-content">
      {budget && <BudgetLine budget={budget} />}

      {/* ─── Criteria (Evaluators) — full-width rows, Model Registry pattern ── */}
      <div className="va-settings-section-title">Evaluators</div>
      <table className="va-table">
        <thead>
          <tr>
            <th style={{ width: 24 }} />
            <th>Name</th>
            <th>Model</th>
            <th>Weight</th>
            <th>Enabled</th>
            <th style={{ width: 24 }} />
          </tr>
        </thead>
        <tbody>
          {criteria.map((c) => {
            const isOpen = expandedId === c.id;
            return (
              <Fragment key={c.id}>
                <tr
                  className={`va-eval-row${!c.enabled ? ' disabled' : ''}`}
                  onClick={() => setExpandedId(isOpen ? null : c.id)}
                >
                  <td>
                    <span className="va-evaluator-color-swatch" style={{ background: c.color }} />
                  </td>
                  <td style={{ fontWeight: 600 }}>{c.name}</td>
                  <td style={{ fontFamily: 'var(--va-font-mono)', fontSize: 12, color: 'var(--va-text-dim)' }}>
                    {c.modelName}
                  </td>
                  <td>{c.weight}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={c.enabled}
                      onChange={(e) => void handleEnabledToggle(c, e.target.checked)}
                    />
                  </td>
                  <td>
                    <span className={`va-eval-chevron${isOpen ? ' open' : ''}`}>▶</span>
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={6} style={{ padding: 0, borderBottom: '1px solid var(--va-border)' }}>
                      <EvaluatorEditor
                        criterion={c}
                        models={models}
                        onUpdate={async (next) => {
                          try {
                            await onUpdateCriterion(next);
                            setFieldError(null);
                          } catch (e) {
                            setFieldError({ id: c.id, message: String(e) });
                            throw e;
                          }
                        }}
                        fieldError={fieldError?.id === c.id ? fieldError.message : null}
                        onRemove={async () => {
                          if (!window.confirm(`Delete “${c.name}”?`)) return;
                          setFieldError(null);
                          try {
                            await onRemoveCriterion(c.id);
                            setExpandedId(null);
                          } catch (e) {
                            setFieldError({ id: c.id, message: `Could not remove — disable the evaluator instead. ${String(e)}` });
                          }
                        }}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      <button
        className="va-add-eval-btn"
        data-testid="add-evaluator-btn"
        onClick={() => setShowAddEvaluator(true)}
      >
        + Add evaluator
      </button>

      {/* ─── Model Registry ─────────────────────────────────────────────────── */}
      <div className="va-model-registry-section">
        <div className="va-settings-section-title" style={{ marginTop: 32 }}>Model Registry</div>
        <table className="va-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Base URL</th>
              <th>API Key</th>
              <th>Params</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => {
              const ts = stateFor(m.name);
              const paramsOpen = !!expandedParams[m.name];
              const paramsCount = Object.keys(m.params).length;
              return (
                <Fragment key={m.name}>
                  <tr>
                    <td style={{ fontWeight: 600, fontFamily: 'var(--va-font-mono)', fontSize: 12 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        {ts.result && (
                          <span className={`va-verdict-dot ${ts.result.ok ? 'green' : 'red'}`} />
                        )}
                        {m.name}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--va-font-mono)', fontSize: 11, color: 'var(--va-text-dim)' }}>{m.baseUrl}</td>
                    <td style={{ fontFamily: 'var(--va-font-mono)', fontSize: 11, color: 'var(--va-text-dim)' }}>
                      {m.apiKeyMasked}
                    </td>
                    <td>
                      <span
                        className={`va-params-badge${paramsOpen ? ' open' : ''}`}
                        data-testid={`params-badge-${m.name}`}
                        onClick={() => setExpandedParams((s) => ({ ...s, [m.name]: !s[m.name] }))}
                      >
                        <span className="chev">▶</span>{paramsCount} params
                      </span>
                      {paramsOpen && (
                        <div className="va-params-expanded" data-testid={`params-expanded-${m.name}`}>
                          {Object.entries(m.params).map(([k, v]) => (
                            <div key={k}><span className="k">{k}:</span><span className="v">{JSON.stringify(v)}</span></div>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="va-btn-secondary" onClick={() => handleTest(m.name)} disabled={ts.loading}>
                          {ts.loading ? '…' : 'Test'}
                        </button>
                        <button className="va-btn-secondary" onClick={() => setEditing(m)}>Edit</button>
                        <button className="va-btn-secondary" onClick={() => void handleRemoveModel(m.name)}>
                          Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                  {ts.expanded && ts.result && (
                    <tr>
                      <td colSpan={5} style={{ padding: 0, borderBottom: '1px solid var(--va-border)' }}>
                        <TestResultCard result={ts.result} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        <div className="va-model-registry-actions">
          <button className="va-btn-secondary" data-testid="add-model-btn" onClick={() => setShowAddModel(true)}>
            + Add model
          </button>
        </div>
      </div>

      {editing && (
        <EditModelModal
          model={editing}
          onClose={() => setEditing(null)}
          onSave={async (entry) => {
            await onSaveModel(editing.name, entry);
            setEditing(null);
          }}
        />
      )}

      {showAddEvaluator && (
        <AddEvaluatorModal
          criteria={criteria}
          models={models}
          onClose={() => setShowAddEvaluator(false)}
          onSave={async (criterion) => {
            await onAddCriterion(criterion);
            setShowAddEvaluator(false);
          }}
        />
      )}

      {showAddModel && (
        <AddModelModal
          onClose={() => setShowAddModel(false)}
          onSave={async (entry) => {
            await onAddModel(entry);
            setShowAddModel(false);
          }}
        />
      )}
    </div>
  );
}

// ─── EvaluatorEditor — inline expanded editor (Model Registry expand pattern) ──

interface EvaluatorEditorProps {
  criterion: Criterion;
  models: ModelRegistryEntryPublic[];
  onUpdate: (c: Criterion) => Promise<void>;
  onRemove: () => void;
  /** Server error text from a failed remove or field edit (e.g. 409 history
   * conflict, rejected save); null = no error */
  fieldError: string | null;
}

function EvaluatorEditor({ criterion, models, onUpdate, onRemove, fieldError }: EvaluatorEditorProps) {
  function updateField<K extends keyof Criterion>(field: K, value: Criterion[K]) {
    void onUpdate({ ...criterion, [field]: value }).catch(() => {
      // onUpdate already recorded the error in fieldError; nothing further to
      // do here — this catch only stops an unhandled rejection.
    });
  }

  return (
    <div className="va-evaluator-detail" style={{ border: 'none', borderRadius: 0 }}>
      {/* Name */}
      <div>
        <div className="va-field-label">Name</div>
        <input
          className="va-field-input"
          value={criterion.name}
          onChange={(e) => updateField('name', e.target.value)}
        />
      </div>

      {/* Color */}
      <div>
        <div className="va-field-label">Color</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="color"
            value={criterion.color}
            onChange={(e) => updateField('color', e.target.value)}
            style={{ width: 36, height: 28, border: 'none', background: 'none', cursor: 'pointer', padding: 0 }}
          />
          <span style={{ fontSize: 12, color: 'var(--va-text-muted)', fontFamily: 'var(--va-font-mono)' }}>
            {criterion.color}
          </span>
        </div>
      </div>

      {/* Model picker — by name from registry */}
      <div>
        <div className="va-field-label">Model</div>
        <select
          className="va-field-input va-field-select"
          value={criterion.modelName}
          onChange={(e) => updateField('modelName', e.target.value)}
        >
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      {/* Weight — numeric input only (owner: no slider); lang="en" forces the
          dot decimal separator regardless of browser locale (audit LOW «0,3») */}
      <div>
        <div className="va-field-label">Weight (0–1)</div>
        <input
          type="number"
          lang="en"
          className="va-field-input va-weight-input"
          min={0}
          max={1}
          step={0.05}
          value={criterion.weight}
          onChange={(e) => updateField('weight', clampWeight(e.target.value))}
        />
      </div>

      {/* Scale */}
      <div>
        <div className="va-field-label">Scale</div>
        <span style={{ fontSize: 13, color: 'var(--va-text-muted)' }}>
          {criterion.scaleMin} – {criterion.scaleMax}
        </span>
      </div>

      {/* Prompt preview */}
      <div>
        <div className="va-field-label">Prompt (read-only preview)</div>
        <div className="va-prompt-preview">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{criterion.prompt}</ReactMarkdown>
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button className="va-btn-secondary" onClick={onRemove}>
          Remove
        </button>
      </div>
      {fieldError && (
        <div className="va-inspector-warning" data-testid="evaluator-field-error">
          {fieldError}
        </div>
      )}
    </div>
  );
}

// ─── BudgetLine ──────────────────────────────────────────────────────────────

function budgetBand(spentUsd: number, capUsd: number, calls: number, callCap: number): 'muted' | 'yellow' | 'red' {
  const usdShare = capUsd > 0 ? spentUsd / capUsd : 0;
  const callShare = callCap > 0 ? calls / callCap : 0;
  const share = Math.max(usdShare, callShare);
  if (share > 0.8) return 'red';
  if (share > 0.5) return 'yellow';
  return 'muted';
}

function BudgetLine({ budget }: { budget: BudgetSnapshot }) {
  const band = budgetBand(budget.spentUsd, budget.capUsd, budget.calls, budget.callCap);
  return (
    <div className={`va-budget-line ${band}`} data-testid="budget-line">
      Budget: ${budget.spentUsd.toFixed(2)} / ${budget.capUsd.toFixed(2)} · {budget.calls}/{budget.callCap} calls
    </div>
  );
}

// ─── TestResultCard ────────────────────────────────────────────────────────

function TestResultCard({ result }: { result: TestModelResult }) {
  const sharePct = Math.round(result.share * 100);
  return (
    <div className="va-insp-issue-card" style={{ borderBottom: 'none' }}>
      <div className="va-insp-issue-header">
        <span
          className="va-insp-crit-badge"
          style={
            result.ok
              ? { color: 'var(--va-green)', borderColor: 'var(--va-green)' }
              : { color: 'var(--va-red)', borderColor: 'var(--va-red)' }
          }
        >
          {result.ok ? 'OK' : 'FAILED'}
        </span>
        <span className="va-insp-model-name">{result.latencyMs} ms</span>
        <span className="va-insp-model-name">
          matched {result.matched}/{result.total} ({sharePct}%)
        </span>
        <span className="va-insp-model-name">
          cost {result.costUsd !== null ? `$${result.costUsd.toFixed(4)}` : '—'}
        </span>
      </div>
      {!result.ok && <div className="va-insp-issue-expl">{result.message}</div>}
    </div>
  );
}

// ─── EditModelModal ──────────────────────────────────────────────────────────

interface EditModelModalProps {
  model: ModelRegistryEntryPublic;
  onClose: () => void;
  onSave: (entry: { baseUrl: string; apiKey: string; params: Record<string, unknown> }) => Promise<void>;
}

function EditModelModal({ model, onClose, onSave }: EditModelModalProps) {
  const [baseUrl, setBaseUrl] = useState(model.baseUrl);
  const [apiKey, setApiKey] = useState('');
  const [paramsText, setParamsText] = useState(JSON.stringify(model.params, null, 2));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Synchronous re-entry guard — see handleTest's comment in SettingsTab for why
  // state alone (`saving`) is too slow to stop a rapid double/triple-click.
  const inFlight = useRef(false);

  async function handleSave() {
    if (inFlight.current) return;
    let params: Record<string, unknown>;
    try {
      params = JSON.parse(paramsText);
    } catch {
      setError('Params must be valid JSON.');
      return;
    }
    setError(null);
    inFlight.current = true;
    setSaving(true);
    try {
      await onSave({ baseUrl, apiKey, params });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
      inFlight.current = false;
    }
  }

  return (
    <>
      <div className="va-popover-backdrop" onClick={onClose} />
      <div
        className="va-popover"
        style={{ top: '20vh', left: '50%', transform: 'translateX(-50%)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="va-popover-close" onClick={onClose}>✕</button>
        <div className="va-field-label">Model</div>
        <div style={{ fontFamily: 'var(--va-font-mono)', fontSize: 12, color: 'var(--va-text)' }}>
          {model.name}
        </div>

        <div>
          <div className="va-field-label">Base URL</div>
          <input
            className="va-field-input"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </div>

        <div>
          <div className="va-field-label">API Key</div>
          <input
            className="va-field-input"
            type="password"
            placeholder={model.apiKeyMasked}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div>
          <div className="va-field-label">Params (JSON)</div>
          <textarea
            className="va-field-input"
            style={{ fontFamily: 'var(--va-font-mono)', fontSize: 11, minHeight: 120, resize: 'vertical' }}
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
          />
        </div>

        {error && <div className="va-inline-error" data-testid="edit-model-error" style={{ color: 'var(--va-red)', fontSize: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 8 }}>
          <button className="va-btn-secondary" onClick={handleSave} disabled={saving}>
            {saving ? '…' : 'Save'}
          </button>
          <button className="va-btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </>
  );
}

// ─── AddEvaluatorModal ────────────────────────────────────────────────────────

interface AddEvaluatorModalProps {
  criteria: Criterion[];
  models: ModelRegistryEntryPublic[];
  onClose: () => void;
  onSave: (criterion: Criterion) => Promise<void>;
}

function AddEvaluatorModal({ criteria, models, onClose, onSave }: AddEvaluatorModalProps) {
  const [name, setName] = useState('');
  const [modelName, setModelName] = useState(models[0]?.name ?? '');
  const [weightText, setWeightText] = useState('0.20');
  const [color, setColor] = useState(unusedColor(criteria));
  const [prompt, setPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Synchronous re-entry guard — see handleTest's comment in SettingsTab for why
  // state alone (`saving`) is too slow to stop a rapid double/triple-click.
  const inFlight = useRef(false);

  async function handleSave() {
    if (inFlight.current) return;
    const nameEmpty = !name.trim();
    const promptEmpty = !prompt.trim();
    setNameError(nameEmpty ? 'Name is required' : null);
    setPromptError(promptEmpty ? 'Prompt is required' : null);
    if (nameEmpty || promptEmpty) return;

    const weight = parseFloat(weightText);
    if (Number.isNaN(weight) || weight < 0 || weight > 1) {
      setError('Weight must be between 0 and 1');
      return;
    }
    setError(null);
    inFlight.current = true;
    setSaving(true);
    try {
      await onSave({
        id: `crit-${Date.now()}`,
        name,
        modelName,
        prompt,
        scaleMin: 1,
        scaleMax: 10,
        weight,
        color,
        enabled: false,
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
      inFlight.current = false;
    }
  }

  return (
    <div className="va-popover-backdrop va-modal-backdrop" onClick={onClose}>
      <div className="va-popover" data-testid="add-evaluator-modal" onClick={(e) => e.stopPropagation()}>
        <button className="va-popover-close" onClick={onClose}>✕</button>
        <div className="va-modal-title">Add evaluator</div>

        <div>
          <div className="va-field-label">Name</div>
          <input className="va-field-input" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          {nameError && <div className="va-inline-error" data-testid="add-evaluator-name-error">{nameError}</div>}
        </div>

        <div>
          <div className="va-field-label">Model</div>
          <select
            className="va-field-input va-field-select"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.name} value={m.name}>{m.name}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="va-field-label" htmlFor="add-evaluator-weight">Weight (0–1)</label>
          <input
            id="add-evaluator-weight"
            type="number"
            lang="en"
            className="va-field-input va-weight-input"
            min={0}
            max={1}
            step={0.05}
            value={weightText}
            onChange={(e) => setWeightText(e.target.value)}
          />
        </div>

        <div>
          <div className="va-field-label">Color (auto)</div>
          <div className="va-color-row">
            <span className="va-color-swatch-preview" style={{ background: color }} />
            <input className="va-field-input" style={{ maxWidth: 120 }} value={color} onChange={(e) => setColor(e.target.value)} />
          </div>
        </div>

        <div>
          <div className="va-field-label">Prompt</div>
          <textarea
            className="va-field-input va-prompt-textarea"
            data-testid="add-evaluator-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
          {promptError && <div className="va-inline-error" data-testid="add-evaluator-prompt-error">{promptError}</div>}
        </div>

        {error && <div className="va-inline-error" data-testid="add-evaluator-error">{error}</div>}

        <div className="va-modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className="va-primary" onClick={() => void handleSave()} disabled={saving}>
            {saving ? '…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── AddModelModal ────────────────────────────────────────────────────────────

interface AddModelModalProps {
  onClose: () => void;
  onSave: (entry: { name: string; baseUrl: string; apiKey: string; params: Record<string, unknown> }) => Promise<void>;
}

const DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1';

function AddModelModal({ onClose, onSave }: AddModelModalProps) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState(DEFAULT_BASE_URL);
  const [apiKey, setApiKey] = useState('');
  const [paramsText, setParamsText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Synchronous re-entry guard — see handleTest's comment in SettingsTab for why
  // state alone (`saving`) is too slow to stop a rapid double/triple-click.
  const inFlight = useRef(false);

  async function handleSave() {
    if (inFlight.current) return;
    let params: Record<string, unknown> = {};
    if (paramsText.trim()) {
      try {
        params = JSON.parse(paramsText);
      } catch {
        setError('Params must be valid JSON.');
        return;
      }
    }
    setError(null);
    inFlight.current = true;
    setSaving(true);
    try {
      await onSave({ name, baseUrl, apiKey, params });
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
      inFlight.current = false;
    }
  }

  return (
    <div className="va-popover-backdrop va-modal-backdrop" onClick={onClose}>
      <div className="va-popover" data-testid="add-model-modal" onClick={(e) => e.stopPropagation()}>
        <button className="va-popover-close" onClick={onClose}>✕</button>
        <div className="va-modal-title">Add model</div>

        <div>
          <div className="va-field-label">Name</div>
          <input
            className="va-field-input"
            placeholder="provider/model-id, e.g. mistralai/mistral-large"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <div className="va-field-label">Base URL</div>
          <input className="va-field-input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </div>

        <div>
          <div className="va-field-label">API Key</div>
          <input
            className="va-field-input"
            type="password"
            placeholder="sk-or-v1-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>

        <div>
          <div className="va-field-label">Params (JSON)</div>
          <textarea
            className="va-field-input"
            style={{ fontFamily: 'var(--va-font-mono)', fontSize: 11, minHeight: 100, resize: 'vertical' }}
            placeholder='{"max_tokens": 1536}'
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
          />
        </div>

        {error && <div className="va-inline-error" data-testid="add-model-error">{error}</div>}

        <div className="va-modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className="va-primary" onClick={() => void handleSave()} disabled={saving}>
            {saving ? '…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
