# Independent evaluation

`EvaluationService` is the AF-020 evidence-first review boundary for a validated candidate change.

Before a reviewer function can run, the service reconstructs all five AF-052 validator results for the exact task, attempt, and candidate digest; verifies their immutable snapshot; requires every result to have succeeded; and requires primary mapped evidence for every declared acceptance criterion. The reviewer model identity must differ from the model stored on the AF-049 producer result.

The reviewer returns exactly one `pass` or `fail` entry per criterion with confidence, concerns, and dissent. Agent Factory supplies the authoritative evidence rather than accepting evidence references from the model. The rubric ID/version, producer and reviewer identities, evidence digest, summary, and criterion verdicts are immutable. Any failed criterion rejects the evaluation, while replay of the same candidate and rubric version returns the stored result without another model call.
