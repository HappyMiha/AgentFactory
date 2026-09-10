# Documentation language policy

English · [Українська](language-policy.md)

Owner decision:2026-09-10. Revision:LP1. Translation of the Ukrainian policy revision LP1. Status:agreed approach; the complete English portfolio has not yet been prepared.

## Decision

Lokvetia Core and Lokiravia are developed as international products with Ukrainian as the working language and complete English documentation for external assessment. Ukrainian originals, research findings, architecture and backlogs remain in Git. The English version must allow readers to understand and assess the project without having to read Ukrainian.

This is one coordinated portfolio in two languages. Translation does not create separate requirements, dependencies, priorities or release promises. This decision does not change the existing canonical manifests or Markdown/JSON authorship rules.

## Public reading path

1. An English README with a prominent link to the Ukrainian version.
2. Complete English descriptions of the vision, product problem, architecture and responsibility boundaries between the two products.
3. Consistent English implementation order, first-release scopes and acceptance criteria.
4. English detailed backlog items and research arguments needed to verify the main claims.
5. A separate English grant-application package: problem, novelty, research questions, milestones, evaluation, risks and resource justification. Adapt it to the specific call; Git does not replace a self-contained application.

Translate historical working notes when needed. A complete assessment path matters more than identical file counts in each language. The Ukrainian version remains available for day-to-day product management.

## Consistency and quality

- Each translation identifies its Ukrainian original and exact revision or commit/hash. A source change requires checking translation currency; an outdated translation must be visibly marked.
- IDs, dependencies, numbers, statuses, release scope, acceptance criteria and evidence limits stay identical across languages. Editorial translation does not change a requirement.
- Ukrainian remains the language for developing the concept. English text receives subject-matter and language review; it must be understandable on its own rather than reproduce unclear wording literally.
- Resolve conflicts against the Ukrainian original and the existing canonical manifest, then synchronize corrections. Do not create a separate English runtime backlog.
- Add automated checks for invariant fields and stale translations when implementing bilingual documentation. This policy specifies the requirement; it does not claim a working translation checker or complete translation.

## Preservation and current delivery boundary

The existing vision, architecture, source findings,280 requirements, dependency order and first-release scopes are preserved on the current documentation branch in both repositories. This delivery adds the agreed language policy in Ukrainian and English; it does not declare the entire portfolio translated or the products implemented.

The next scope is the complete English assessment path in the sequence above. Moving Ukrainian files must not break existing links. Preserve anonymous literary IDs, source anchors and coverage limits; do not publish book titles, the books themselves or private extraction caches.

[Implementation order — Ukrainian](implementation-order.md) · [First releases — Ukrainian](first-releases.md) · [Portfolio — Ukrainian](README.md)
