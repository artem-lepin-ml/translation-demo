import { describe, expect, it } from 'vitest';
import { stripMarkdown } from '../md-strip';

describe('stripMarkdown', () => {
  it('strips headings, emphasis, links; drops images', () => {
    expect(stripMarkdown('# Заголовок\n\n**жирный** и [ссылка](http://x) и ![img](y.png)'))
      .toBe('Заголовок\n\nжирный и ссылка и');
  });
  it('keeps code fence content, drops markers', () => {
    expect(stripMarkdown('```py\nprint(1)\n```')).toBe('print(1)');
  });
  it('joins table cells with em-dash', () => {
    expect(stripMarkdown('| a | b |\n|---|---|\n| c | d |')).toBe('a — b\nc — d');
  });
});
