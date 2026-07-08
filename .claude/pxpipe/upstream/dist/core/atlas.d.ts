/** Latin advance width in pixels. CJK glyphs advance 10px (= 2 × this). */
export declare const ATLAS_CELL_W = 5;
/** Cell height in pixels. */
export declare const ATLAS_CELL_H = 8;
/** Distance from cell top to baseline. */
export declare const ATLAS_ASCENT = 7;
/** Distance from baseline to cell bottom. */
export declare const ATLAS_DESCENT = 1;
/** Primary font size used when rasterizing ASCII/code glyphs. */
export declare const ATLAS_FONT_PX = 8;
/** Font family label used at build time. Renderer never re-loads the font. */
export declare const ATLAS_FONT_FAMILY = "Spleen 5x8 ASCII + Unifont 8px fallback";
/** Profile used to build this atlas. */
export declare const ATLAS_PROFILE = "full-bmp";
/** Sorted codepoint table. `ATLAS_CODEPOINTS[rank]` is the codepoint stored
 *  at `rank` in OFFSETS / WIDE_FLAGS / PIXELS. */
export declare const ATLAS_CODEPOINTS: Uint32Array;
/** BIT offset into ATLAS_PIXELS for the glyph at each rank. */
export declare const ATLAS_OFFSETS: Uint32Array;
/** 1 if the glyph at this rank is double-wide (East Asian Wide), 0 otherwise. */
export declare const ATLAS_WIDE_FLAGS: Uint8Array;
/** Bit-packed 1-bit pixel data, MSB-first. Runtime extraction:
 *    bitIdx  = OFFSETS[rank] + row * srcW + col
 *    byteIdx = bitIdx >>> 3
 *    bitOff  = 7 - (bitIdx & 7)
 *    pixel   = (ATLAS_PIXELS[byteIdx] >>> bitOff) & 1
 *  where srcW is CELL_W (narrow) or 2*CELL_W (wide, per WIDE_FLAGS[rank]). */
export declare const ATLAS_PIXELS: Uint8Array;
/** Number of glyphs in the atlas. */
export declare const ATLAS_NUM_GLYPHS: number;
/** Binary-search the sparse codepoint table. Returns rank (≥0) or -1 if the
 *  codepoint is not in the atlas. Hot path; called once per rendered char. */
export declare function atlasRank(codepoint: number): number;
//# sourceMappingURL=atlas.d.ts.map