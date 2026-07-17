import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import UploadModal, { SidePanel, Step2, nextBlockReason } from './UploadModal';
import UploadIcon from './UploadIcon';
import { useDemoStore } from '../../store';
import type { DemoStore } from '../../store';

vi.mock('../../store', () => ({
  useDemoStore: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// 5 enabled criteria mirrors the seeded default (precompute cost captions assume this count).
const FIVE_ENABLED_CRITERIA = Array.from({ length: 5 }, (_, i) => ({ id: `c${i}`, enabled: true })) as DemoStore['criteria'];

function mockCreateDoc(createDoc: DemoStore['createDoc']) {
  vi.mocked(useDemoStore).mockImplementation(
    ((selector: (s: DemoStore) => unknown) =>
      selector({ createDoc, criteria: FIVE_ENABLED_CRITERIA } as DemoStore)) as typeof useDemoStore,
  );
}

function renderStep2(createDoc: DemoStore['createDoc']) {
  mockCreateDoc(createDoc);
  return render(
    <Step2
      title="t"
      srcLang="ru"
      tgtLang="en"
      srcParas={['один']}
      tgtParas={['one']}
      onBack={vi.fn()}
    />,
  );
}

describe('UploadModal Step2 submit (C2 double-submit guard)', () => {
  it('fires exactly one createDoc call for 3 synchronous submit clicks', () => {
    let resolveCreate: () => void = () => {};
    const createDoc = vi.fn(
      () => new Promise<void>((resolve) => { resolveCreate = resolve; }),
    );
    renderStep2(createDoc);

    // Raw DOM .click() (not RTL's act()-wrapped fireEvent) to reproduce the
    // real race: 3 rapid clicks before React commits the `submitting` state
    // update that disables the button. This mirrors what happened live
    // tonight (3 duplicate docs, N x real precompute spend).
    const btn = screen.getByTestId('upload-submit') as HTMLButtonElement;
    btn.click();
    btn.click();
    btn.click();

    expect(createDoc).toHaveBeenCalledTimes(1);
    resolveCreate();
  });
});

describe('UploadModal SidePanel sticky error (C1)', () => {
  function ControlledSidePanel() {
    const [state, setState] = useState<{ text: string; lang: string; busy: boolean; error: string | null }>({
      text: '', lang: 'ru', busy: false, error: 'Unsupported file type',
    });
    return (
      <SidePanel
        id="source"
        label="Source"
        langPlaceholder="Russian"
        state={state}
        onChange={(patch) => setState((s) => ({ ...s, ...patch }))}
      />
    );
  }

  it('clears the error once the user types valid text', () => {
    render(<ControlledSidePanel />);
    expect(screen.getByTestId('panel-source-error')).toBeTruthy();

    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст абзаца' } });

    expect(screen.queryByTestId('panel-source-error')).toBeNull();
  });
});

describe('UploadModal SidePanel CRLF counter (T1-F3: raw CR bytes inflated the char count)', () => {
  function ControlledSidePanel() {
    const [state, setState] = useState<{ text: string; lang: string; busy: boolean; error: string | null }>({
      text: '', lang: 'ru', busy: false, error: null,
    });
    return (
      <SidePanel
        id="source"
        label="Source"
        langPlaceholder="Russian"
        state={state}
        onChange={(patch) => setState((s) => ({ ...s, ...patch }))}
      />
    );
  }

  it('normalizes CRLF to LF on paste/type, so the counter reports the real (post-normalize) length', () => {
    render(<ControlledSidePanel />);
    const textarea = screen.getByTestId('panel-source-textarea') as HTMLTextAreaElement;

    // Two paragraphs of 5 chars each, CRLF-joined: raw 5+2+2+5=14 chars, real (LF) 5+1+1+5=12.
    fireEvent.change(textarea, { target: { value: 'aaaaa\r\n\r\nbbbbb' } });

    expect(textarea.value).toBe('aaaaa\n\nbbbbb');
    expect(textarea.value).not.toContain('\r');
    expect(screen.getByTestId('panel-source-counter').textContent).toContain('12 chars');
  });

  it('reports the same char count for an equivalent LF-only paste (no CRLF inflation either way)', () => {
    render(<ControlledSidePanel />);
    const textarea = screen.getByTestId('panel-source-textarea') as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'aaaaa\n\nbbbbb' } });

    expect(screen.getByTestId('panel-source-counter').textContent).toContain('12 chars');
  });
});

describe('UploadModal Step2 precompute caption (LOW-c planned count/cost)', () => {
  it('computes min(N,12) planned paragraphs and planned x5x$0.004 cost', () => {
    mockCreateDoc(vi.fn(() => new Promise<void>(() => {})));
    const paras = Array.from({ length: 3 }, (_, i) => `para ${i}`);
    render(<Step2 title="t" srcLang="ru" tgtLang="en" srcParas={paras} tgtParas={paras} onBack={vi.fn()} />);

    expect(screen.getByText(/first 3 ¶, ~\$0\.06, in background/)).toBeTruthy();
  });

  it('caps planned paragraphs at 12 for larger documents', () => {
    mockCreateDoc(vi.fn(() => new Promise<void>(() => {})));
    const paras = Array.from({ length: 20 }, (_, i) => `para ${i}`);
    render(<Step2 title="t" srcLang="ru" tgtLang="en" srcParas={paras} tgtParas={paras} onBack={vi.fn()} />);

    expect(screen.getByText(/first 12 ¶, ~\$0\.24, in background/)).toBeTruthy();
  });
});

describe('UploadModal Step1 language inputs', () => {
  it('keeps Next disabled until both languages are typed', () => {
    mockCreateDoc(vi.fn(() => new Promise<void>(() => {})));
    render(<UploadModal />);
    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст абзаца' } });
    fireEvent.change(screen.getByTestId('panel-target-textarea'), { target: { value: 'Paragraph text' } });
    fireEvent.change(screen.getByPlaceholderText('Title'), { target: { value: 'Doc' } });
    expect(screen.getByText('Next →').closest('button')).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByTestId('panel-source-lang'), { target: { value: 'Russian' } });
    fireEvent.change(screen.getByTestId('panel-target-lang'), { target: { value: 'English' } });
    expect(screen.getByText('Next →').closest('button')).toHaveProperty('disabled', false);
  });

  it('shows a hint when a language field is empty so the disabled Next is not mysterious', () => {
    mockCreateDoc(vi.fn(() => new Promise<void>(() => {})));
    render(<UploadModal />);
    expect(screen.getByTestId('upload-lang-hint').textContent).toContain('Enter source and target languages to continue');

    fireEvent.change(screen.getByTestId('panel-source-lang'), { target: { value: 'Russian' } });
    expect(screen.getByTestId('upload-lang-hint')).toBeTruthy(); // target still empty

    fireEvent.change(screen.getByTestId('panel-target-lang'), { target: { value: 'English' } });
    // Both languages are now filled but no text was ever typed — the hint
    // stays, now naming the REAL blocker (S3 §2.3 nextBlockReason), not the
    // (now-resolved) language gap.
    expect(screen.getByTestId('upload-lang-hint').textContent).toContain('Add source and translation text to continue');

    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст' } });
    fireEvent.change(screen.getByTestId('panel-target-textarea'), { target: { value: 'Text' } });
    expect(screen.queryByTestId('upload-lang-hint')).toBeNull();
  });
});

describe('nextBlockReason (S3 §2.3)', () => {
  it('names the language gap first', () => {
    expect(nextBlockReason('', '', '', '', false)).toBe('Enter source and target languages to continue');
    expect(nextBlockReason('Russian', '', '', '', false)).toBe('Enter source and target languages to continue');
  });

  it('names the missing text once languages are set (paste mode)', () => {
    expect(nextBlockReason('Russian', 'English', '', '', false))
      .toBe('Add source and translation text to continue');
    expect(nextBlockReason('Russian', 'English', 'Текст', '', false))
      .toBe('Add source and translation text to continue');
  });

  it('only requires source text in AI-translate mode', () => {
    expect(nextBlockReason('Russian', 'English', '', '', true)).toBe('Add source text to continue');
    expect(nextBlockReason('Russian', 'English', 'Текст', '', true)).toBeNull();
  });

  it('is null once everything required is filled', () => {
    expect(nextBlockReason('Russian', 'English', 'Текст', 'Text', false)).toBeNull();
  });
});

describe('UploadIcon', () => {
  it('renders an inline SVG (no emoji)', () => {
    const { container } = render(<UploadIcon />);
    expect(container.querySelector('svg')).toBeTruthy();
    expect(container.textContent).toBe('');
  });
});

describe('UploadModal dropzone drag state (S3 §2.2)', () => {
  it('adds va-upload-drop-active and swaps the placeholder on dragenter, removes both on dragleave', () => {
    mockCreateDoc(vi.fn());
    render(<UploadModal />);
    const panel = screen.getByTestId('panel-source');
    const textarea = screen.getByTestId('panel-source-textarea');

    expect(panel.className).not.toContain('va-upload-drop-active');
    fireEvent.dragEnter(textarea);
    expect(panel.className).toContain('va-upload-drop-active');
    expect(textarea.getAttribute('placeholder')).toBe('Drop file to load');

    fireEvent.dragLeave(textarea);
    expect(panel.className).not.toContain('va-upload-drop-active');
  });

  it('clears drop-active state on drop', () => {
    mockCreateDoc(vi.fn());
    render(<UploadModal />);
    const panel = screen.getByTestId('panel-source');
    const textarea = screen.getByTestId('panel-source-textarea');

    fireEvent.dragEnter(textarea);
    expect(panel.className).toContain('va-upload-drop-active');
    fireEvent.drop(textarea, { dataTransfer: { files: [] } });
    expect(panel.className).not.toContain('va-upload-drop-active');
  });
});

describe('UploadModal AI-translate mode (S4 §3.2)', () => {
  it('shows the "Translate with AI" CTA only once source has text and translation is empty', () => {
    mockCreateDoc(vi.fn());
    render(<UploadModal />);
    expect(screen.queryByTestId('ai-translate-cta')).toBeNull();

    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст' } });
    expect(screen.getByTestId('ai-translate-cta')).toBeTruthy();

    fireEvent.change(screen.getByTestId('panel-target-textarea'), { target: { value: 'Text' } });
    expect(screen.queryByTestId('ai-translate-cta')).toBeNull();
  });

  it('enabling AI-translate mode swaps the target textarea for the placeholder card and Next → Create & translate', () => {
    mockCreateDoc(vi.fn());
    render(<UploadModal />);
    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Текст' } });
    fireEvent.click(screen.getByTestId('ai-translate-cta'));

    expect(screen.getByTestId('ai-translate-card')).toBeTruthy();
    expect(screen.queryByTestId('panel-target-textarea')).toBeNull();
    expect(screen.getByText(/Create & translate/)).toBeTruthy();

    fireEvent.click(screen.getByText('↩ Paste translation instead'));
    expect(screen.queryByTestId('ai-translate-card')).toBeNull();
    expect(screen.getByTestId('panel-target-textarea')).toBeTruthy();
  });

  it('submits translate:true with empty targets and skips Step 2 entirely', async () => {
    const createDoc = vi.fn().mockResolvedValue(undefined);
    mockCreateDoc(createDoc);
    render(<UploadModal />);
    fireEvent.change(screen.getByPlaceholderText('Title'), { target: { value: 'Doc' } });
    fireEvent.change(screen.getByTestId('panel-source-lang'), { target: { value: 'Russian' } });
    fireEvent.change(screen.getByTestId('panel-target-lang'), { target: { value: 'English' } });
    fireEvent.change(screen.getByTestId('panel-source-textarea'), { target: { value: 'Первый.\n\nВторой.' } });
    fireEvent.click(screen.getByTestId('ai-translate-cta'));

    const btn = screen.getByTestId('upload-submit-translate') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);

    await vi.waitFor(() => expect(createDoc).toHaveBeenCalledTimes(1));
    expect(createDoc).toHaveBeenCalledWith({
      title: 'Doc',
      sourceLang: 'Russian',
      targetLang: 'English',
      precompute: false,
      translate: true,
      paragraphs: [{ source: 'Первый.', target: '' }, { source: 'Второй.', target: '' }],
    });
    expect(screen.queryByTestId('step2-merge-src-1')).toBeNull(); // Step 2 never rendered
  });
});
