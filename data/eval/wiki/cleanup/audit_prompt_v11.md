## Role
You are auditing the gold terminology annotation of ONE Russian Wikipedia article on ancient history. Anchors were auto-derived from editors' hyperlinks; some links are not historical terms at all. Flag ONLY clearly irrelevant anchors for removal. A human re-verifies your work afterwards: precision of removals matters more than coverage — IF IN DOUBT, KEEP.

## KEEP (valid anchors)
Historical terms and entities a translator of ancient-history scholarship must render correctly:
- persons (including modern scholars, archaeologists, egyptologists), deities, peoples, dynasties
- places, incl. multiword geographic names and archaeological sites
- languages, scripts, literary works, events, religions
- institutions incl. museums and universities that hold or study artifacts
- titles/offices, social strata, cultures/periods
- lowercase realia with specialized historical translations: artifact types, materials, practices and duties
- adjectives derived from proper names (ethnic, dynastic, cultural)

## REMOVE (flag the line number) — ONLY these categories
1. Modern consumer brands, companies, websites, social media, pop culture.
2. Natural-science vocabulary: genetics (DNA, chromosomes, haplogroups), chemistry (elements, compounds, formulas), modern medicine/biology.
3. Generic everyday words that are no term of art — their translation needs no historical glossary (linked by editors purely for navigation). Includes everyday-object and gift/goods words («серьги», «подарки», «изделия» as ordinary objects) and generic abstract nouns («история», «государство») linked non-terminologically. Capitalization alone does not make a generic word a term — «Серьги» at sentence start is still generic.
4. Service/template links: language tags («англ.», «лат.»), formatting and reference links.
5. Abstract multiword phrases linked for navigation, not term-worthy (e.g. «зарождении государственности», «мировоззрении древних народов»).

## Doubt rule
A word generic in everyday Russian may still be a term HERE if historians translate it in a specialized way (weights, duties, artifact classes, art-historical genres — cf. examples 7 and 8 below). If you hesitate between category 3 and a specialized reading — KEEP. Never remove because a word merely looks common; remove only when it is clearly outside historical terminology.

## Output
Strict JSON only, no other text:
{"remove": [<line numbers>], "reasons": {"<number>": "<reason, ≤8 words>"}}
Empty remove-list is a valid answer.

## Example
Input:
1. «Шампольон» — Иероглифы дешифровал ⟪Шампольон⟫ в 1822 году.
2. «полимеразной цепной реакции» — Родство подтвердили методом ⟪полимеразной цепной реакции⟫.
3. «Instagram» — Музей публикует находки в ⟪Instagram⟫.
4. «стеле» — Законы вырезаны на базальтовой ⟪стеле⟫.
5. «украшения» — В гробнице нашли золотые ⟪украшения⟫.
6. «лат.» — Название происходит от ⟪лат.⟫ castellum.
7. «подать» — Провинции платили ⟪подать⟫ зерном и серебром.
8. «фресками» — Стены дворца украшены ⟪фресками⟫.
9. «мировой культуры» — Памятник имеет значение для ⟪мировой культуры⟫.
Output:
{"remove": [2, 3, 5, 6, 9], "reasons": {"2": "modern genetics method", "3": "modern social media", "5": "generic everyday noun", "6": "language template tag", "9": "abstract navigational phrase"}}
