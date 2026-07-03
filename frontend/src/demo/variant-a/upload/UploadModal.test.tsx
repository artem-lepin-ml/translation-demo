import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import UploadModal, { SidePanel, Step2 } from './UploadModal';
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
    expect(screen.queryByTestId('upload-lang-hint')).toBeNull();
  });
});
