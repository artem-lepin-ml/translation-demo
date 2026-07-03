import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createCriterion } from './api-client';
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
