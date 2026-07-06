import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createCriterion, deleteModel, exportUrl } from './api-client';
import type { Criterion } from './api-client';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const criterion: Criterion = {
  id: 'accuracy', name: 'Accuracy', modelName: 'm', prompt: '', scaleMin: 1, scaleMax: 10,
  weight: 0.5, color: '#fff', enabled: true,
};

describe('wave-4 Б5: admin-token gating removed', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('createCriterion sends no Authorization header on any call', async () => {
    await createCriterion(criterion);
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers?.Authorization).toBeUndefined();
  });
});

describe('del() surfaces the response body (S1 §2.5 — honest Remove errors)', () => {
  it('deleteModel rejects with the backend detail text, not a bare status code', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'model referenced by a criterion' }), { status: 409 }),
    ));
    await expect(deleteModel('foo/bar')).rejects.toThrow('model referenced by a criterion');
    vi.unstubAllGlobals();
  });

  it('resolves silently on 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(deleteModel('foo/bar')).resolves.toBeUndefined();
    vi.unstubAllGlobals();
  });
});

describe('exportUrl (S6)', () => {
  it('builds a same-origin URL with the requested format', () => {
    expect(exportUrl(7, 'xlsx')).toBe('/api/documents/7/export?format=xlsx');
    expect(exportUrl(7, 'md')).toBe('/api/documents/7/export?format=md');
  });
});
