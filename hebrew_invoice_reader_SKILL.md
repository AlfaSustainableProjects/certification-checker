---
name: hebrew-invoice-reader
description: >
  Use this skill when extracting product names from Hebrew building material delivery
  notes (תעודות משלוח) or invoices — whether from an uploaded image, PDF, or typed-out
  invoice text. Trigger on: any delivery note or invoice upload, "read this invoice",
  "what products are here", "extract materials from this", "check these materials",
  "what's on this delivery note", or any request to identify building material products
  from a document. This skill is essential for accurate extraction — without it Claude
  tends to drop Hebrew prepositions, confuse similar-looking letters, and mix model
  numbers across brands. ALWAYS use it when a delivery note or materials list is involved.
---

# Hebrew Building Materials Invoice Reader

## Your Task

Extract product names from the delivery note (תעודת משלוח), and — only when clearly identifiable — the manufacturer of each product. Return a JSON array of objects, nothing else.

Each object = one product: `{"name": "...", "manufacturer": "..." or null}`. The name is written exactly as it appears in the document, including model codes and grade designations. See "Manufacturer / Company Identification" below for when to fill `manufacturer` and when to leave it `null`.

## Handling Rotated or Upside-Down Scans

Many real delivery notes are photographed or scanned upside down. If text appears mirrored or inverted:
- Rotate mentally and still extract the products
- The supplier logo/letterhead usually appears at the top — use it to orient yourself
- Common upside-down senders: SAKRET Israel (green checkmark logo), LYMA (dark logo)
- If in doubt, look for recognizable brand names (כוחלה, SAKRET, TAMCRETE, VALSIR) regardless of orientation

## Invoice Column Structure

Israeli delivery notes almost always have a table. The **תיאור** (description) column is what you extract from. Ignore all other columns:

| Column | Hebrew name | Extract? |
|---|---|---|
| Item # | #, מס' | ❌ |
| Asset / SKU | אסמ', מק"ט, קוד פריט | ❌ |
| **Description** | **תיאור, תיאור מוצר** | **✅ YES** |
| Unit | יח', ניר | ❌ |
| Quantity | כמות | ❌ |
| Price | מחיר, סה"כ, ₪ | ❌ |

If there is no table (free-form note), extract lines that start with a product name.

## What to Include

- Product / material names (שם מוצר)
- Model codes and grade specifications (e.g., FL810, AD 700, PR-007, C2TES2, MC1)
- Descriptive suffixes that are part of the product name (e.g., "עמיד אש", "עמיד במים", "EXTRA WHITE")
- **Tile dimensions** when they are part of the product identity: `120*120`, `80*180*2`, `180*23*0.65`
- **Pipe sizes** when part of the product name: `3/8"`, `1/2"`, `110mm`
- Color/variant codes for tiles and flooring: `גוון 1010`, `כרמית`, `GREY`, `A3555 HH`

## What to Exclude

- Quantities and units (כמות, ק"ג, ליטר, מ"ר, יח', שק, דלי, ניר)
- Prices and totals (מחיר, סה"כ, ₪, מחיר יחידה)
- Catalog / SKU numbers (מק"ט, ברקוד, אסמ', קוד פריט, VS03..., PO23...) — unless the SKU IS recognizable as the product name
- Customer name, address, phone, company header
- Column headers ("שם מוצר", "כמות", "מחיר", "תיאור" etc.)
- Dates and document numbers
- Lot numbers / shade codes that appear AFTER the product name (e.g., the `672 69-315` in `TAMCRETE MC1 672 69-315` — include only `TAMCRETE MC1`)
- `שק 25 ק"ג` — always packaging, always exclude

- **Delivery, freight, service and fee lines — NEVER products.** Skip any line that describes logistics, a service, or a commercial term rather than a physical material: `הובלה`, `דמי הובלה`, `הובלה נהג`, `הובלה דאבל`, `משלוח`, `שירות`, `הנחה`, `מקדמה`, `פיקדון`, `החזר`.
- **Project / site names and agreement references — not products.** Skip lines like `שוהם - הובלה דאבל לפי "הסכם התקשרות"`, `לפי סיכום`, `לפי הזמנה`, `הזמנת רכש PO...`. A town/site/project name (e.g. שוהם, בית לחיים) is a location, not a product. Only extract physical building-material products.

## Hebrew Letter Disambiguation

When reading from photos, scans, or handwriting, take extra care with these confusable pairs:

| Confused pair | Key visual tell | Typical in context |
|---|---|---|
| **ב** (bet) vs **כ** (kaf) | כ has a more open downward curve; ב is rounder | "עמיד **ב**מים" — the ב here is crucial |
| **ד** (dalet) vs **ר** (resh) | ד has a sharper 90° top-right corner; ר is rounded | "לוח **ג**בס" — גבס not גרס |
| **ה** (he) vs **ח** (khet) vs **ת** (tav) | ה has a gap at top-right; ח is closed all around; ת has small feet | "**ח**סין אש" (not הסין) |
| **ו** (vav) vs **ז** (zayin) | ז has a horizontal top stroke; ו is just a vertical line | common in word-medial position |
| **נ** sofit (ן) vs **כ** sofit (ך) | ן descends in a straight line; ך has a slight curve | "תקן", not "תקך" |
| **מ** (mem) vs **ס** (samekh) | מ has an open bottom-right gap; ס is fully enclosed | "**מ**ים" vs "**ס**לע" |

If you read something that produces a nonsense Hebrew word, try the confusable letter.

## Latin Letter and Digit Disambiguation

| Characters | Rule of thumb | Example |
|---|---|---|
| **O** vs **0** | Letter O inside brand names; digit 0 in numeric strings | "OC200" — first char is letter O |
| **l** vs **1** vs **I** | Digit 1 in numeric codes; letter L in model names | "FL810" — L is a letter, 810 are digits |
| **B** vs **8** | Usually letter B following other letters | "TRBR-3/8" not "TR8R-3/8" |
| **S** vs **5** | Letter S at start of brand names | "SIKA", not "5IKA" |
| **G** vs **6** | Letter G in brand names | "GREY" not "6REY" |

## Preposition Rule — Critical

Hebrew prepositions **ב / ל / מ / כ / ש** attach directly to the next word with NO space. Do NOT drop them or split them off incorrectly.

| Attached form | Meaning | Full phrase |
|---|---|---|
| **במים** | in water | "עמיד **במים**" — NOT "עמיד מים" |
| **לריצוף** | for tiling | "דבק **לריצוף**" |
| **לצביעה** | for painting | "בסיס **לצביעה**" |

The difference between "עמיד במים" and "עמיד מים" matters for database matching.

## Abbreviation Expansion — Critical

Delivery notes abbreviate common words with a dot (`.`). ALWAYS expand the abbreviation to the full word — the certification database stores the full spelling, so a bare abbreviation fails to match.

| Abbrev | Full word | Read it as |
|---|---|---|
| **צ.** | צמר (mineral/glass wool) | `צ.זכוכית` → **צמר זכוכית** · `צ.סלעים` → **צמר סלעים** · `צ.מינרלי` → **צמר מינרלי** |
| **צ.ז.** | צמר זכוכית (glass wool) | `צ.ז. לוח שחור` → **צמר זכוכית לוח שחור** — a two-letter abbreviation: each letter starts a word |
| **ע.** | עמיד (resistant) | `ע. מים` → **עמיד במים** (with the preposition ב, per the rule above) · `ע.אש` → **עמיד אש** |

Rule: a lone Hebrew letter followed by a dot is an abbreviation — expand it to the full word, never emit the bare letter. Keep the rest of the product name (brand, model, grade) exactly as written. If unsure what the letter stands for, expand to your best reading rather than leaving the dot-letter.

## Known Israeli Building Material Brands — Sanity Check

Use these to verify your reading when a name looks unusual:

**Israeli manufacturers:**
- **תרמוקיר** — plasters and adhesives; products: PL 130, AD 700, FL 810, FL 820, WL 720
- **אורבונד** — gypsum board systems; products: לוח גבס חסין אש, לוח גבס עמיד במים
- **LYMA** — tiles and parquet flooring; products: MOTIF, PORFIDO, KB SPC (vinyl flooring)
- **כוחלה** — tile adhesives (כוחלה 119, כוחלה 120)
- **רוקבונד / ROCKBOND** — bonding agents
- **Tambour / טמבור** — paints and primers

**International brands common in Israel:**
- **SAKRET** — German mortars; products: AD 505, OC200, PR 007, TAMCRETE MC1, C2TES2
- **TAMCRETE** — concrete/mortar mix by SAKRET; products: MC1 (with lot/shade codes after)
- **KNAUF** — German gypsum; products: שפכטל, לוח גבס, KNAUF BOND
- **MAPEI** — Italian adhesives; products: MAPEFLEX, MAPECOAT, ULTRABOND
- **SIKA / SIKASIL** — Swiss chemicals; products: SIKASIL-C, SikaTop 107, SikaFlex
- **Murexin** — Austrian coatings; products: WL720/D1, KP4YB, evomineral
- **VALSIR** — Italian drainage/plumbing; products: pipe fittings with sizes (45°, 87°, 110mm)
- **NAI** — channels and profiles (מנגשי פח, ערוצי פח)
- **ABSOTEC** — waterproofing

**Israeli distributors** (these are company names, not product brands — look for the actual product name in the תיאור column):
- **מנדלסון (MENDELSON)** — distributes VALSIR, STUD anchors, TRBR threaded rod
- **אחד לבנין** (1labinyan.co.il) — distributes כוחלה, general building materials
- **LYMA** — their own tile brand

## Manufacturer / Company Identification — Critical

Some product names are registered by MORE THAN ONE manufacturer (e.g. "לוח גבס רגיל" is a real product name used by both אורבונד and טמבורד, each with its own separate certification). When the name alone can't tell them apart, the manufacturer you extract is what lets the certification lookup pick the right one — so accuracy here matters as much as the product name itself.

**Fill `manufacturer` ONLY when a maker name is clearly tied to THAT SPECIFIC product line** — for example the brand name is written directly as part of the product description ("תרמוקיר FL 810" → manufacturer `תרמוקיר`), or the line unambiguously names its maker. Use the brand list above to confirm a name really is a manufacturer.

**Leave `manufacturer` as `null` when:**
- No maker name appears on that product's own line — do NOT fall back to guessing from the invoice header/letterhead just because a company name is visible somewhere on the page.
- The visible company is a known **distributor**, not a manufacturer (מנדלסון, אחד לבנין) — a distributor's name is never the answer, even if it's the only company name on the page.
- You are not confident — a wrong manufacturer is worse than none, because it can point the lookup at the wrong company's certificate. When in doubt, leave it `null` and let a human resolve it.

## Product Code Pattern Reference

| Pattern | Example | Note |
|---|---|---|
| Letters + digits (no space) | FL810, AD700, OC200, MC1 | Keep exactly as written |
| Letters + dash + digits | PR-007, AD-505, TRBR-3/8 | Preserve the dash |
| Letters + digits + slash | WL720/D1, 3/8" | Preserve the slash and inch mark |
| Tile dimensions | 120*120, 80*180*2, 180*23*0.65 | Part of product identity |
| Tile quality grades | C2TES2, C1T, S1, A3555 HH | EU/ISO designations — keep as-is |
| Brand name + code | "SAKRET AD 505", "LYMA MOTIF 120G" | Include full two-part name |
| VALSIR sizes | 110, 45°, 3/8", 1/2" | Pipe size is part of product name |

## Real Invoice Examples

From actual delivery notes seen in the field:

**כוחלה invoice (אחד לבנין):**
- Full description: `כוחלה 119 לבן גוון 1010 שק 25 ק"ג כרמית`
- Extract as: `כוחלה 119 לבן`
- Why: "גוון 1010 כרמית" is color specification; "שק 25 ק"ג" is packaging

**SAKRET/TAMCRETE invoice:**
- Full description: `TAMCRETE MC1 672 שלדה 69-315`
- Extract as: `TAMCRETE MC1`
- Why: "672" and "69-315" are lot/shade numbers, not part of the product name

**LYMA tile invoice:**
- Full description: `MOTIF 120G 120*120 נ"ק`
- Extract as: `MOTIF 120G 120*120`
- Why: dimensions are part of the tile identity; `נ"ק` (nominal quality) is a classification tag — exclude it

**VALSIR plumbing invoice (מנדלסון):**
- Full description: `VALSIR 110 45 זית`
- Extract as: `VALSIR 110 45 זית`
- Why: 110 is pipe diameter, 45 is angle (elbow type), זית (olive/elbow) is the fitting type — all part of the product name

**C2TES2 adhesive:**
- Full description: `C2TES2 - 35 861 דבק אריחים`
- Extract as: `C2TES2 דבק אריחים` (or just `C2TES2`)
- Why: "35" and "861" are internal codes; C2TES2 is the EU adhesive grade

## Output Format

Return ONLY a valid JSON array of objects. No explanation, no markdown fences, no extra text.

[
  {"name": "כוחלה 119 לבן", "manufacturer": null},
  {"name": "תרמוקיר FL 810", "manufacturer": "תרמוקיר"},
  {"name": "MOTIF 120G 120*120", "manufacturer": null},
  {"name": "VALSIR 110 45 זית", "manufacturer": null}
]

Empty result: []

If the document is unclear in one spot, include your best reading of the name — do not skip the product. `manufacturer` may be `null` on any or all products; it is optional per line, never guessed.
