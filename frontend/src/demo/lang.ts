/** Language display labels. Pilot documents store ISO codes; uploads store
 *  free-text names. Dictionary stays the FIRST lookup step (upload-polish
 *  heritage); BCP-47-shaped input goes through Intl.DisplayNames; anything
 *  else is echoed capitalized. */

const LANG_LABELS: Record<string, string> = { ru: 'Russian', en: 'English' };

/** Loose BCP-47 shape: 2-3 letter primary subtag + optional dash-joined subtags. */
export function isBcp47Like(raw: string): boolean {
  return /^[a-z]{2,3}(-[A-Za-z0-9]+)*$/i.test(raw);
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}

/** raw → human-readable language name.
 *  1) dictionary code→name; 2) BCP-47-like → Intl.DisplayNames (its default
 *  fallback: 'code' echoes unknown-but-well-formed input); 3) free text →
 *  capitalized as-is; any error → raw. */
export function langLabel(raw: string): string {
  const dict = LANG_LABELS[raw.toLowerCase()];
  if (dict) return dict;
  if (isBcp47Like(raw)) {
    try {
      const name = new Intl.DisplayNames(['en'], { type: 'language' }).of(raw);
      if (name) return name;
    } catch {
      return raw;
    }
  }
  return capitalize(raw);
}
