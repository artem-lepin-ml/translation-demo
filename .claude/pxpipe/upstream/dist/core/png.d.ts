/**
 * Minimal PNG encoder (grayscale + RGB, 8-bit, filter=None, single IDAT).
 * Pure Uint8Array — uses CompressionStream (Node 18+, Workers, browsers); no Buffer/node:zlib.
 */
/** Encode a single-channel (grayscale) buffer as PNG bytes. pixels is row-major, length = width × height. */
export declare function encodeGrayPng(pixels: Uint8Array, width: number, height: number): Promise<Uint8Array>;
/** Encode an RGB (3 bytes/pixel, R,G,B) buffer as PNG bytes (colorType 2 = truecolor). length = width × height × 3. */
export declare function encodeRgbPng(pixels: Uint8Array, width: number, height: number): Promise<Uint8Array>;
/** Base64-encode bytes. Chunks to avoid call-stack blow-up from String.fromCharCode(...bigArray). */
export declare function bytesToBase64(bytes: Uint8Array): string;
//# sourceMappingURL=png.d.ts.map