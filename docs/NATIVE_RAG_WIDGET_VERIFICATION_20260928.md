# Final native RAGFlow widget verification — 28 September 2026

## Verdict

Implemented locally in Chatbot-SaaS: native RAGFlow W128 search + focused queries + pinned BGE scoring + interleaving + whole-passage context. Gemini remains the normal provider; Codex was substituted only in the external test harness. Nothing was committed, pushed or deployed.

**Eight original WOWMD90 questions completed through the actual widget: six matched the saved reference’s key facts/conclusion, one returned a different supported recommendation, and one missed important conflicting evidence. No answer is claimed to match the old wording exactly. The method is implemented, but perfect retrieval or identical Gemini answers is not established.**

| Case | Exact question | Result |
|---|---|---|
| Q3 | What is MyCovital Mushroom Powder? | Matched key facts |
| Q5 | How many Turmeric Boost capsules should I take per day? | Matched key facts |
| Q8 | How do I mix the Grass-Fed Hydrolyzed Collagen Peptides powder? | Matched key facts |
| Q41 | Where can I browse your anti-aging range? | Matched key facts |
| Q57 | How are the chocolate collagen powder and Collagen Complex different in form and use? | Matched key facts |
| Q59 | Compare Turmeric Boost with Turmeric Gummies on flavor, form and daily amount. | Incomplete evidence |
| Q65 | Can you suggest options for digestive wellness? | Supported alternative |
| Q84 | Can Collagen Complex cure arthritis? | Matched key conclusion |

## Test setup and evidence

- Selection was frozen before fresh retrieval. Cases cover identity, dosage conflict, mixing, collection navigation, product comparisons, recommendations and an unsupported disease claim.
- The complete unchanged WOWMD index was available: 23 documents / 413 native chunks. All native searches used the bot-owned full corpus, not a preselected answer document.
- The real frontend/public/widget.js, SaaS session authentication, public SSE routes, persistence and quota functions ran locally. Each question was entered through the widget UI; delivered text and source links were visually/accessibility checked. All eight saved database answers equal the server outputs exactly.
- Actual native RAGFlow search/TEI embeddings ran on unchanged Railway stock-dev. The production addon core was executed in memory over a guarded read-only SSH transport because deploying an addon was not authorized. The private addon HTTP server was not deployed or tested as a Linux service.
- Actual pinned BGE GPU inference ran locally. No score replay was used in these eight fresh widget answers.
- Codex supplied focused queries based on the question and wrote each answer after reading its actual final context. The saved reference was not injected into the answer prompt. No missing facts were patched into context; Q59 retains the miss.
- Local PostgreSQL was represented by isolated SQLite. Redis used the existing development fallback because a local server was unavailable. This does not establish full production DB/Redis behavior.
- 21 successful native calls have source-hash, dataset-fingerprint and before/after provider telemetry evidence: zero new Gemini events; gateway event count stayed 3. Calls include the Q3 retry and the successful part of the first Q84 attempt.
- Eight successful messages were persisted and charged once each. One abandoned failed Q84 request retained an unconsumed reservation pending the existing expiry/cleanup; it was not charged. Normal native-error quota release and same-turn retry are covered by the final HTTP tests.
- Test latency includes repeated SSH/runtime startup and waiting for manual Codex answers. It is not a production speed benchmark.

Integrity records:

- Frozen selection SHA-256: `63b736d628a4290cffb3ca15129fa150f3042e28c1dd869fc13f7023f6cc04cc`.
- Baseline file SHA-256: `012fdd323c74e75efbe74dc6be804985f0d820a7e1986b94e3ad84a3c9b9cc3a`.
- Native index fingerprint: `8f422318ec69cbd6b8cea7943e6d2695c62dec08163bc13f5c95582c4c54cc59`.
- Native upstream: `a024bea0cd93f39e6652a42bf84dd20c55bc560b`; six pinned search-source hashes verified.
- BGE revision: `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

## What differed and why

**Q59 is a ranking/context failure, not unavailable website data.** The missing Boost Suggested Use passage `d5a4acd35027977b` was native rank 20 for the original question and rank 12 for the Boost focus query. It was therefore inside that focus lane’s 32 scored candidates, but did not make the final 4,000-token prefix. The final answer saw only the one-capsule-daily instructions. It was not given the known conflicting fact from Q5.

**Q65 is an acceptable alternate answer, not exact parity.** The Good Gut reference passage was native rank 6 for the original query and 10 for the focus query, but was not selected. Several collection FAQs/reviews occupied context. The selected Greens and Boost passages still supported two suitable catalog options for the open-ended question.

**Context precision remains imperfect.** Q5/Q8 included extra sources, and Q84 included menus, reviews and blocked-page boilerplate alongside the correct disclaimer. Source footer links represent supplied context and can include a page unused by the answer. The source-preview feature remains absent; ordinary source links remain.

No question-specific rule, extra keyword boost, source rewrite or larger context window was added to hide these misses. A future general improvement should test conflict-sensitive evidence coverage and source diversity against held-out queries, then compare against this unchanged baseline. Source-conflict editing remains deferred as requested.

## Failures preserved during this run

- Q3 first failed in the external test recorder: serializing a dataclass with tuple dictionary keys failed after answer generation. The recorder was corrected to use the application trace serializer. The widget retry produced an identical context and delivered the answer; both attempts are retained. This was test instrumentation, not a native-search failure.
- Q84 first failed because the SSH transport returned no safe payload during a focused search. The application produced a temporary-service result; no Codex answer was generated. A fresh widget retry with the same question/plan completed. The underlying transport cause was not conclusively identified.
- Final review found that returning a temporary-service sentence could otherwise be treated as billable success by the existing public routes. The new native adapter now raises the platform’s existing typed service exception. HTTP tests verify retryable SSE errors, nonstream 503 responses, quota release and one charge after a successful retry. This changes error classification, not the ranking or platform quota design.

## Verification summary

- 73 targeted backend tests collected: 72 passed; one opt-in disposable PostgreSQL test skipped. This includes native scope/integrity, atomic ingestion/recrawl, parse failure, clone isolation, cleanup, SQLite migration execution, public SSE/session/history/error/quota behavior, readiness and frozen replay.
- Frozen ranking/context replay matches all 65 stored cases. Existing answerable-evidence coverage remains WOWMD 9/9 + 9/9 and IKEA 43/45. The two IKEA misses remain; no new IKEA100 or full WOWMD90 run is claimed.
- BGE service boundary tests: 14 passed, one optional explicit local-model test skipped. Real GPU scoring was separately exercised by the live widget run.
- Widget regression script: 34 checks passed. Static Compose YAML, Python syntax and upstream Git-blob checks passed.
- Deployment code keeps the existing configured Gemini router and credentials. The harness alone substituted Codex; no Codex callback or answer files are shipped.
- Still unverified: Linux image build/Compose boot, deployed native-addon HTTP auth, real PostgreSQL/Redis stack, real Gemini query planning/answers, CPU sizing and concurrent performance. Existing knowledge must be adopted/reindexed into native bindings before cutover.

## Exact answer comparison

The old answer and reference below are saved test artifacts, not newly endorsed medical guidance. The reference is the previously reviewed answer; evaluation compares supported meaning, not exact wording.

### Q3 — What is MyCovital Mushroom Powder?

**Result: Matched key facts.** Correct product identity, four mushrooms and supported wellness purpose.

New widget answer:

> [MyCovital Mushroom Powder](https://www.wowmd.com/products/mycovital-mushroom-powder) is a powdered supplement combining Lion’s Mane, Reishi, Chaga and Cordyceps mushrooms with adaptogenic herbs. It is designed to support cognitive wellness, everyday balance and normal immune function as part of a daily wellness routine.

Saved reviewed reference:

> MyCovital Mushroom Powder is WOWMD’s mushroom-based powdered supplement containing Lion’s Mane, Reishi, Chaga and Cordyceps, alongside adaptogenic herbs. It is formulated to support cognitive wellness, everyday balance and normal immune function [ID:0] [ID:1].

Original saved widget answer:

> WOWMD® MyCovital Mushroom Powder is a simple, clean powder supplement designed to support your daily wellness routine [ID:3][ID:7]. It is formulated with organic mushroom extracts and adaptogens to support cognitive wellness, immune system wellness, daily balance, stress-response resilience, steady-feeling energy, and overall vitality [ID:4][ID:6][ID:8][ID:11]. 
> 
> The formula features a blend of mushroom ingredients including:
> - **Lion's Mane**: Included to support mental clarity, focus, and cognitive wellness [ID:2][ID:7][ID:21].
> - **Reishi**: Commonly used to support calmness, daily balance, resilience, and normal immune function [ID:2][ID:7][ID:21].
> - **Chaga**: Contains naturally occurring antioxidant compounds to support everyday wellness, immune function, steady-feeling energy, and stress-response balance [ID:2][ID:7][ID:11][ID:21].
> - **Cordyceps**: Included to support daily energy, physical wellness routines, active lifestyles, and stress-response balance [ID:2][ID:7][ID:8][ID:11][ID:21].
> 
> **Key Product Details:**
> - **Serving and Taste:** The recommended usage is to mix 1 scoop (1.96 g) daily into water, juice, smoothies, or your favorite beverage [ID:7]. It dissolves easily and has a mild, earthy taste [ID:7].
> - **Attributes:** It is vegan-friendly, gluten-free (implied by vegan/plant formulas, though check specific product details), non-GMO, and contains no artificial colors, flavors, or preservatives [ID:11][ID:14][ID:15]. 
> - **Quality & Testing:** The ingredients undergo comprehensive laboratory testing to ensure purity, potency, and safety [ID:4].

Final native passage IDs: `b0e9fab2fb08a65b`, `f9492dd6e5d64bb2`, `b380cb2efcf0d95b`, `62f88ef08eab69bc`, `167139a1c4cbfe5a`, `48a1056f5d5d5306`, `4f6ea7f9b0678b76`, `59ee5f7685352812`.

### Q5 — How many Turmeric Boost capsules should I take per day?

**Result: Matched key facts.** Both conflicting capsule directions were present and disclosed. The final context/footer also included an unnecessary Joint Supplements source.

New widget answer:

> The [Turmeric Boost page](https://www.wowmd.com/products/turmeric-boost) gives conflicting directions: the FAQ says **1 veggie capsule daily, preferably with a meal**, while the separate Suggested Use section says **1 capsule twice daily**, ideally 20–30 minutes before a meal. Both allow directions from your healthcare professional. I can’t confirm which instruction is current; check your bottle’s label and confirm the discrepancy with WOWMD or your healthcare professional before choosing a dose.

Saved reviewed reference:

> The Turmeric Boost page gives conflicting directions:
> 
> - The FAQ says **1 veggie capsule daily, preferably with a meal**, or as directed by your healthcare professional [ID:0].
> - The separate Suggested Use section says **1 capsule twice daily**; for best results, 20–30 minutes before a meal, or as directed by your healthcare professional [ID:1].
> 
> The information does not establish which direction is current. Check your bottle’s label and confirm the discrepancy with the manufacturer or your healthcare professional before choosing a dose.

Original saved widget answer:

> You should take 1 veggie capsule of WOWMD® Turmeric Boost daily, preferably with a meal, or as directed by your healthcare professional [ID:1].

Final native passage IDs: `ae8776e694e24c03`, `71351a328f0306d9`, `0374f576cd449843`, `d5a4acd35027977b`, `56750b4f56ac5c73`, `0eafc2491459bbc0`, `d294025e67e9d6a0`.

### Q8 — How do I mix the Grass-Fed Hydrolyzed Collagen Peptides powder?

**Result: Matched key facts.** Correct product mixing instructions and the one-versus-two scoop conflict were present and disclosed. Chocolate-product passages/links also occupied context unnecessarily.

New widget answer:

> The [Grass-Fed Hydrolyzed Collagen Peptides page](https://www.wowmd.com/products/grass-fed-hydrolyzed-collagen-peptides) says to mix **1 level scoop into 8–10 oz of chilled water or your preferred beverage**, using a shaker cup or blender; its step-by-step directions say to shake for about **5 seconds**. However, another section on that same page says **2 scoops**, so the serving instructions conflict. Check your container’s label and confirm the correct scoop amount with WOWMD before use.

Saved reviewed reference:

> The page disagrees about the amount:
> 
> - Its detailed instructions say **1 level scoop in 8–10 oz of chilled water or another beverage**, shaken for about 5 seconds. The separate Suggested Use section also says **1 scoop in 8–10 oz**, using a shaker cup or blender [ID:0] [ID:1].
> - Its main “How to use & taste” section instead says **2 scoops in 8–10 oz**, taken daily [ID:2].
> 
> The supplied information does not resolve the one-scoop versus two-scoop conflict. Confirm the current directions on your bottle with the manufacturer before choosing an amount.

Original saved widget answer:

> To mix WOWMD® Grass-Fed Hydrolyzed Collagen Peptides, take one level scoop of the powder and add it to 8-10 oz (236-295 ml) of chilled water or your preferred beverage [ID:3]. Shake or stir for about 5 seconds [ID:3][ID:20]. Alternatively, you can easily add the powder to shakes, smoothies, or water for an effortless daily supplement [ID:3].

Final native passage IDs: `8c5d9a5024ce4aa6`, `a849a0432cf37795`, `71225df4a3098fd3`, `c975fd17b4a97cce`, `b23b5e3618c2378e`, `e00740d9391b8359`, `91c0ea0f372f1607`, `64a171f8f5c2ede3`.

### Q41 — Where can I browse your anti-aging range?

**Result: Matched key facts.** The correct anti-aging collection URL was supplied and rendered as a link.

New widget answer:

> You can browse our [Anti-Aging Supplements collection](https://www.wowmd.com/collections/anti-aging), which brings together collagen-supporting formulas and antioxidant blends for healthy-aging wellness.

Saved reviewed reference:

> Browse our [Anti-Aging Supplements collection](https://www.wowmd.com/collections/anti-aging), which includes collagen-supporting formulas and antioxidant blends for skin wellness and vitality [ID:0] [ID:1].

Original saved widget answer:

> You can browse the anti-aging supplements collection online [ID: 0], which features 7 products [ID: 0]. You can explore the anti-aging range to find the right formula that fits your goals [ID: 0].

Final native passage IDs: `a522fbdca5240bc8`, `23a387731a3c88f3`, `f975d9175736df59`, `36b015594fe640ca`, `723c4c889d5e344d`, `6eaa5b136140ca80`, `7b8233d6bac5f6c6`, `3e31157c3eb3d674`.

### Q57 — How are the chocolate collagen powder and Collagen Complex different in form and use?

**Result: Matched key facts.** Correct powder/capsule distinction and serving directions; no invented capsules-per-serving value.

New widget answer:

> - [Chocolate Collagen Powder](https://www.wowmd.com/products/grass-fed-collagen-peptides-powder-chocolate) is a chocolate-flavored powder: mix 2 scoops with 8–10 oz of water, milk or another beverage and take daily. It can go into hot or cold drinks.
> - [Collagen Complex](https://www.wowmd.com/products/collagen-complex) comes in capsules: adults take 1–2 servings daily, or as directed by their healthcare professional. Follow the current label for the number of capsules per serving.

Saved reviewed reference:

> - **Chocolate collagen powder:** Mix **2 scoops in 8–10 oz of water or another beverage** daily. It is chocolate-flavored and can be added to hot or cold drinks [ID:0] [ID:2].
> - **Collagen Complex:** A **capsule supplement**. Adults take **1–2 servings daily**, or as directed by a healthcare professional, following the current product label [ID:1] [ID:6].
> 
> The quoted Collagen Complex directions do not specify how many capsules make up one serving, so check the bottle for that detail.

Original saved widget answer:

> WOWMD® Grass-Fed Collagen Peptides Powder (Chocolate) is a chocolate-flavored powder that requires mixing 2 scoops into 8-10 oz of water, milk, coffee, or a smoothie [ID:0]. In contrast, Collagen Complex is provided as a daily capsule formula where adults take 1 to 2 servings per day or as directed by a healthcare professional [ID:1][ID:0].

Final native passage IDs: `a849a0432cf37795`, `38c63fbbbda4b89b`, `71225df4a3098fd3`, `5173636c28e01836`, `91c0ea0f372f1607`, `d235afc205bff4ae`, `e00740d9391b8359`, `ae60b9152aafe06d`.

### Q59 — Compare Turmeric Boost with Turmeric Gummies on flavor, form and daily amount.

**Result: Incomplete evidence.** Flavor/form and main servings were correct, but the conflicting twice-daily Boost direction was absent from final context. The answer therefore did not disclose it.

New widget answer:

> - [Turmeric Boost](https://www.wowmd.com/products/turmeric-boost): veggie capsules; no specific flavor is stated. Its main directions say 1 capsule daily, preferably with a meal, or as directed by your healthcare professional.
> - [Turmeric Gummies](https://www.wowmd.com/products/turmeric-gummies): turmeric-ginger flavored gummies; take 2 gummies daily, preferably after meals, or as directed by your healthcare professional.
> Follow the current product label for serving instructions.

Saved reviewed reference:

> - **Turmeric Gummies:** Gummies with a **turmeric-ginger flavor**. The directions say **2 gummies daily, preferably after meals**, or as directed by a healthcare professional [ID:0].
> - **Turmeric Boost:** A **veggie capsule**; the quoted use instructions do not name a flavor [ID:1]. Its directions conflict: the main instructions and FAQ say **1 capsule daily, preferably with a meal**, while Suggested Use says **1 capsule twice daily**, with 20–30 minutes before a meal recommended for best results. Both allow healthcare-professional directions [ID:1] [ID:2] [ID:3].
> 
> Confirm the conflicting Boost directions against your bottle with the manufacturer or your healthcare professional before choosing a dose.

Original saved widget answer:

> Based on the provided evidence, here is a comparison of Turmeric Boost and Turmeric Gummies:
> 
> - **Flavor:** Turmeric Gummies feature a turmeric-ginger flavor [ID:2]. The flavor of Turmeric Boost is not specified in the evidence.
> - **Form:** Turmeric Boost comes in veggie capsules [ID:0], whereas Turmeric Gummies come in a gummy format [ID:2].
> - **Daily Amount:** The suggested serving for Turmeric Boost is 1 veggie capsule daily [ID:0]. The recommended serving for Turmeric Gummies is two gummies daily [ID:5].

Final native passage IDs: `71351a328f0306d9`, `a42372ee88431a79`, `ae8776e694e24c03`, `828e9d7b49280913`, `0374f576cd449843`, `d6972730b5379fdc`, `0eafc2491459bbc0`, `3aae27e1fa262d96`.

### Q65 — Can you suggest options for digestive wellness?

**Result: Supported alternative.** The answer offered Greens Blend and Turmeric Boost with grounded reasons and the collection link. The saved reference offered Good Gut Great Life and Greens Blend. Valid for this open-ended question, but not the same recommendation or evidence.

New widget answer:

> Two options are [Greens Blend](https://www.wowmd.com/products/greens-blend), which includes spirulina, wheatgrass and chlorella for digestive wellness and everyday nutrition, and [Turmeric Boost](https://www.wowmd.com/products/turmeric-boost), whose ginger extract supports normal digestive function. You can also browse our [Digestion Supplements collection](https://www.wowmd.com/collections/digestion-supplements) to compare options.

Saved reviewed reference:

> Two options to consider are:
> 
> - [Good Gut Great Life](https://www.wowmd.com/products/good-gut-great-life), described as supporting daily digestive wellness and gut microbiome balance [ID:0].
> - [Greens Blend](https://www.wowmd.com/products/greens-blend), which includes supergreens such as wheatgrass, spirulina and chlorella for digestive wellness and everyday nutritional support [ID:1].
> 
> You can also browse the [Digestion Supplements collection](https://www.wowmd.com/collections/digestion-supplements) [ID:3].

Original saved widget answer:

> WOWMD offers a variety of digestive health and wellness options designed to support gut comfort, regularity, and microbiome balance [ID:0][ID:5]. Here are some product options and categories you can explore:
> 
> * **Digestion and Gut Health Supplements:** WOWMD offers targeted solutions such as **Good Gut Great Life**, which supports daily digestive wellness and gut microbiome balance [ID:5], and **Greens Blend**, a formula featuring organic greens, prebiotics, and probiotics (including a Bacillus probiotic and inulin) to support digestive wellness and microbial balance [ID:9][ID:12]. 
> * **Turmeric and Botanical Blends:** **Turmeric Boost** and **Turmeric Gummies** are formulated with ingredients like organic turmeric and ginger extract to support normal digestive function and everyday digestive wellness as part of a balanced routine [ID:14][ID:27][ID:63].
> * **Digestive Supplements & Quiz Tools:** You can explore specific supplement collections for gut health, probiotics, and colon support [ID:15][ID:48], or take the online **Digestion Quiz** provided by WOWMD to help find a personalized path to a healthier gut [ID:45]. 
> 
> *Note: Individual results may vary [ID:45], and it is always a good idea to consult a healthcare professional before starting any new supplement regimen.*

Final native passage IDs: `34d9e91799218a1a`, `2d956e6a41b9697f`, `8d76361cb8c0226d`, `81dbbd9286688297`, `56f7d94f2dfe70f4`, `5603b9ff546fba6d`, `8d7434435dd2fd9a`, `3f399120633e90c2`.

### Q84 — Can Collagen Complex cure arthritis?

**Result: Matched key conclusion.** The explicit product disease disclaimer was retrieved; the answer did not claim an arthritis cure. It did not reproduce every optional detail in the saved reference.

New widget answer:

> No. [Collagen Complex](https://www.wowmd.com/products/collagen-complex) supports everyday joint comfort and mobility, but its product disclaimer says it is not intended to diagnose, treat, cure or prevent disease. If you have arthritis, consult your healthcare professional before using it.

Saved reviewed reference:

> The supplied information does **not establish that Collagen Complex cures arthritis**. Its FAQ describes everyday joint comfort and mobility support, with no specific result or timeframe guaranteed [ID:1]. The broader Joint Supplements page also says those products are not intended to diagnose, treat, cure or prevent disease [ID:3].
> 
> For persistent or worsening joint pain, the Collagen Complex FAQ advises consulting a healthcare professional [ID:1].

Original saved widget answer:

> The content on this video is not intended to diagnose, treat, cure, or prevent any disease or medical condition [ID:0].

Final native passage IDs: `6405bafb4c4d3ded`, `5173636c28e01836`, `6145b1a1bd7c6540`, `7ff25c9d08e77dc0`, `ae60b9152aafe06d`, `7d876f6d3f33c5c6`, `67ece173ce04dba0`, `cd84dc5a5f9caf87`.

## Files and deployment handoff

Implementation/configuration: [COMBINED_RAG_INTEGRATION.md](COMBINED_RAG_INTEGRATION.md). Native service and migration instructions: [deploy/native-ragflow/README.md](../deploy/native-ragflow/README.md).

Raw manifests, prompts, focus plans, native searches, failed attempts, server outputs and the isolated test database are retained outside the repository at `C:\Users\ADMIN\Documents\CodexArchives\rag-native-final-20260928`. These are private test artifacts, not deployment dependencies.

No remote dataset, provider setting, database row, service deployment or Git history was changed by this fresh widget run. Local test services are stopped after verification.
