# Software engineering role pack

AF-054 installs an immutable `software-engineering@1.0.0` manifest containing exactly these provider-neutral AF-010 roles: Requirements and Backlog Steward, Solution Architect, Implementation Worker, Deterministic Test Runner, Independent Code Reviewer, Security Reviewer, Release and Integration Agent, and Policy Guardian.

Every role declares typed input, output, and evidence objects plus responsibilities, tools, permissions, positive limits, and incompatible duties. The Implementation Worker cannot also validate, independently review, secure, release, or guard the same decision. The Deterministic Test Runner and Independent Code Reviewer are distinct and mutually incompatible for one agent/decision.

`SoftwareEngineeringRolePack.authorize_release` does not accept a caller-provided approval flag. It joins the immutable candidate to its AF-053 delivery and Founder gate, requiring `delivery.status == pr_ready`, `founder.status == approved`, and the bound GitHub plan. Successful authorization is immutable and replay-safe for the release agent and candidate.
