/** Markdown -> plain text (spec §5.4): the owner asked for "plain text". */
export function stripMarkdown(md: string): string {
  let t = md.replace(/\r\n/g, '\n');
  t = t.replace(/^```[^\n]*$/gm, '');                        // code fence markers (content stays)
  t = t.replace(/!\[[^\]]*\]\([^)]*\)/g, '');                // images — drop
  t = t.replace(/\[([^\]]*)\]\(([^)]*)\)/g, '$1');           // links -> text
  t = t.replace(/<[^>\n]+>/g, '');                           // HTML tags
  t = t.replace(/^#{1,6}\s+/gm, '');                         // headings
  t = t.replace(/^>\s?/gm, '');                              // quotes
  t = t.replace(/^([-*_]){3,}\s*$/gm, '');                   // horizontal rules
  t = t.replace(/^\|?[\s:|-]+\|[\s:|-]*$/gm, '');            // table separators (before row conversion!)
  t = t.replace(/^\|(.+)\|\s*$/gm, (_, row: string) =>       // table rows -> " — "
    row.split('|').map((c) => c.trim()).filter(Boolean).join(' — '));
  t = t.replace(/(\*\*|__)(.*?)\1/g, '$2');                  // bold
  t = t.replace(/(\*|_)(?=\S)(.*?)(?<=\S)\1/g, '$2');        // italic
  t = t.replace(/`([^`]*)`/g, '$1');                         // inline code
  t = t.replace(/\n{3,}/g, '\n\n');
  return t.trim();
}
