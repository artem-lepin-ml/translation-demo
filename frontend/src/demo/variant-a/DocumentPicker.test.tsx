import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import DocumentPicker, { termsStatusPresentation } from './DocumentPicker';
import type { DocumentSummary } from '../api-client';

afterEach(cleanup);

function doc(over: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: 1, title: 'Herodotus, Book I', sourceLang: 'ru', targetLang: 'en',
    nParagraphs: 12, origin: 'seed',
    ...over,
  };
}

describe('DocumentPicker', () => {
  it('renders one card per document plus a trailing blank-document card', () => {
    const documents = [doc({ id: 1 }), doc({ id: 2 }), doc({ id: 3 })];
    render(<DocumentPicker documents={documents} onSelect={vi.fn()} onCreateBlank={vi.fn()} />);

    expect(screen.getByTestId('doc-picker')).toBeTruthy();
    expect(screen.getByTestId('doc-card-1')).toBeTruthy();
    expect(screen.getByTestId('doc-card-2')).toBeTruthy();
    expect(screen.getByTestId('doc-card-3')).toBeTruthy();
    expect(screen.getByTestId('doc-card-blank')).toBeTruthy();
  });

  it('renders only the blank card when there are zero documents (not an error state)', () => {
    render(<DocumentPicker documents={[]} onSelect={vi.fn()} onCreateBlank={vi.fn()} />);
    expect(screen.getByTestId('doc-card-blank')).toBeTruthy();
    expect(screen.queryByTestId(/^doc-card-\d+$/)).toBeNull();
  });

  it('shows title, lang pair, and paragraph count derived from the real DocumentSummary fields', () => {
    render(
      <DocumentPicker
        documents={[doc({ id: 5, title: 'Iliad', sourceLang: 'ru', targetLang: 'en', nParagraphs: 42 })]}
        onSelect={vi.fn()}
        onCreateBlank={vi.fn()}
      />,
    );
    const card = screen.getByTestId('doc-card-5');
    expect(card.textContent).toContain('Iliad');
    expect(card.textContent).toContain('Russian');
    expect(card.textContent).toContain('English');
    expect(card.textContent).toContain('42');
  });

  it('clicking a document card calls onSelect with that document id', () => {
    const onSelect = vi.fn();
    render(
      <DocumentPicker
        documents={[doc({ id: 1 }), doc({ id: 7 })]}
        onSelect={onSelect}
        onCreateBlank={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('doc-card-7'));
    expect(onSelect).toHaveBeenCalledWith(7);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('clicking the blank-document card calls onCreateBlank, not onSelect', () => {
    const onSelect = vi.fn();
    const onCreateBlank = vi.fn();
    render(<DocumentPicker documents={[doc()]} onSelect={onSelect} onCreateBlank={onCreateBlank} />);
    fireEvent.click(screen.getByTestId('doc-card-blank'));
    expect(onCreateBlank).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('renders the Glossa-MT brand on its own header', () => {
    render(<DocumentPicker documents={[]} onSelect={vi.fn()} onCreateBlank={vi.fn()} />);
    expect(screen.getByText('Glossa-MT')).toBeTruthy();
  });
});

describe('termsStatusPresentation (status dot + label, single source of truth for the picker card)', () => {
  it('maps done → green "Terminology ready"', () => {
    expect(termsStatusPresentation('done')).toEqual({ text: 'Terminology ready', tone: 'green' });
  });

  it('maps running → yellow "Extracting terminology…"', () => {
    expect(termsStatusPresentation('running')).toEqual({ text: 'Extracting terminology…', tone: 'yellow' });
  });

  it('maps failed → red "Terminology extraction failed"', () => {
    expect(termsStatusPresentation('failed')).toEqual({ text: 'Terminology extraction failed', tone: 'red' });
  });

  it('maps none/undefined → dim "No terminology extracted"', () => {
    expect(termsStatusPresentation('none')).toEqual({ text: 'No terminology extracted', tone: 'dim' });
    expect(termsStatusPresentation(undefined)).toEqual({ text: 'No terminology extracted', tone: 'dim' });
  });
});
