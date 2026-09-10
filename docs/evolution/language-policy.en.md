<a id="мовна-політика-документації"></a>
# Documentation language policy


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [language-policy.md](language-policy.md). Source SHA-256 (UTF-8/LF): `7c46f0e039f87d3c5da37de980eb5bae7ceadddcee725f1209c2fd90697af1b5`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

English · [Українська](language-policy.md)

Owner decision: 2026-09-10. Revision: LP2. Translation of Ukrainian policy revision LP2. Status: the complete English portfolio has been prepared alongside the Ukrainian originals.

<a id="рішення"></a>
## Decision

Lokvetia Core and Lokiravia are developed as international products with Ukrainian as the working language and complete English documentation for external assessment. Ukrainian originals, research findings, architecture and backlogs remain in Git. The English version must allow readers to understand and assess the project without having to read Ukrainian.

This is one coordinated portfolio in two languages. Translation does not create separate requirements, dependencies, priorities or release promises. This decision does not change the existing canonical manifests or Markdown/JSON authorship rules.

<a id="публічний-шлях-читача"></a>
## Public reading path

1. An English README with a prominent link to the Ukrainian version.
2. Complete English descriptions of the vision, product problem, architecture and responsibility boundaries between the two products.
3. Consistent English implementation order, first-release scopes and acceptance criteria.
4. English detailed backlog items and research arguments needed to verify the main claims.
5. A separate English grant-application package: problem, novelty, research questions, milestones, evaluation, risks and resource justification. Adapt it to the specific call; Git does not replace a self-contained application.

Translate historical working notes when needed. A complete assessment path matters more than identical file counts in each language. The Ukrainian version remains available for day-to-day product management.

<a id="синхронність-і-якість"></a>
## Consistency and quality

- Each translation identifies its Ukrainian original and exact revision or commit/hash. A source change requires checking translation currency; an outdated translation must be visibly marked.
- IDs, dependencies, numbers, statuses, release scope, acceptance criteria and evidence limits stay identical across languages. Editorial translation does not change a requirement.
- Ukrainian remains the language for developing the concept. English text receives subject-matter and language review; it must be understandable on its own rather than reproduce unclear wording literally.
- Resolve conflicts against the Ukrainian original and the existing canonical manifest, then synchronize corrections. Do not create a separate English runtime backlog.
- `scripts/validate_translations.py` checks source hashes, document coverage, invariant IDs and links against `translations.json`. It runs in Planning CI; changing an original without synchronising its translation fails validation with a STALE diagnostic. It does not establish linguistic or subject-matter accuracy: that requires separate review.

<a id="збереження-та-межі-поточної-поставки"></a>
## Preservation and current delivery boundary

The vision, architecture, source findings,280 requirements, dependency order and first-release scopes are preserved. This delivery adds complete English counterparts to every Markdown document in `docs/evolution`, including detailed cards and research passes, plus a translation of Core's older Ukrainian GC backlog. Canonical JSON manifests and implementation statuses remain unchanged. Complete documentation translation does not mean an implemented product.

English files use the `.en.md` suffix; Ukrainian files retain their existing paths. Each English page identifies its original and exact source hash. A separate grant package will require a specific funding call; this delivery does not present one as ready. Historical notes outside the portfolio are not claimed to be fully translated. Preserve anonymous literary IDs, source anchors and coverage limits; do not publish book titles, the books themselves or private extraction caches.

[Implementation order](implementation-order.en.md) · [First releases](first-releases.en.md) · [Portfolio](README.en.md)
