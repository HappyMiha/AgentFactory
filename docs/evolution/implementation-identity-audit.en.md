<a id="q02-ідентичність-і-зміст-контрактів-у-чинному-core"></a>
# Q02: identity and contract semantics in the current Core


<!-- translation-metadata:start -->
<details>
<summary>Translation source and currency</summary>

Translation source: [implementation-identity-audit.md](implementation-identity-audit.md). Source SHA-256 (UTF-8/LF): `0513f44c22f10c3681cf9b16adb7037df8bfbedb51279642af68c727a9f6e811`.

Currency checks: [Core](https://github.com/HappyMiha/Lokvetia-Core/actions/workflows/planning.yml?query=branch%3Amain) · [Lokiravia](https://github.com/HappyMiha/Lokiravia/actions/workflows/planning.yml?query=branch%3Amain). English is a documentation translation; canonical requirements and evidence statuses are unchanged.

</details>
<!-- translation-metadata:end -->

Українська: [original](implementation-identity-audit.md).

2026-09-10. Static reading at Core commit `1f0f25bab16886ff5597f3a2be02eb1d44fac023`. The sections of two modules listed below were examined; their callers throughout the upper layers were not audited, and the runtime was not started. This describes the boundary of the implementation checked locally, not a claim of an end-to-end vulnerability.

| Primary source | What actually exists | What self-evolution must define |
|---|---|---|
| [roles.py](../../src/agent_factory/roles.py), lines 31–70, 93–115 | RoleDefinition has separate ID, version, tools, permissions, limits, and incompatible duties. Registering the same ID/version again with a different contract digest is rejected | Rights must not expand silently through a new interpretation of an old role/permission label; a semantic compatibility contract is needed |
| The same module, lines 118–126 | `resolve` with a version selects that specific version; without a version, it selects the latest entry | The evolution manifest and migration must carry an explicit version/digest; a convenient latest lookup does not authorize floating qualification |
| The same module, lines 184–215 | Conflicting duties are checked between assignments with the same decision_key and agent_id; role/version are explicit | This function alone does not prove that different agent IDs have independent origins or control. Alias/lineage checks must belong to the declared decision policy; we draw no conclusion about the behavior of the entire application stack |
| [memory.py](../../src/agent_factory/memory.py), lines 30–70, 105–145 | MemoryWrite contains tenant/mission/task, purpose, authority, source, validity, and invalidation; its digest covers the content and those fields | Old content/a hash is not a separate right to transfer it to another purpose, tenant, or actor. Copy/reuse must preserve provenance and enforce the current authority policy |
| The same module, lines 266–296, 299–340 | A skill draft checks for source_memory_id and records a specification digest for key/version. Review requires an allowed reviewer role, a tests version, verdict/score, representative cases, and nonempty evidence | A source-memory reference or a completed review field alone is not external evidence of semantic transferability. A new runtime/role/evaluator needs an explicit applicability decision for the relevant scope |

The existing version/digest, role assignment, and memory scope primitives are reused. The [Identity continuity contract](identity-continuity.en.md) defines additional rules and static Q02-I01–08; it does not declare those rules already implemented. Changes to Core's own source/harness/optimizer/evaluator remain immutable candidates subject to independent verification. A new name, a new process, or a copied skill grants no new authority.
