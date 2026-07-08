/**
 * Shared JSON-Schema annotation stripper for BOTH transformer paths
 * (Anthropic/Claude in transform.ts and OpenAI/GPT in openai.ts).
 *
 * The whole point of this module is that the strip is *structure-aware*: the
 * literal key `description` (also `title`, `default`, `examples`) is a schema
 * ANNOTATION in one place and a user-defined PROPERTY NAME in another. The
 * `task` tool, for example, has a required parameter literally named
 * `description`. A naive "drop every key called description" walk deletes that
 * property, leaving `required: ["description"]` pointing at nothing — the model
 * then can't emit it and the host rejects the tool call ("Missing key at
 * [\"description\"]"). So we only strip annotation keywords at the schema-node
 * level and recurse into the *values* of `properties`/`$defs`/etc., never
 * treating their keys as annotations.
 */
/** Strip long-form metadata from a JSON Schema node, preserving the structural
 *  keys a tool-use validator needs. Strips: description, title, examples,
 *  default, $schema, $id, $comment, long format. Recurses into
 *  properties/oneOf/anyOf/allOf/items etc. Returns a fresh object — never
 *  mutates the input. Property *names* (the keys inside `properties` and
 *  friends) are preserved even when they collide with annotation keywords. */
export declare function stripSchemaDescriptions(node: unknown, depth?: number): unknown;
/** JSON Schema keys that carry a parameter *contract* (shape/values), as opposed
 *  to pure annotations. Used to decide whether a stripped schema still tells the
 *  validator anything — if none survive, the strip is not worth shipping. */
export declare const SCHEMA_STRUCTURAL_KEYS: readonly ["properties", "patternProperties", "oneOf", "anyOf", "allOf", "items", "$ref", "enum", "const"];
/** True when the schema node retains at least one structural (contract) key. */
export declare function schemaHasStructure(schema: Record<string, unknown>): boolean;
//# sourceMappingURL=schema-strip.d.ts.map