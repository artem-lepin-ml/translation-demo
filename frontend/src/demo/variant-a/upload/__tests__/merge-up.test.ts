import { describe, expect, it } from 'vitest';
import { mergeUp } from '../UploadModal';

describe('mergeUp', () => {
  it('merges into previous, keeps rest', () => {
    expect(mergeUp(['a', 'b', 'c'], 1)).toEqual(['a\nb', 'c']);
  });
  it('no-op at index 0', () => {
    expect(mergeUp(['a', 'b'], 0)).toEqual(['a', 'b']);
  });
});
