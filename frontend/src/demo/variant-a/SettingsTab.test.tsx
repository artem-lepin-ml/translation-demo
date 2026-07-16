import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SettingsTab from './SettingsTab';
import type {
  Criterion, GroundingConfig, ModelRegistryEntryPublic, RefinerConfig, TranslatorConfig,
} from '../api-client';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const criterion: Criterion = {
  id: 'accuracy',
  name: 'Accuracy',
  modelName: 'openai/gpt-5.4-mini',
  prompt: '',
  scaleMin: 1,
  scaleMax: 10,
  weight: 0.3,
  color: '#4d8dff',
  enabled: true,
};

const model: ModelRegistryEntryPublic = {
  name: 'openai/gpt-5.4-mini',
  baseUrl: '',
  apiKeyMasked: '****',
  params: {},
  effectiveParams: {},
};

const groundingConfig: GroundingConfig = {
  modelName: 'openai/gpt-5.4-mini',
  prompt: 'Disambiguate the candidate.',
  params: { max_tokens: 512, temperature: 0 },
};

const translatorConfig: TranslatorConfig = {
  modelName: 'openai/gpt-5.4-mini',
  prompt: 'Translate faithfully.',
  params: { max_tokens: 2048, temperature: 0.3 },
};

const refinerConfig: RefinerConfig = {
  modelName: 'openai/gpt-5.4-mini',
  prompt: 'Rewrite the paragraph addressing every open finding while preserving meaning.',
  params: { max_tokens: 2048, temperature: 0.2 },
};

function renderSettings(overrides: Partial<React.ComponentProps<typeof SettingsTab>> = {}) {
  const props = {
    criteria: [criterion],
    models: [model],
    onUpdateCriterion: vi.fn(),
    onAddCriterion: vi.fn(),
    onRemoveCriterion: vi.fn(),
    onSaveModel: vi.fn(),
    onAddModel: vi.fn(),
    onRemoveModel: vi.fn(),
    onTestModel: vi.fn(),
    groundingConfig,
    onSaveGroundingConfig: vi.fn(),
    translatorConfig,
    onSaveTranslatorConfig: vi.fn(),
    refinerConfig,
    onSaveRefinerConfig: vi.fn(),
    ...overrides,
  };
  render(<SettingsTab {...props} />);
  return props;
}

describe('SettingsTab Remove confirm guard (LOW-b)', () => {
  it('does not remove the model when the confirm dialog is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const props = renderSettings();

    fireEvent.click(screen.getByText('Remove'));

    expect(window.confirm).toHaveBeenCalledWith(`Delete "${model.name}"?`);
    expect(props.onRemoveModel).not.toHaveBeenCalled();
  });

  it('removes the model when the confirm dialog is accepted', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const props = renderSettings();

    fireEvent.click(screen.getByText('Remove'));

    expect(props.onRemoveModel).toHaveBeenCalledWith(model.name);
  });

  it('does not remove the judge when the confirm dialog is declined', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const props = renderSettings();

    // Expand the criterion row to reveal its Remove button, scoped to the
    // Judges section (settings-section-judges) so it's unambiguous relative
    // to the Model Registry row's own "Remove" button elsewhere on the page.
    fireEvent.click(screen.getByText('Accuracy'));
    const judgeRemove = within(screen.getByTestId('settings-section-judges')).getByText('Remove');
    fireEvent.click(judgeRemove);

    expect(window.confirm).toHaveBeenCalledWith(`Delete "${criterion.name}"?`);
    expect(props.onRemoveCriterion).not.toHaveBeenCalled();
  });
});

describe('SettingsTab Add Evaluator modal', () => {
  async function openAddEvaluator(overrides: Partial<React.ComponentProps<typeof SettingsTab>> = {}) {
    const props = renderSettings(overrides);
    fireEvent.click(await screen.findByText('+ Add judge'));
    return props;
  }

  it('opens the modal with expected fields', async () => {
    await openAddEvaluator();
    expect(await screen.findByTestId('add-evaluator-modal')).toBeTruthy();
  });

  it('centers via the same backdrop modifier as UploadModal (regression: modal rendered below viewport)', async () => {
    await openAddEvaluator();
    const modal = await screen.findByTestId('add-evaluator-modal');

    // The centering mechanism is: .va-popover nested inside a
    // .va-popover-backdrop.va-modal-backdrop (flex-center), with the CSS rule
    // `.va-modal-backdrop > .va-popover { position: static }` dropping the
    // fixed-without-top/left positioning that stranded the modal at the end
    // of the static-flow SettingsTab container. jsdom can't measure real
    // layout, so we assert the structural contract instead.
    expect(modal.parentElement?.classList.contains('va-modal-backdrop')).toBe(true);
    expect(modal.parentElement?.classList.contains('va-popover-backdrop')).toBe(true);
  });

  it('blocks Save and shows inline error when weight is out of [0,1]', async () => {
    const props = await openAddEvaluator();
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'New eval' } });
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: 'Evaluate this.' } });
    const weightInput = screen.getByLabelText(/weight/i, { selector: 'input' });
    fireEvent.change(weightInput, { target: { value: '1.5' } });
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('add-evaluator-error')).textContent).toContain('Weight must be between 0 and 1');
    expect(props.onAddCriterion).not.toHaveBeenCalled();
  });

  it('saves via onAddCriterion with enabled:false on valid input', async () => {
    const props = await openAddEvaluator();
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'New eval' } });
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: 'Evaluate this.' } });
    const weightInput = screen.getByLabelText(/weight/i, { selector: 'input' });
    fireEvent.change(weightInput, { target: { value: '0.2' } });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(props.onAddCriterion).toHaveBeenCalled());
    const arg = (props.onAddCriterion as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.enabled).toBe(false);
    expect(arg.name).toBe('New eval');
  });

  it('shows inline error on server rejection', async () => {
    const onAddCriterion = vi.fn().mockRejectedValue(new Error('POST /criteria → 422'));
    const props = await openAddEvaluator({ onAddCriterion });
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'New eval' } });
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: 'Evaluate this.' } });
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('add-evaluator-error')).textContent).toContain('422');
    void props;
  });

  it('blocks Save and shows "Name is required" when name is empty', async () => {
    const props = await openAddEvaluator();
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: 'Evaluate this.' } });
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('add-evaluator-name-error')).textContent).toContain('Name is required');
    expect(props.onAddCriterion).not.toHaveBeenCalled();
  });

  it('blocks Save and shows "Prompt is required" when prompt is empty', async () => {
    const props = await openAddEvaluator();
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'New eval' } });
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('add-evaluator-prompt-error')).textContent).toContain('Prompt is required');
    expect(props.onAddCriterion).not.toHaveBeenCalled();
  });

  it('blocks Save when name/prompt are whitespace-only', async () => {
    const props = await openAddEvaluator();
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: '   ' } });
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: '   ' } });
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('add-evaluator-name-error')).textContent).toContain('Name is required');
    expect((await screen.findByTestId('add-evaluator-prompt-error')).textContent).toContain('Prompt is required');
    expect(props.onAddCriterion).not.toHaveBeenCalled();
  });
});

describe('SettingsTab Add Model modal', () => {
  async function openAddModel(overrides: Partial<React.ComponentProps<typeof SettingsTab>> = {}) {
    const props = renderSettings(overrides);
    fireEvent.click(await screen.findByText('+ Add model'));
    return props;
  }

  it('opens the modal with a default openrouter base URL', async () => {
    await openAddModel();
    expect(await screen.findByTestId('add-model-modal')).toBeTruthy();
    expect(screen.getByDisplayValue('https://openrouter.ai/api/v1')).toBeTruthy();
  });

  it('centers via the same backdrop modifier as UploadModal (regression: modal rendered below viewport)', async () => {
    await openAddModel();
    const modal = await screen.findByTestId('add-model-modal');

    expect(modal.parentElement?.classList.contains('va-modal-backdrop')).toBe(true);
    expect(modal.parentElement?.classList.contains('va-popover-backdrop')).toBe(true);
  });

  it('shows inline error on invalid params JSON and does not save', async () => {
    const props = await openAddModel();
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: 'foo/bar' } });
    fireEvent.change(screen.getByPlaceholderText('{"max_tokens": 20000}'), { target: { value: '{not json' } });
    fireEvent.click(screen.getByText('Save'));

    expect(await screen.findByTestId('add-model-error')).toBeTruthy();
    expect(props.onAddModel).not.toHaveBeenCalled();
  });

  it('saves via onAddModel replacing window.prompt entirely', async () => {
    const props = await openAddModel();
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: 'foo/bar' } });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(props.onAddModel).toHaveBeenCalled());
    const arg = (props.onAddModel as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(arg.name).toBe('foo/bar');
    expect(arg.baseUrl).toBe('https://openrouter.ai/api/v1');
  });

  it('BUG-2 (wave2): Save is disabled while Name is empty, and blurring an empty Name shows inline validation', async () => {
    const props = await openAddModel();
    const saveBtn = screen.getByText('Save') as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
    expect(screen.queryByTestId('add-model-name-error')).toBeNull();   // not shown on pristine open

    fireEvent.blur(screen.getByPlaceholderText(/provider\/model-id/));
    expect(await screen.findByTestId('add-model-name-error')).toBeTruthy();
    expect(props.onAddModel).not.toHaveBeenCalled();
  });

  it('BUG-2 (wave2): Save stays disabled for a whitespace-only Name', async () => {
    await openAddModel();
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: '   ' } });
    expect((screen.getByText('Save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('BUG-2 (wave2): a non-empty Name re-enables Save and clears the inline error', async () => {
    await openAddModel();
    const nameInput = screen.getByPlaceholderText(/provider\/model-id/);
    fireEvent.blur(nameInput);
    expect(await screen.findByTestId('add-model-name-error')).toBeTruthy();

    fireEvent.change(nameInput, { target: { value: 'foo/bar' } });
    expect((screen.getByText('Save') as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByTestId('add-model-name-error')).toBeNull();
  });

  it('BUG-2 (wave2): a server 422 on Name (race/legacy client) surfaces a clean detail message', async () => {
    const onAddModel = vi.fn().mockRejectedValue(
      new Error('POST /models → 422: {"detail":"name must not be blank"}'),
    );
    const props = await openAddModel({ onAddModel });
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: 'foo/bar' } });
    fireEvent.click(screen.getByText('Save'));

    const err = await screen.findByTestId('add-model-error');
    expect(err.textContent).toContain('422');
    expect(err.textContent).toContain('name must not be blank');
    expect(props.onAddModel).toHaveBeenCalled();
  });
});

describe('SettingsTab silent mutation failures (fix wave commit 1)', () => {
  it('a rejected field edit (e.g. Name) shows an inline error in EvaluatorEditor', async () => {
    const onUpdateCriterion = vi.fn().mockRejectedValue(new Error('PUT /criteria/accuracy → 500'));
    renderSettings({ onUpdateCriterion });

    fireEvent.click(await screen.findByText('Accuracy'));
    const nameInput = screen.getByDisplayValue('Accuracy');
    fireEvent.change(nameInput, { target: { value: 'Accuracy2' } });

    expect((await screen.findByTestId('evaluator-field-error')).textContent).toContain('500');
  });

  it('EditModelModal shows an inline error when the save is rejected', async () => {
    const onSaveModel = vi.fn().mockRejectedValue(new Error('PUT /models/x → 500'));
    renderSettings({ onSaveModel });

    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));
    fireEvent.click(screen.getByText('Save'));

    expect((await screen.findByTestId('edit-model-error')).textContent).toContain('500');
  });
});

describe('SettingsTab rapid double-click guards (fix wave commit 2, BUG-4)', () => {

  it('Add-Evaluator Save: triple-click fires onAddCriterion exactly once', async () => {
    let resolveSave!: () => void;
    const onAddCriterion = vi.fn().mockReturnValue(new Promise<void>((r) => { resolveSave = r; }));
    const props = renderSettings({ onAddCriterion });
    fireEvent.click(await screen.findByText('+ Add judge'));
    fireEvent.change(screen.getByPlaceholderText('Name'), { target: { value: 'New eval' } });
    fireEvent.change(screen.getByTestId('add-evaluator-prompt'), { target: { value: 'Evaluate this.' } });

    const saveBtn = screen.getByText('Save');
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    resolveSave();

    await waitFor(() => expect(props.onAddCriterion).toHaveBeenCalledTimes(1));
  });

  it('Add-Model Save: triple-click fires onAddModel exactly once', async () => {
    let resolveSave!: () => void;
    const onAddModel = vi.fn().mockReturnValue(new Promise<void>((r) => { resolveSave = r; }));
    const props = renderSettings({ onAddModel });
    fireEvent.click(await screen.findByText('+ Add model'));
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: 'foo/bar' } });

    const saveBtn = screen.getByText('Save');
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    resolveSave();

    await waitFor(() => expect(props.onAddModel).toHaveBeenCalledTimes(1));
  });

  it('EditModel Save: triple-click fires onSaveModel exactly once', async () => {
    let resolveSave!: () => void;
    const onSaveModel = vi.fn().mockReturnValue(new Promise<void>((r) => { resolveSave = r; }));
    const props = renderSettings({ onSaveModel });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));

    const saveBtn = screen.getByText('Save');
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    fireEvent.click(saveBtn);
    resolveSave();

    await waitFor(() => expect(props.onSaveModel).toHaveBeenCalledTimes(1));
  });

  it('Save buttons disable while saving is in flight', async () => {
    let resolveSave!: () => void;
    const onAddModel = vi.fn().mockReturnValue(new Promise<void>((r) => { resolveSave = r; }));
    renderSettings({ onAddModel });
    fireEvent.click(await screen.findByText('+ Add model'));
    fireEvent.change(screen.getByPlaceholderText(/provider\/model-id/), { target: { value: 'foo/bar' } });

    const saveBtn = screen.getByText('Save') as HTMLButtonElement;
    fireEvent.click(saveBtn);

    await waitFor(() => expect(saveBtn.disabled).toBe(true));
    resolveSave();
  });
});

describe('SettingsTab params inline text (S1 §2.4)', () => {
  const paramsModel: ModelRegistryEntryPublic = {
    name: 'openai/gpt-5.4-mini',
    baseUrl: 'https://openrouter.ai/api/v1',
    apiKeyMasked: '****',
    params: { max_tokens: 1536, temperature: 0.2 },
    effectiveParams: { max_tokens: 1536, temperature: 0.2, seed: 7 },
  };

  it('renders readable inline params (temp abbreviation, first 3) instead of a raw "N params" badge', async () => {
    renderSettings({ models: [paramsModel] });
    const inline = await screen.findByTestId(`params-inline-${paramsModel.name}`);
    expect(inline.textContent).toContain('max_tokens 1536');
    expect(inline.textContent).toContain('temp 0.2');
    expect(screen.queryByTestId(`params-expanded-${paramsModel.name}`)).toBeNull();
  });

  it('shows "+N" once there are more than 3 params', async () => {
    const many: ModelRegistryEntryPublic = {
      ...paramsModel,
      params: { max_tokens: 1536, temperature: 0.2, top_p: 0.9, seed: 7 },
    };
    renderSettings({ models: [many] });
    const inline = await screen.findByTestId(`params-inline-${many.name}`);
    expect(inline.textContent).toContain('+1');
  });

  it('toggles the raw-JSON expansion independently on click', async () => {
    renderSettings({ models: [paramsModel] });
    const inline = await screen.findByTestId(`params-inline-${paramsModel.name}`);
    fireEvent.click(inline);
    expect(await screen.findByTestId(`params-expanded-${paramsModel.name}`)).toBeTruthy();
    fireEvent.click(inline);
    expect(screen.queryByTestId(`params-expanded-${paramsModel.name}`)).toBeNull();
  });
});

describe('SettingsTab Test button state (S1 §2.5)', () => {
  it('shows "Testing…" while a test is in flight', async () => {
    let resolveTest!: (r: unknown) => void;
    const onTestModel = vi.fn().mockReturnValue(new Promise((r) => { resolveTest = r; }));
    renderSettings({ onTestModel });
    fireEvent.click(screen.getByText('Test'));
    expect(await screen.findByText('Testing…')).toBeTruthy();
    resolveTest({ ok: true, extracted: [], reference: [], matched: 1, total: 1, share: 1,
      tokens: { prompt: 0, completion: 0, reasoning: 0 }, costUsd: 0, latencyMs: 10, message: '' });
  });
});

describe('SettingsTab Remove-model error surfacing (S1 §2.5, wave5 §4.2)', () => {
  it('shows a friendly "used by judge" message on 409, not the raw method/URL/body dump', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onRemoveModel = vi.fn().mockRejectedValue(
      new Error(`DELETE /models/${encodeURIComponent(model.name)} → 409: {"detail":"model referenced by a criterion"}`),
    );
    renderSettings({ onRemoveModel });
    fireEvent.click(screen.getByText('Remove'));

    const err = await screen.findByTestId(`model-field-error-${model.name}`);
    expect(err.textContent).toBe(`Model is used by judge "${criterion.name}" — reassign it first`);
    expect(err.textContent).not.toContain('DELETE');
    expect(err.textContent).not.toContain('409');
    expect(err.textContent).not.toContain('%2F');
  });

  it('lists multiple referencing judges comma-separated', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fluency: Criterion = { ...criterion, id: 'fluency', name: 'Fluency' };
    const onRemoveModel = vi.fn().mockRejectedValue(
      new Error(`DELETE /models/${encodeURIComponent(model.name)} → 409: {"detail":"model referenced by a criterion"}`),
    );
    renderSettings({ onRemoveModel, criteria: [criterion, fluency] });
    fireEvent.click(screen.getByText('Remove'));

    const err = await screen.findByTestId(`model-field-error-${model.name}`);
    expect(err.textContent).toBe('Model is used by judges "Accuracy", "Fluency" — reassign it first');
  });

  it('shows a short human message (status + detail) for any other error, never the raw dump', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onRemoveModel = vi.fn().mockRejectedValue(
      new Error(`DELETE /models/${encodeURIComponent(model.name)} → 500: {"detail":"internal error"}`),
    );
    renderSettings({ onRemoveModel });
    fireEvent.click(screen.getByText('Remove'));

    const err = await screen.findByTestId(`model-field-error-${model.name}`);
    expect(err.textContent).toBe('Could not remove the model (500): internal error');
  });

  it('falls back to a generic message when the error has no parseable status at all', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onRemoveModel = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    renderSettings({ onRemoveModel });
    fireEvent.click(screen.getByText('Remove'));

    const err = await screen.findByTestId(`model-field-error-${model.name}`);
    expect(err.textContent).toBe('Could not remove the model — please try again.');
  });
});

describe('SettingsTab EditModelModal — API key clear (S1 §2.5)', () => {
  it('Save omits apiKey entirely when the field was never touched (does not wipe the stored key)', async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveModel });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(onSaveModel).toHaveBeenCalled());
    const entry = (onSaveModel as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect('apiKey' in entry).toBe(false);
  });

  it('Clear key sends apiKey:"" via its own action', async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveModel });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));
    fireEvent.click(screen.getByTestId('clear-key-btn'));

    await waitFor(() => expect(onSaveModel).toHaveBeenCalled());
    const entry = (onSaveModel as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(entry.apiKey).toBe('');
  });

  it('typing a new key and saving includes the new apiKey verbatim', async () => {
    const onSaveModel = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveModel });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));
    fireEvent.change(screen.getByPlaceholderText('****'), { target: { value: 'sk-new-key' } });
    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => expect(onSaveModel).toHaveBeenCalled());
    const entry = (onSaveModel as ReturnType<typeof vi.fn>).mock.calls[0][1];
    expect(entry.apiKey).toBe('sk-new-key');
  });

  it('renders the read-only Effective params block from the model registry entry', async () => {
    const withEffective: ModelRegistryEntryPublic = {
      ...model,
      params: { max_tokens: 1536 },
      effectiveParams: { max_tokens: 1536, seed: 7 },
    };
    renderSettings({ models: [withEffective] });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));

    const block = await screen.findByTestId('edit-model-effective');
    expect(block.textContent).toContain('max_tokens 1536');
    expect(block.textContent).toContain('seed 7');
  });

  it('BUG-3 (wave2): recomputes the Effective params preview live as the Params textarea changes, instead of staying frozen at dialog-open', async () => {
    const withEffective: ModelRegistryEntryPublic = {
      ...model,
      params: { max_tokens: 1536 },
      effectiveParams: { max_tokens: 1536, seed: 7 },
    };
    renderSettings({ models: [withEffective] });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));

    const paramsInput = screen.getByDisplayValue(/max_tokens/);
    fireEvent.change(paramsInput, { target: { value: JSON.stringify({ max_tokens: 2048 }) } });

    const block = await screen.findByTestId('edit-model-effective');
    expect(block.textContent).toContain('max_tokens 2048');
    expect(block.textContent).not.toContain('seed 7');
    expect(screen.queryByTestId('edit-model-effective-stale-hint')).toBeNull();
  });

  it('BUG-3 (wave2): invalid JSON keeps showing the last valid preview plus a hint, without crashing', async () => {
    const withEffective: ModelRegistryEntryPublic = {
      ...model,
      params: { max_tokens: 1536 },
      effectiveParams: { max_tokens: 1536 },
    };
    renderSettings({ models: [withEffective] });
    fireEvent.click(await screen.findByTestId(`edit-model-btn-${model.name}`));

    const paramsInput = screen.getByDisplayValue(/max_tokens/);
    fireEvent.change(paramsInput, { target: { value: '{not json' } });

    const block = await screen.findByTestId('edit-model-effective');
    expect(block.textContent).toContain('max_tokens 1536');
    expect(await screen.findByTestId('edit-model-effective-stale-hint')).toBeTruthy();
  });
});

describe('SettingsTab Translator card (S4 §3.4)', () => {
  it('renders above Evaluators with model/prompt from translatorConfig; call params stay Model-Registry-only', async () => {
    renderSettings();
    const card = await screen.findByTestId('translator-card');
    expect(within(card).getByText('openai/gpt-5.4-mini', { selector: 'option' })).toBeTruthy();
    expect(screen.getByText('Applies to the next translation run')).toBeTruthy();
    expect(screen.queryByTestId('translator-params')).toBeNull();
    expect(screen.queryByTestId('translator-effective')).toBeNull();
  });

  it('does not render the Translator card when translatorConfig is null, showing the unavailable affordance instead (2026-07-06 prod incident)', () => {
    renderSettings({ translatorConfig: null });
    // Numbered heading now shares text with its nav link ("2. Translator"),
    // so assert on the section landmark instead of bare getByText.
    expect(screen.getByTestId('settings-section-translator')).toBeTruthy();
    expect(screen.queryByTestId('translator-card')).toBeNull();
    expect(screen.getByTestId('translator-config-unavailable')).toBeTruthy();
  });

  it('changing the model select calls onSaveTranslatorConfig immediately', async () => {
    const onSaveTranslatorConfig = vi.fn().mockResolvedValue(undefined);
    const otherModel: ModelRegistryEntryPublic = { ...model, name: 'anthropic/claude' };
    renderSettings({ models: [model, otherModel], onSaveTranslatorConfig });

    const card = await screen.findByTestId('translator-card');
    const select = within(card).getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: otherModel.name } });

    await waitFor(() => expect(onSaveTranslatorConfig).toHaveBeenCalledWith(
      expect.objectContaining({ modelName: otherModel.name }),
    ));
  });

  it('shows an inline error when the save is rejected', async () => {
    const onSaveTranslatorConfig = vi.fn().mockRejectedValue(new Error('PUT /translator-config → 500'));
    const otherModel: ModelRegistryEntryPublic = { ...model, name: 'anthropic/claude' };
    renderSettings({ models: [model, otherModel], onSaveTranslatorConfig });

    const card = await screen.findByTestId('translator-card');
    const select = within(card).getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: otherModel.name } });

    expect((await screen.findByTestId('translator-field-error')).textContent).toContain('500');
  });
});

describe('SettingsTab PromptEditor (S1 §2.3, shared by evaluator + translator)', () => {
  it('defaults to Preview and switches to Edit on click', async () => {
    renderSettings();
    fireEvent.click(await screen.findByText('Accuracy'));
    expect(screen.getByTestId('evaluator-prompt-preview')).toBeTruthy();
    expect(screen.queryByTestId('evaluator-prompt-editor')).toBeNull();

    fireEvent.click(within(screen.getByTestId('evaluator-prompt-toggle')).getByText('Edit'));
    expect(screen.getByTestId('evaluator-prompt-editor')).toBeTruthy();
    expect(screen.queryByTestId('evaluator-prompt-preview')).toBeNull();
  });

  it('moves focus into the textarea (cursor at end) on the preview -> edit transition (keyboard a11y)', async () => {
    renderSettings({ criteria: [{ ...criterion, prompt: 'Rate accuracy.' }] });
    fireEvent.click(await screen.findByText('Accuracy'));

    fireEvent.click(within(screen.getByTestId('evaluator-prompt-toggle')).getByText('Edit'));
    const textarea = screen.getByTestId('evaluator-prompt-editor') as HTMLTextAreaElement;

    expect(document.activeElement).toBe(textarea);
    expect(textarea.selectionStart).toBe(textarea.value.length);
    expect(textarea.selectionEnd).toBe(textarea.value.length);
  });

  it('Save prompt is disabled until the draft differs from the saved prompt, then calls onUpdateCriterion with the full body', async () => {
    const onUpdateCriterion = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onUpdateCriterion, criteria: [{ ...criterion, prompt: 'Rate accuracy.' }] });
    fireEvent.click(await screen.findByText('Accuracy'));
    fireEvent.click(within(screen.getByTestId('evaluator-prompt-toggle')).getByText('Edit'));

    const saveBtn = screen.getByTestId('evaluator-prompt-save') as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);

    const textarea = screen.getByTestId('evaluator-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'Rate accuracy more strictly.' } });
    expect(saveBtn.disabled).toBe(false);
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
    expect(screen.getByText('28 chars')).toBeTruthy();

    fireEvent.click(saveBtn);
    await waitFor(() => expect(onUpdateCriterion).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'accuracy', prompt: 'Rate accuracy more strictly.', name: 'Accuracy' }),
    ));
  });

  it('Revert resets the draft to the saved prompt without saving', async () => {
    renderSettings({ criteria: [{ ...criterion, prompt: 'Original prompt.' }] });
    fireEvent.click(await screen.findByText('Accuracy'));
    fireEvent.click(within(screen.getByTestId('evaluator-prompt-toggle')).getByText('Edit'));

    const textarea = screen.getByTestId('evaluator-prompt-editor') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Changed.' } });
    fireEvent.click(screen.getByTestId('evaluator-prompt-revert'));

    expect(textarea.value).toBe('Original prompt.');
    expect((screen.getByTestId('evaluator-prompt-save') as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows a server rejection inline via the existing evaluator-field-error pattern', async () => {
    const onUpdateCriterion = vi.fn().mockRejectedValue(new Error('PUT /criteria/accuracy → 500'));
    renderSettings({ onUpdateCriterion, criteria: [{ ...criterion, prompt: 'P.' }] });
    fireEvent.click(await screen.findByText('Accuracy'));
    fireEvent.click(within(screen.getByTestId('evaluator-prompt-toggle')).getByText('Edit'));
    fireEvent.change(screen.getByTestId('evaluator-prompt-editor'), { target: { value: 'P2.' } });
    fireEvent.click(screen.getByTestId('evaluator-prompt-save'));

    expect((await screen.findByTestId('evaluator-field-error')).textContent).toContain('500');
  });
});

describe('SettingsTab Grounding card', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('renders the Grounding section with the model select populated; call params stay Model-Registry-only', async () => {
    renderSettings();

    // Numbered heading now shares text with its nav link ("4. Grounding"),
    // so assert on the section landmark instead of bare getByText.
    expect(await screen.findByTestId('settings-section-grounding')).toBeTruthy();
    const editor = await screen.findByTestId('grounding-editor');
    const select = editor.querySelector('select') as HTMLSelectElement;
    expect(select.value).toBe(model.name);
    expect(select.querySelectorAll('option')).toHaveLength(1);
    expect(within(editor).queryByTestId('grounding-params-badge')).toBeNull();
  });

  it('does not render the Grounding editor when groundingConfig is null, showing the unavailable affordance instead (2026-07-06 prod incident)', () => {
    renderSettings({ groundingConfig: null });

    expect(screen.getByTestId('settings-section-grounding')).toBeTruthy();
    expect(screen.queryByTestId('grounding-editor')).toBeNull();
    expect(screen.getByTestId('grounding-config-unavailable')).toBeTruthy();
  });

  // BUG-1 (wave2): Grounding's prompt editor used to be a bare textarea that
  // auto-saved on blur ONLY — an edit followed by e.g. tabbing straight to a
  // button (never blurring into empty space) silently never reached the
  // server. It now reuses the shared PromptEditor (Save prompt / Revert /
  // char count / "Unsaved changes"), the same as Translator/Judges/Refiner —
  // these tests mirror the Refiner card's own PromptEditor coverage above.
  it('BUG-1 (wave2): renders the shared PromptEditor with explicit Save/Revert, not a bare auto-saving textarea', async () => {
    renderSettings();
    const editor = await screen.findByTestId('grounding-editor');

    expect(within(editor).getByTestId('grounding-prompt-toggle')).toBeTruthy();
    fireEvent.click(within(within(editor).getByTestId('grounding-prompt-toggle')).getByText('Edit'));
    expect(within(editor).getByTestId('grounding-prompt-editor')).toBeTruthy();
    expect(within(editor).getByTestId('grounding-prompt-save')).toBeTruthy();
    expect(within(editor).getByTestId('grounding-prompt-revert')).toBeTruthy();
  });

  it('BUG-1 (wave2): editing the prompt and clicking Save prompt calls onSaveGroundingConfig with the full body', async () => {
    const onSaveGroundingConfig = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveGroundingConfig });
    const editor = await screen.findByTestId('grounding-editor');

    fireEvent.click(within(within(editor).getByTestId('grounding-prompt-toggle')).getByText('Edit'));
    const textarea = within(editor).getByTestId('grounding-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'New judge prompt.' } });
    fireEvent.click(within(editor).getByTestId('grounding-prompt-save'));

    await waitFor(() => expect(onSaveGroundingConfig).toHaveBeenCalledWith({
      modelName: groundingConfig.modelName,
      prompt: 'New judge prompt.',
      params: groundingConfig.params,
    }));
  });

  it('BUG-1 (wave2): a blur without clicking Save prompt does NOT save (the old silent-loss path)', async () => {
    const onSaveGroundingConfig = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveGroundingConfig });
    const editor = await screen.findByTestId('grounding-editor');

    fireEvent.click(within(within(editor).getByTestId('grounding-prompt-toggle')).getByText('Edit'));
    const textarea = within(editor).getByTestId('grounding-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'Edited but never saved.' } });
    fireEvent.blur(textarea);

    expect(onSaveGroundingConfig).not.toHaveBeenCalled();
    expect(screen.getByText('Unsaved changes')).toBeTruthy();
  });

  it('changing the model select calls onSaveGroundingConfig immediately', async () => {
    const onSaveGroundingConfig = vi.fn().mockResolvedValue(undefined);
    const otherModel: ModelRegistryEntryPublic = { ...model, name: 'anthropic/claude' };
    renderSettings({ models: [model, otherModel], onSaveGroundingConfig });

    const editor = await screen.findByTestId('grounding-editor');
    const select = editor.querySelector('select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: otherModel.name } });

    await waitFor(() => expect(onSaveGroundingConfig).toHaveBeenCalledWith(
      expect.objectContaining({ modelName: otherModel.name }),
    ));
  });

  it('shows an inline error when the save is rejected', async () => {
    const onSaveGroundingConfig = vi.fn().mockRejectedValue(new Error('PUT /grounding-config → 500'));
    renderSettings({ onSaveGroundingConfig });
    const editor = await screen.findByTestId('grounding-editor');

    fireEvent.click(within(within(editor).getByTestId('grounding-prompt-toggle')).getByText('Edit'));
    const textarea = within(editor).getByTestId('grounding-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'New judge prompt.' } });
    fireEvent.click(within(editor).getByTestId('grounding-prompt-save'));

    expect((await screen.findByTestId('grounding-field-error')).textContent).toContain('500');
  });
});

describe('SettingsTab 5-section layout with mini-nav (EMNLP sprint)', () => {
  it('renders all 5 sections in order: Model Registry, Translator, Judges, Grounding, Refiner', async () => {
    renderSettings();
    const titles = (await screen.findAllByTestId('settings-section-title')).map((el) => el.textContent);
    expect(titles).toEqual([
      '1. Model Registry',
      '2. Translator',
      '3. Judges',
      '4. Grounding',
      '5. Refiner',
    ]);
  });

  it('renders a sticky mini-nav with one anchor link per section, in the same order', async () => {
    renderSettings();
    const nav = await screen.findByTestId('settings-nav');
    const links = within(nav).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual([
      '1. Model Registry',
      '2. Translator',
      '3. Judges',
      '4. Grounding',
      '5. Refiner',
    ]);
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '#settings-model-registry',
      '#settings-translator',
      '#settings-judges',
      '#settings-grounding',
      '#settings-refiner',
    ]);
  });
});

describe('SettingsTab Refiner card (EMNLP sprint)', () => {
  it('renders with model/prompt from refinerConfig; call params stay Model-Registry-only', async () => {
    renderSettings();
    const card = await screen.findByTestId('refiner-card');
    expect(within(card).getByText(model.name, { selector: 'option' })).toBeTruthy();
    expect(within(card).getByTestId('refiner-prompt-preview')).toBeTruthy();
    expect(within(card).queryByTestId('refiner-params')).toBeNull();
  });

  it('does not render the Refiner card when refinerConfig is null, showing the unavailable affordance instead', () => {
    renderSettings({ refinerConfig: null });
    expect(screen.getByTestId('settings-section-refiner')).toBeTruthy();
    expect(screen.queryByTestId('refiner-card')).toBeNull();
    expect(screen.getByTestId('refiner-config-unavailable')).toBeTruthy();
  });

  it('changing the model select calls onSaveRefinerConfig immediately', async () => {
    const onSaveRefinerConfig = vi.fn().mockResolvedValue(undefined);
    const otherModel: ModelRegistryEntryPublic = { ...model, name: 'anthropic/claude' };
    renderSettings({ models: [model, otherModel], onSaveRefinerConfig });

    const card = await screen.findByTestId('refiner-card');
    const select = within(card).getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: otherModel.name } });

    await waitFor(() => expect(onSaveRefinerConfig).toHaveBeenCalledWith(
      expect.objectContaining({ modelName: otherModel.name }),
    ));
  });

  it('saving the prompt calls onSaveRefinerConfig with the full body', async () => {
    const onSaveRefinerConfig = vi.fn().mockResolvedValue(undefined);
    renderSettings({ onSaveRefinerConfig });
    const card = await screen.findByTestId('refiner-card');

    fireEvent.click(within(within(card).getByTestId('refiner-prompt-toggle')).getByText('Edit'));
    const textarea = within(card).getByTestId('refiner-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'Rewrite addressing all findings.' } });
    fireEvent.click(within(card).getByTestId('refiner-prompt-save'));

    await waitFor(() => expect(onSaveRefinerConfig).toHaveBeenCalledWith(
      expect.objectContaining({ prompt: 'Rewrite addressing all findings.' }),
    ));
  });

  it('shows an inline error when the save is rejected', async () => {
    const onSaveRefinerConfig = vi.fn().mockRejectedValue(new Error('PUT /refiner-config → 500'));
    renderSettings({ onSaveRefinerConfig });
    const card = await screen.findByTestId('refiner-card');

    fireEvent.click(within(within(card).getByTestId('refiner-prompt-toggle')).getByText('Edit'));
    const textarea = within(card).getByTestId('refiner-prompt-editor');
    fireEvent.change(textarea, { target: { value: 'New refiner prompt.' } });
    fireEvent.click(within(card).getByTestId('refiner-prompt-save'));

    expect((await screen.findByTestId('refiner-field-error')).textContent).toContain('500');
  });
});

describe('SettingsTab Model Registry — Host + Roles columns (EMNLP sprint)', () => {
  it('derives a friendly host label from baseUrl (openrouter / local vLLM / raw hostname fallback)', async () => {
    const openrouterModel: ModelRegistryEntryPublic = { ...model, name: 'a/a', baseUrl: 'https://openrouter.ai/api/v1' };
    const localModel: ModelRegistryEntryPublic = { ...model, name: 'b/b', baseUrl: 'http://localhost:8001/v1' };
    const otherHostModel: ModelRegistryEntryPublic = { ...model, name: 'c/c', baseUrl: 'https://api.example.com/v1' };
    renderSettings({ models: [openrouterModel, localModel, otherHostModel] });

    const registry = await screen.findByTestId('settings-section-model-registry');
    expect(within(registry).getByText('openrouter')).toBeTruthy();
    expect(within(registry).getByText('local vLLM')).toBeTruthy();
    expect(within(registry).getByText('api.example.com')).toBeTruthy();
  });

  it('badges a model referenced by all 4 roles (criteria + translator + grounding + refiner) as "default · all roles"', async () => {
    // Default fixtures already point criteria/translatorConfig/groundingConfig/refinerConfig at model.name.
    renderSettings();

    const badge = await screen.findByTestId(`role-badge-${model.name}`);
    expect(badge.textContent).toBe('default · all roles');
  });

  it('badges a model referenced by only a subset of roles with the comma-separated list', async () => {
    const other: ModelRegistryEntryPublic = { ...model, name: 'anthropic/claude' };
    renderSettings({
      models: [model, other],
      translatorConfig: { ...translatorConfig, modelName: other.name },
    });

    const badge = await screen.findByTestId(`role-badge-${other.name}`);
    expect(badge.textContent).toBe('translator');
  });

  it('shows a dash for a model referenced by no role at all', async () => {
    const unused: ModelRegistryEntryPublic = { ...model, name: 'unused/model' };
    renderSettings({ models: [model, unused] });

    const badge = await screen.findByTestId(`role-badge-${unused.name}`);
    expect(badge.textContent).toBe('—');
  });
});
