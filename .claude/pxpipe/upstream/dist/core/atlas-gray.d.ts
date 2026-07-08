/** Latin advance width in pixels. CJK glyphs advance 10px (= 2 × this). */
export declare const ATLAS_GRAY_CELL_W = 5;
/** Cell height in pixels. */
export declare const ATLAS_GRAY_CELL_H = 8;
/** Distance from cell top to baseline. */
export declare const ATLAS_GRAY_ASCENT = 7;
/** Distance from baseline to cell bottom. */
export declare const ATLAS_GRAY_DESCENT = 1;
/** Sorted codepoint table. `ATLAS_GRAY_CODEPOINTS[rank]` is the codepoint at `rank`. */
export declare const ATLAS_GRAY_CODEPOINTS: Uint32Array;
/** BYTE offset into ATLAS_GRAY_PIXELS for the glyph at each rank.
 *  (Unlike the 1-bit atlas, this is a byte offset — 1 byte per pixel.) */
export declare const ATLAS_GRAY_OFFSETS: Uint32Array;
/** 1 if the glyph at this rank is double-wide (East Asian Wide), 0 otherwise. */
export declare const ATLAS_GRAY_WIDE_FLAGS: Uint8Array;
/** Coverage bytes (0-255), one byte per pixel. Runtime extraction:
 *    byteIdx = ATLAS_GRAY_OFFSETS[rank] + gy * srcW + gx
 *    coverage = ATLAS_GRAY_PIXELS[byteIdx]
 *  where srcW is ATLAS_GRAY_CELL_W (narrow) or 2*ATLAS_GRAY_CELL_W (wide). */
export declare const ATLAS_GRAY_PIXELS: Uint8Array;
/** Number of glyphs in the gray atlas. */
export declare const ATLAS_GRAY_NUM_GLYPHS: number;
/** Binary-search the sparse codepoint table. Returns rank (≥0) or -1 if absent.
 *  Mirrors atlasRank() from atlas.ts but operates on ATLAS_GRAY_CODEPOINTS. */
export declare function atlasGrayRank(codepoint: number): number;
//# sourceMappingURL=atlas-gray.d.ts.map