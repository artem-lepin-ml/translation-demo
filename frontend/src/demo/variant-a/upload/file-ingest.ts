import { extractText } from '../../api-client';
import { stripMarkdown } from './md-strip';

export const ACCEPT = '.docx,.md,.txt';

const ERRORS: Record<number, string> = {
  415: 'Unsupported format. Save the document as .docx and upload again',
  422: 'The file is corrupted or is not a Word document (.docx)',
  413: 'File exceeds 5 MB — split the document or paste the text in parts',
};

export function errorMessage(status: number): string {
  return ERRORS[status] ?? `Could not process the file (HTTP ${status})`;
}

/** Share of control/non-printable characters (excluding \n and \t) above which
 * decodeText treats the result as garbage (not text), not just "unusual" text. */
const UNREADABLE_CONTROL_CHAR_RATIO = 0.1;

function controlCharRatio(text: string): number {
  if (text.length === 0) return 0;
  let controls = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0)!;
    if (ch === '\n' || ch === '\t') continue;
    if (code < 0x20 || code === 0x7f) controls++;
  }
  return controls / text.length;
}

/** UTF-8 -> retry windows-1251 on U+FFFD (spec §5.4, legacy RU texts). If even
 * the cp1251 fallback is mostly control chars (a binary, not text), treat the
 * file as unreadable instead of silently pasting mojibake into the textarea. */
export function decodeText(buf: ArrayBuffer): string {
  const utf8 = new TextDecoder('utf-8').decode(buf);
  const decoded = utf8.includes('�') ? new TextDecoder('windows-1251').decode(buf) : utf8;
  if (controlCharRatio(decoded) > UNREADABLE_CONTROL_CHAR_RATIO) {
    throw Object.assign(new Error(errorMessage(422)), { status: 422 });
  }
  return decoded;
}

/** Any supported file type -> plain text for the textarea (SSOT). */
export async function ingestFile(file: File): Promise<string> {
  const name = file.name.toLowerCase();
  if (name.endsWith('.docx')) {
    const { text } = await extractText(file);              // server-side, python-docx
    return text;
  }
  // Drag-n-drop bypasses the accept filter: anything but .md/.txt is 415 (spec §5.8.5: .doc/.pdf)
  if (!name.endsWith('.md') && !name.endsWith('.txt')) {
    throw Object.assign(new Error(errorMessage(415)), { status: 415 });
  }
  const raw = decodeText(await file.arrayBuffer());
  return name.endsWith('.md') ? stripMarkdown(raw) : raw;
}

export function splitParagraphs(text: string): string[] {
  return text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
}
