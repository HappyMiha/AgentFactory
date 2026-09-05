# Provider role and model compatibility

AF-GC-042 checks configured CLI role/model pairs before saving a planning route,
before atomic backlog approval or execution-authority creation, and before each
inference invocation. Disabled inference, an absent role, an unbound model or an
invalid model argument template is denied. Errors list the configured alternatives;
a remote provider still cannot acquire local autonomous authority.

CLI profile roles, canonical model IDs and execution enablement are included in
capability snapshots. Changing the profile invalidates dependent authorization
snapshots and requires a fresh review. This configuration check does not itself
prove that a model is installed or produces a correct game plan.

Ollama explicitly permits the five autonomous planning role IDs, Environment
Bootstrap and Developer in addition to its existing roles. These are inference
roles; this change grants no tool calls, filesystem writes, package installation
or service control. Existing mission permissions and human gates still apply.
Bootstrap inference is a proposal, not execution of a bootstrap operation.
Programmatically supplied non-CLI adapters retain their separate role contract;
the absence of CLI metadata is not evidence of live role qualification.

## Regression scope

`test_provider_role_qualification` checks every shipped profile against the seven
roles, zero subprocesses for denied pairs, denial before manifest/approval writes,
authorization rechecks, and native Python fixture CLI execution. The fixture is
synthetic and is not Ollama or a real-model qualification result.

## Optional local canary

On a node with an already installed Ollama and the named model, review the exact
commit, use an isolated clean checkout, and run:

```sh
python scripts/qualify_provider_roles.py --run-live --model qwen2.5-coder:7b
```

The script neither downloads a model nor starts or exposes a service. It uses
only synthetic prompts and a temporary empty workspace. Its API requests go to
fixed loopback without proxies or redirects. Before any request, it rejects an
ambient remote/custom `OLLAMA_HOST` and pins the CLI to the same IPv4 loopback
endpoint used for API inventory and model digests. Each of seven roles has a JSON
contract check through the local API (96 output tokens, 2048 context tokens,
60-second socket timeout, 128 KiB response bound) and the configured CLI
(60-second process timeout, 16384 combined stdout/stderr characters, with the
JSON response separately limited to 1024 characters). Bounded numeric diagnostics
report retained stream lengths and stderr ANSI-sequence count, never raw prompts
or stderr. The CLI has no asserted hard
token cap. The script stops on the first failure and reports the installed model
digest and profile digest; a changed model digest invalidates the result.

The API bounds use Ollama's documented [generation options](https://docs.ollama.com/api/generate)
and [num_predict parameter](https://docs.ollama.com/modelfile). JSON shape and role
acknowledgement are contract smoke evidence only. They do not prove all five
planning artifact schemas, actual environment bootstrap, independent review,
full mission completion or product quality. Retain those separate acceptance
gates. A failure or absent live result must not be reported as qualification.
