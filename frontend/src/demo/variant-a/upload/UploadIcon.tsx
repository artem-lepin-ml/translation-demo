/**
 * UploadIcon — inline upload glyph (tray + arrow-up), 16×16, stroke=currentColor.
 *
 * Replaces the 📄 emoji on the Upload-file button (S3 §2.1) — no external
 * icon package, matches the mockup's `#ic-upload` symbol 1:1.
 */
export default function UploadIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 15V4M12 4l-4.5 4.5M12 4l4.5 4.5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  );
}
