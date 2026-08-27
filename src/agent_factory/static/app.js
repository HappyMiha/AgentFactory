const state = { lastSuccess: null, timer: null, selectedTask: null, projectsLoaded: false, settingsLoaded: false, refreshSeconds: 5, auditPageSize: 50, founderPackets: [], selectedGate: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);

function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }
function badge(status) { const value = String(status || "unknown"); return `<span class="badge status-${escapeHtml(value)}">${escapeHtml(value.replaceAll("_", " "))}</span>`; }
function metric(label, value, tone) { return `<article class="metric tone-${tone}"><span>${escapeHtml(label)}</span><strong>${value}</strong><i aria-hidden="true"></i></article>`; }

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { headers: { Accept: "application/json", ...(options.headers || {}) }, ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function renderDashboard(data) {
  const c = data.counts;
  $("metrics").innerHTML = [
    metric("Ready", c.ready, "mint"), metric("Active", c.active, "blue"), metric("Blocked", c.blocked, "amber"),
    metric("Failed", c.failed, "red"), metric("Awaiting review", c.awaiting_review, "violet"), metric("Awaiting approval", c.awaiting_approval, "cyan")
  ].join("");
  $("run-list").innerHTML = data.runs.length ? data.runs.map((run) => `<button class="list-row row-button" type="button" data-run-id="${run.id}"><span><strong>${escapeHtml(run.workflow_id)}</strong><small>Run #${run.id} &middot; Task #${run.task_id}${run.temporal_workflow_id ? ` &middot; ${escapeHtml(run.temporal_workflow_id)}` : ""}</small></span>${badge(run.status)}</button>`).join("") : empty("No workflow runs yet");
  $("approval-list").innerHTML = data.pending_approvals.length ? data.pending_approvals.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.kind)} approval</strong><small>${escapeHtml(item.target_type)} #${item.target_id}</small></span>${badge(item.status)}</div>`).join("") : empty("No decisions are waiting");
  $("provider-list").innerHTML = data.providers.length ? data.providers.map((item) => `<article class="provider"><span class="health health-${escapeHtml(item.status)}" aria-hidden="true"></span><span><strong>${escapeHtml(item.id)}</strong><small>${escapeHtml(item.type)} &middot; ${escapeHtml(item.status)}${item.version ? ` &middot; ${escapeHtml(item.version)}` : ""}</small><small>${escapeHtml(item.path || item.error || "No executable detail")}</small><small>Execution ${item.execution_enabled ? "enabled" : "disabled"} &middot; Roles: ${escapeHtml(item.allowed_roles.join(", ") || "simulation only")}</small><details><summary>Redacted health detail</summary><pre>${escapeHtml(JSON.stringify(item.health_details, null, 2))}</pre></details></span></article>`).join("") : empty("No providers configured");
  $("failure-list").innerHTML = data.recent_failures.length ? data.recent_failures.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.event_type)}</strong><small>${escapeHtml(item.entity_type)} #${escapeHtml(item.entity_id)}</small></span><time>${escapeHtml(item.created_at)}</time></div>`).join("") : empty("No recent failures");
}

function renderExecutions(data) {
  const rows = [
    ...data.runs.map((item) => `<article class="execution-row"><span><strong>Run #${item.id}</strong><small>Task #${item.task_id} · ${escapeHtml(item.workflow_id)} · ${escapeHtml(item.status)}</small></span><button class="danger" data-execution-action="cancel-run" data-id="${item.id}">Cancel run</button></article>`),
    ...data.sessions.map((item) => `<article class="execution-row"><span><strong>Session #${item.id}</strong><small>Assignment #${item.assignment_id} · ${escapeHtml(item.runtime)} · ${escapeHtml(item.status)}</small></span><button class="danger" data-execution-action="stop-session" data-id="${item.id}">Stop session</button></article>`),
    ...data.leases.map((item) => `<article class="execution-row"><span><strong>Lease #${item.lease_id}</strong><small>Task #${item.task_id} · ${escapeHtml(item.agent_id)} · expires ${escapeHtml(item.expires_at)}</small></span><button class="danger" data-execution-action="release-lease" data-assignment="${item.assignment_id}" data-fence="${item.fencing_token}">Release lease</button>`),
  ];
  $("execution-summary").textContent = `${rows.length} active control-plane item(s)`;
  $("execution-list").classList.remove("loading-block");
  $("execution-list").innerHTML = rows.length ? rows.join("") : empty("No active executions, sessions, or leases");
}

function renderMonitor(data) {
  const ready = data.status === "ready";
  const summary = $("monitor-summary");
  summary.classList.remove("loading-block");
  summary.innerHTML = `<span class="monitor-state ${ready ? "ready" : "degraded"}">${ready ? "READY" : "DEGRADED"}</span><strong>${ready ? "System is ready for work" : "Resolve readiness blockers before starting"}</strong>`;
  $("monitor-checked").textContent = `Checked ${new Date(data.checked_at).toLocaleTimeString()}`;
  const checks = [
    ["Database", data.database.ok ? "OK" : "Failed", data.database.ok ? "ready" : "degraded"],
    ["Migrations", `${data.migrations.current}/${data.migrations.latest}`, data.migrations.current === data.migrations.latest ? "ready" : "degraded"],
    ["Providers", `${data.providers.ready}/${data.providers.total} ready`, data.providers.ready === data.providers.total ? "ready" : "degraded"],
    ["Agents", `${data.agents.enabled}/${data.agents.total} enabled`, data.agents.enabled > 0 ? "ready" : "degraded"],
    ["Emergency stop", data.safety.emergency_stop ? "ACTIVE" : "Clear", data.safety.emergency_stop ? "degraded" : "ready"],
    ["Runtime", `${data.runtime.active_sessions} sessions · ${data.runtime.queued_tasks} queued`, "info"],
  ];
  $("monitor-checks").innerHTML = checks.map(([label, value, status]) => `<article class="monitor-card ${status}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  $("monitor-blockers").innerHTML = data.blockers.length ? `<strong>Blockers</strong><ul>${data.blockers.map((item) => `<li>${escapeHtml(item.replaceAll("_", " "))}</li>`).join("")}</ul>` : `<span>No blockers detected. The local control plane can accept work.</span>`;
}

function renderRuntime(agents, providers, reviews) {
  $("agent-list").classList.remove("loading-block");
  $("routing-list").classList.remove("loading-block");
  $("agent-list").innerHTML = agents.length ? agents.map((agent) => {
    const compatible = providers.filter((provider) => provider.enabled && (provider.id === "deterministic" || provider.allowed_roles.includes(agent.role)));
    const options = compatible.map((provider) => `<option value="${escapeHtml(provider.id)}" ${provider.id === agent.provider ? "selected" : ""}>${escapeHtml(provider.id)} (${escapeHtml(provider.status)})</option>`).join("");
    return `<article class="agent-card" data-agent-id="${escapeHtml(agent.id)}"><div class="agent-title"><span><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.id)} &middot; ${escapeHtml(agent.role)}</small></span>${badge(agent.enabled ? "enabled" : "disabled")}</div><dl class="agent-facts"><div><dt>Provider / model</dt><dd>${escapeHtml(agent.provider)} / ${escapeHtml(agent.model)}</dd></div><div><dt>Recent work</dt><dd>${agent.last_claimed_task_id ? `Task #${agent.last_claimed_task_id}` : "No claim"}</dd></div><div><dt>Reviewer use</dt><dd>${agent.reviewer_assignment_count}${agent.last_reviewed_run_id ? ` (last run #${agent.last_reviewed_run_id})` : ""}</dd></div><div><dt>Permissions</dt><dd>${escapeHtml(agent.permissions.join(", "))}</dd></div></dl><div class="agent-controls"><button type="button" data-agent-toggle="${agent.enabled ? "false" : "true"}" class="${agent.enabled ? "danger" : ""}">${agent.enabled ? "Disable" : "Enable"}</button><label>Compatible provider<select class="agent-provider">${options}</select></label><label>Model identity<input class="agent-model" value="${escapeHtml(agent.model)}"></label><button type="button" data-agent-provider>Replace provider</button></div></article>`;
  }).join("") : empty("No agents configured");
  $("routing-list").innerHTML = reviews.length ? [...reviews].reverse().map((review) => {
    const producerModels = review.producer_agents.map((producer) => producer.model || producer.model_identity || producer.provider || "unknown");
    const independent = !producerModels.some((model) => String(model).toLowerCase() === review.reviewer_model.toLowerCase());
    const excluded = Object.entries(review.excluded_candidates).map(([id, reason]) => `<li><strong>${escapeHtml(id)}</strong>: ${escapeHtml(reason)}</li>`).join("");
    return `<article class="routing-card"><div class="stage-head"><h3>${escapeHtml(review.stage)} &middot; run #${review.run_id}</h3>${badge(independent ? "independent" : "conflict")}</div><p>Selected <strong>${escapeHtml(review.reviewer_agent_id)}</strong> via ${escapeHtml(review.reviewer_provider)} / ${escapeHtml(review.reviewer_model)}</p><p>Producer models: ${escapeHtml(producerModels.join(", ") || "none recorded")}</p><p>Strategy: ${escapeHtml(review.strategy)} &middot; verdict: ${escapeHtml(review.verdict || "pending")}</p><details><summary>Candidate exclusions</summary>${excluded ? `<ul>${excluded}</ul>` : `<p>No candidates were excluded.</p>`}</details></article>`;
  }).join("") : empty("No reviewer assignments yet. Run a simulation to create routing evidence.");
}

function renderFounderInbox(packets) {
  state.founderPackets = packets;
  $("approval-list").innerHTML = packets.length ? packets.map((packet) => `<button class="list-row row-button" type="button" data-founder-gate="${packet.approval.id}"><span><strong>${escapeHtml(packet.work_item.title)}</strong><small>Run #${packet.run.id} · ${packet.artifacts.length} artifacts · ${packet.reviews.length} independent reviews</small></span><span class="row-meta">${packet.unresolved_findings.length ? `<span class="finding-count">${packet.unresolved_findings.length} finding(s)</span>` : ""}${badge(packet.approval.status)}</span></button>`).join("") : empty("No Founder decisions are waiting");
}

function openFounderDecision(gateId) {
  const packet = state.founderPackets.find((item) => item.approval.id === Number(gateId));
  if (!packet) return;
  state.selectedGate = packet.approval.id;
  $("founder-title").textContent = `Founder decision · ${packet.work_item.title}`;
  const artifactCards = packet.artifacts.map((artifact) => {
    const document = parseArtifact(artifact.content);
    return `<article class="decision-artifact"><div class="stage-head"><h4>${escapeHtml(artifact.stage)}</h4>${badge(artifact.status)}</div><p>${escapeHtml(artifact.agent_id)} via ${escapeHtml(artifact.provider)}</p><p>${escapeHtml(document.summary || document.output || "Structured evidence available in run detail")}</p></article>`;
  }).join("");
  const reviews = packet.reviews.map((review) => `<article class="decision-review"><div class="stage-head"><strong>${escapeHtml(review.reviewer_agent_id)}</strong>${badge(review.verdict || "missing")}</div><small>${escapeHtml(review.reviewer_provider)} / ${escapeHtml(review.reviewer_model)} · ${escapeHtml(review.strategy)}</small><p>Reviewed producer(s): ${escapeHtml(review.producer_agents.map((producer) => `${producer.agent_id} / ${producer.model}`).join(", "))}</p></article>`).join("");
  const criteria = packet.work_item.acceptance_criteria.map((criterion) => `<li><strong>${escapeHtml(criterion)}</strong>${(packet.criterion_evidence[criterion] || []).length ? `<ul>${packet.criterion_evidence[criterion].map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<span>No direct criterion evidence recorded</span>`}</li>`).join("");
  const findings = packet.unresolved_findings.map((finding) => `<li>${escapeHtml(finding)}</li>`).join("");
  $("founder-detail").innerHTML = `<div class="authority-banner">Automated verdicts cannot make this decision. Only this separately confirmed Founder action changes the final workflow state.</div><dl class="facts"><div><dt>Work item</dt><dd>#${packet.work_item.id} · ${escapeHtml(packet.work_item.kind)}</dd></div><div><dt>Run</dt><dd>#${packet.run.id} · ${escapeHtml(packet.run.workflow_id)}</dd></div></dl><section class="decision-section"><h3>Acceptance criteria &amp; evidence</h3><ol class="criteria-list">${criteria || "<li>No work-item criteria recorded</li>"}</ol></section><section class="decision-section"><h3>Implementation &amp; validation artifacts</h3><div class="decision-grid">${artifactCards || empty("No artifacts")}</div></section><section class="decision-section"><h3>Independent reviewer verdicts</h3>${reviews || empty("No reviewer decisions")}</section><section class="decision-section findings"><h3>Unresolved findings</h3>${findings ? `<ul>${findings}</ul>` : `<p>No unresolved findings were derived from the recorded evidence.</p>`}</section>`;
  $("founder-note").value = "";
  $("founder-dialog").showModal();
}

function auditQuery() {
  const form = new FormData($("audit-filters"));
  const query = new URLSearchParams({ limit: String(state.auditPageSize) });
  for (const [key, value] of form.entries()) if (String(value).trim()) query.set(key, String(value).trim());
  return query.toString();
}

async function loadAudit() {
  const data = await fetchJson(`/api/events?${auditQuery()}`);
  $("audit-count").textContent = `${data.total} correlated event${data.total === 1 ? "" : "s"}; showing up to ${data.limit}`;
  $("audit-list").classList.remove("loading-block");
  $("audit-list").innerHTML = data.items.length ? data.items.map((event) => {
    const context = [event.project_id && `Project #${event.project_id}`, event.task_id && `Task #${event.task_id}`, event.run_id && `Run #${event.run_id}`, event.agent_id, event.provider].filter(Boolean).join(" · ");
    const artifactLink = event.related_artifact_ids.length ? `<a href="/api/artifacts?${event.run_id ? `run_id=${event.run_id}` : `task_id=${event.task_id}`}">Artifacts ${event.related_artifact_ids.map((id) => `#${id}`).join(", ")}</a>` : "";
    return `<article class="audit-row"><div><div class="stage-head"><strong>${escapeHtml(event.event_type)}</strong>${badge(event.outcome)}</div><small>${escapeHtml(event.entity_type)} #${escapeHtml(event.entity_id)}${context ? ` · ${escapeHtml(context)}` : ""}</small><div class="audit-links">${event.run_id ? `<button type="button" class="text-button" data-run-id="${event.run_id}">Inspect run</button>` : ""}${artifactLink}</div><details><summary>Event payload</summary><pre>${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre></details></div><time>${escapeHtml(event.created_at)}</time></article>`;
  }).join("") : empty("No audit events match these filters");
}

function configureRefresh(seconds) {
  if (state.refreshSeconds === seconds && state.timer) return;
  state.refreshSeconds = seconds;
  if (state.timer) window.clearInterval(state.timer);
  state.timer = window.setInterval(refresh, seconds * 1000);
}

function renderSettings(settings) {
  $("settings-list").classList.remove("loading-block");
  const sources = settings.config_sources.map((source) => `${source.name}: ${source.path}`).join("\n");
  $("settings-list").innerHTML = `<div class="settings-safety">Secrets, environment values, and unrestricted command arguments are never accepted here.</div>${settings.runtime_settings.map((setting) => `<article class="setting-card" data-setting-key="${escapeHtml(setting.key)}"><div><strong>${escapeHtml(setting.key.replaceAll("_", " "))}</strong><small>${escapeHtml(setting.description)} · version ${setting.version}</small></div><label>Value (${setting.minimum}-${setting.maximum})<input class="setting-value" type="number" min="${setting.minimum}" max="${setting.maximum}" value="${setting.value}"></label><button type="button" data-setting-save>Save</button></article>`).join("")}<details class="config-sources"><summary>Environment and config sources</summary><pre>${escapeHtml(`Workspace: ${settings.workspace}\nDatabase: ${settings.database}\n${sources}`)}</pre></details>`;
  const refreshSetting = settings.runtime_settings.find((item) => item.key === "dashboard_refresh_seconds");
  const auditSetting = settings.runtime_settings.find((item) => item.key === "audit_page_size");
  if (refreshSetting) configureRefresh(refreshSetting.value);
  if (auditSetting) state.auditPageSize = auditSetting.value;
  state.settingsLoaded = true;
}

async function loadSettings(force = false) {
  if (state.settingsLoaded && !force) return;
  renderSettings(await fetchJson("/api/settings"));
}

function renderGitHubPreview(result) {
  const operations = result.operations.map((operation) => `<article class="preview-operation"><span><strong>${escapeHtml(operation.action)}</strong><small>${escapeHtml(operation.idempotency_key)}</small></span>${operation.number ? `<span>Issue #${operation.number}</span>` : ""}</article>`).join("");
  $("github-preview").innerHTML = `<div class="dry-run-banner"><strong>DRY RUN · nothing executed</strong><span>Immutable SHA-256: <code>${escapeHtml(result.plan_hash)}</code></span><span>Plan ${result.plan_id ?? "not required"} · Gate ${result.gate_id ?? "not required"} (${escapeHtml(result.gate_status)})</span></div><div class="preview-counts"><span>Create ${result.diff.create.length}</span><span>Update ${result.diff.update.length}</span><span>Unchanged ${result.diff.unchanged.length}</span></div>${operations || empty("No create or update operations")}`;
}

function filterQuery() {
  const form = new FormData($("work-filters"));
  const query = new URLSearchParams();
  for (const [key, value] of form.entries()) if (String(value).trim()) query.set(key, String(value).trim());
  return query.toString();
}

async function loadProjects() {
  if (state.projectsLoaded) return;
  const data = await fetchJson("/api/projects?limit=200");
  $("filter-project").insertAdjacentHTML("beforeend", data.items.map((project) => `<option value="${project.id}">${escapeHtml(project.name)}</option>`).join(""));
  state.projectsLoaded = true;
}

async function loadWork() {
  const query = filterQuery();
  const data = await fetchJson(`/api/work-items?limit=200${query ? `&${query}` : ""}`);
  $("work-count").textContent = `${data.total} work item${data.total === 1 ? "" : "s"}`;
  $("work-list").classList.remove("loading-block");
  $("work-list").innerHTML = data.items.length ? data.items.map((item) => `
    <button type="button" class="work-row ${state.selectedTask === item.id ? "selected" : ""}" data-task-id="${item.id}">
      <span><strong>#${item.id} ${escapeHtml(item.title)}</strong><small>${escapeHtml(item.kind)} &middot; Project #${item.project_id}${item.assignee ? ` &middot; ${escapeHtml(item.assignee)}` : ""}</small></span>
      <span class="row-meta">${item.priority ? `<span class="priority">${escapeHtml(item.priority)}</span>` : ""}${badge(item.status)}</span>
    </button>`).join("") : empty("No work items match these filters");
}

function listBlock(title, values, fallback) {
  return `<div class="detail-block"><h3>${escapeHtml(title)}</h3>${values.length ? `<ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : `<p>${escapeHtml(fallback)}</p>`}</div>`;
}

async function selectWorkItem(taskId) {
  state.selectedTask = Number(taskId);
  $("work-detail").innerHTML = empty("Loading delivery contract...");
  const [item, artifacts, runs] = await Promise.all([
    fetchJson(`/api/work-items/${taskId}`),
    fetchJson(`/api/artifacts?task_id=${taskId}&limit=200`),
    fetchJson(`/api/runs?task_id=${taskId}&limit=200`)
  ]);
  $("work-detail").innerHTML = `
    <div class="detail-title"><div><p class="eyebrow">Work item #${item.id}</p><h2>${escapeHtml(item.title)}</h2></div>${badge(item.status)}</div>
    <p class="detail-description">${escapeHtml(item.description || "No description supplied")}</p>
    <dl class="facts"><div><dt>Type</dt><dd>${escapeHtml(item.kind)}</dd></div><div><dt>Priority</dt><dd>${escapeHtml(item.priority || "Not set")}</dd></div><div><dt>Assignee</dt><dd>${escapeHtml(item.assignee || "Unclaimed")}</dd></div><div><dt>Dependencies</dt><dd>${item.dependencies.length ? item.dependencies.map((id) => `#${id}`).join(", ") : "None"}</dd></div></dl>
    ${listBlock("Acceptance criteria", item.acceptance_criteria, "No acceptance criteria")}
    ${listBlock("Expected outputs", item.expected_outputs, "No expected outputs")}
    <div class="detail-block"><h3>Linked artifacts</h3>${artifacts.items.length ? artifacts.items.map((artifact) => `<article class="artifact-row"><span><strong>${escapeHtml(artifact.stage)}</strong><small>#${artifact.id} &middot; ${escapeHtml(artifact.agent_id)} via ${escapeHtml(artifact.provider)}</small></span><span>${badge(artifact.status)}<span class="artifact-actions"><button type="button" data-review="approved" data-artifact-id="${artifact.id}">Approve</button><button type="button" class="danger" data-review="rejected" data-artifact-id="${artifact.id}">Reject</button></span></span></article>`).join("") : `<p>No artifacts yet</p>`}</div>
    <div class="detail-block"><h3>Workflow runs</h3>${runs.items.length ? runs.items.map((run) => `<button type="button" class="text-button" data-run-id="${run.id}">Inspect run #${run.id} (${escapeHtml(run.status)})</button>`).join("") : `<p>No runs yet</p>`}</div>
    <div class="command-bar"><label>Claim as<input id="claim-agent" value="${escapeHtml(item.assignee || "coding-worker-codex")}" aria-label="Agent ID for claim"></label><button type="button" data-command="claim">Claim</button>${item.kind === "task" ? `<button type="button" data-command="run">Run simulation</button>` : `<span class="panel-copy">Only leaf tasks can run; this ${escapeHtml(item.kind)} is a planning item.</span>`}<button type="button" class="danger" data-command="archive">Archive item</button></div>`;
  await loadWork();
}

function parseArtifact(content) {
  const source = String(content || "").replace(/^\[execution_mode=[^\]]+\]\s*/, "");
  try { return JSON.parse(source); } catch (_error) { return { output: source }; }
}

async function showRun(runId) {
  const dialog = $("run-dialog");
  $("run-detail").innerHTML = empty("Loading ordered stage evidence...");
  dialog.showModal();
  try {
    const detail = await fetchJson(`/api/runs/${runId}/detail`);
    let temporal = null;
    if (detail.run.temporal_workflow_id) {
      temporal = await fetchJson(`/api/runs/${runId}/temporal`).catch((error) => ({ error: error.message }));
    }
    $("run-detail-title").textContent = `Run #${detail.run.id} - ${detail.run.workflow_id}`;
    const stages = detail.artifacts.map((artifact, index) => {
      const payload = parseArtifact(artifact.content);
      const review = detail.reviews.find((item) => (item.reviewed_artifact_ids || []).includes(artifact.id));
      const evidence = payload.acceptance_evidence || payload.evidence || payload.output || "No structured evidence";
      const errors = payload.errors || payload.error || "None recorded";
      return `<article class="stage-card"><div class="stage-number">${index + 1}</div><div><div class="stage-head"><h3>${escapeHtml(artifact.stage)}</h3>${badge(artifact.status)}</div><p>${escapeHtml(artifact.agent_id)} &middot; ${escapeHtml(artifact.provider)}</p><dl class="evidence"><div><dt>Verdict</dt><dd>${escapeHtml(review?.verdict || payload.verdict || "Not reviewed")}</dd></div><div><dt>Evidence</dt><dd>${escapeHtml(typeof evidence === "string" ? evidence : JSON.stringify(evidence))}</dd></div><div><dt>Errors</dt><dd>${escapeHtml(typeof errors === "string" ? errors : JSON.stringify(errors))}</dd></div></dl></div></article>`;
    }).join("");
    const temporalPanel = temporal ? `<div class="stop-reason"><strong>Temporal:</strong> ${escapeHtml(temporal.temporal_status || "unavailable")}${temporal.status ? ` &middot; ${escapeHtml(temporal.status.phase)} &middot; ${escapeHtml(temporal.status.last_progress)}` : ""}${temporal.error ? ` &middot; ${escapeHtml(temporal.error)}` : ""}${detail.run.temporal_ui_url ? ` &middot; <a href="${escapeHtml(detail.run.temporal_ui_url)}" target="_blank" rel="noreferrer">Open in Temporal UI</a>` : ""}<br><small>${escapeHtml(detail.run.temporal_workflow_id)}</small></div>` : "";
    const controls = detail.run.temporal_workflow_id ? `<div class="command-bar"><button type="button" data-temporal-action="pause" data-run-id="${detail.run.id}">Pause after current activity</button><button type="button" data-temporal-action="resume" data-run-id="${detail.run.id}">Resume</button><button type="button" class="danger" data-temporal-action="cancel" data-run-id="${detail.run.id}">Cancel</button></div>` : `<div class="command-bar"><button type="button" disabled>Legacy synchronous run</button><span>Resume unavailable without Temporal; Cancel unavailable from the durable workflow controls</span></div>`;
    $("run-detail").innerHTML = `${temporalPanel}<div class="stop-reason"><strong>Stopped because:</strong> ${escapeHtml(detail.stopped_reason)}</div>${stages || empty("No stages have produced artifacts")}${controls}`;
  } catch (error) { $("run-detail").innerHTML = empty(error.message); }
}

function confirmCommand(summary) {
  const dialog = $("confirm-dialog");
  $("confirm-summary").textContent = summary;
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

async function guardedCommand(url, payload, summary) {
  if (!await confirmCommand(summary)) return null;
  const result = await fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Agent-Factory-Confirm": "true" },
    body: JSON.stringify({ ...payload, confirmed: true })
  });
  $("notice").hidden = false;
  $("notice").textContent = `Completed: ${summary}`;
  return result;
}

async function handleWorkAction(target) {
  if (!state.selectedTask) return;
  if (target.dataset.command === "claim") {
    const agentId = $("claim-agent").value.trim();
    if (!agentId) throw new Error("Enter an agent ID before claiming");
    await guardedCommand(`/api/work-items/${state.selectedTask}/claim`, { agent_id: agentId }, `Assign work item #${state.selectedTask} to ${agentId}`);
  } else if (target.dataset.command === "run") {
    const run = await guardedCommand(`/api/work-items/${state.selectedTask}/runs`, { workflow_id: "delivery", mode: "simulation" }, `Run delivery workflow for work item #${state.selectedTask} in simulation mode`);
    if (run) await showRun(run.id);
  } else if (target.dataset.command === "archive") {
    await guardedCommand(`/api/work-items/${state.selectedTask}/archive`, { reason: "Archived from Local Control Center" }, `Archive work item #${state.selectedTask}; active runs, leases, and dependent items will be checked`);
    state.selectedTask = null;
    $("work-detail").innerHTML = empty("Select a work item to inspect its delivery contract");
    await refresh();
    return;
  } else if (target.dataset.review) {
    await guardedCommand(`/api/artifacts/${target.dataset.artifactId}/review`, { task_id: state.selectedTask, decision: target.dataset.review, note: "Reviewed in Local Control Center" }, `${target.dataset.review === "approved" ? "Approve" : "Reject"} artifact #${target.dataset.artifactId}`);
  }
  await Promise.all([refresh(), selectWorkItem(state.selectedTask)]);
}

async function handleAgentAction(target) {
  const card = target.closest("[data-agent-id]");
  if (!card) return;
  const agentId = card.dataset.agentId;
  if (target.dataset.agentToggle) {
    const enabled = target.dataset.agentToggle === "true";
    const action = enabled ? "Enable" : "Disable";
    const result = await guardedCommand(`/api/agents/${encodeURIComponent(agentId)}/enabled`, { enabled }, `${action} ${agentId}; future work and reviewer routing may change`);
    if (result) $("notice").textContent = result.impact_summary;
  } else if (target.hasAttribute("data-agent-provider")) {
    const provider = card.querySelector(".agent-provider").value;
    const model = card.querySelector(".agent-model").value.trim();
    const result = await guardedCommand(`/api/agents/${encodeURIComponent(agentId)}/provider`, { provider, model }, `Replace ${agentId} provider with ${provider} / ${model || `provider:${provider}`}; prior approval snapshots will not be reused`);
    if (result) $("notice").textContent = result.impact_summary;
  }
  await refresh();
}

async function handleSettingAction(target) {
  const card = target.closest("[data-setting-key]");
  if (!card) return;
  const key = card.dataset.settingKey;
  const value = Number(card.querySelector(".setting-value").value);
  await guardedCommand(`/api/settings/${encodeURIComponent(key)}`, { value }, `Set allowlisted runtime setting ${key} to ${value}; a new immutable version and audit event will be recorded`);
  state.settingsLoaded = false;
  await Promise.all([loadSettings(true), loadAudit()]);
}

async function handleGitHubPreview(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  let existingIssues;
  try { existingIssues = JSON.parse(String(form.get("existing_issues") || "[]")); } catch (_error) { throw new Error("Existing issue snapshot must be valid JSON"); }
  if (!Array.isArray(existingIssues)) throw new Error("Existing issue snapshot must be a JSON array");
  const repo = String(form.get("repo") || "").trim();
  const backlogPath = String(form.get("backlog_path") || "").trim();
  const result = await guardedCommand("/api/github/preview", { repo, backlog_path: backlogPath, existing_issues: existingIssues }, `Create an immutable dry-run GitHub plan for ${repo} from ${backlogPath}; no GitHub command will execute and apply still requires separate approval`);
  if (result) { renderGitHubPreview(result); await loadAudit(); }
}

async function handleBacklogImport(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const projectName = String(form.get("project_name") || "").trim();
  const backlogPath = String(form.get("backlog_path") || "").trim();
  const result = await guardedCommand("/api/backlog/import", { project_name: projectName, project_description: "Imported through Local Control Center", backlog_path: backlogPath }, `Import validated backlog ${backlogPath} into local project ${projectName}; existing stable IDs will be skipped`);
  if (!result) return;
  state.projectsLoaded = false;
  $("filter-project").innerHTML = '<option value="">All projects</option>';
  $("notice").textContent = `Backlog import created ${result.created.length} and skipped ${result.skipped.length} work item(s)`;
  await refresh();
}

async function handleSpecificationUpload(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const response = await fetchJson("/api/backlog/analyze-upload", { method: "POST", body: form });
  const counts = Object.entries(response.counts).map(([kind, count]) => `${kind}: ${count}`).join(" · ");
  $("spec-analysis").innerHTML = `<div class="dry-run-banner"><strong>${escapeHtml(response.analysis_status)} · ${escapeHtml(response.recommended_agent)} (${escapeHtml(response.agent_role)})</strong><span>Source type: ${escapeHtml(response.source_type)} · ${escapeHtml(counts)}</span><span>Source: <code>${escapeHtml(response.source_path)}</code></span><button type="button" data-import-analyzed>Import analyzed backlog</button></div><div class="preview-counts">${response.items.map((item) => `<span>${escapeHtml(item.kind)}: ${escapeHtml(item.title)}</span>`).join("")}</div>`;
  $("spec-analysis").dataset.projectName = String(form.get("project_name") || "").trim();
  $("spec-analysis").dataset.backlogPath = response.source_path;
}

async function handleFounderDecision(decision) {
  if (!state.selectedGate) return;
  const packet = state.founderPackets.find((item) => item.approval.id === state.selectedGate);
  if (!packet) return;
  const note = $("founder-note").value.trim();
  const result = await guardedCommand(`/api/founder-decisions/${state.selectedGate}`, { decision, note, actor: "Founder" }, `${decision === "approved" ? "Approve" : "Reject"} final evidence for run #${packet.run.id} as Founder; ${packet.unresolved_findings.length} unresolved finding(s) are displayed and no merge, close, release, or GitHub mutation will run`);
  if (!result) return;
  $("founder-dialog").close();
  $("notice").hidden = false;
  $("notice").textContent = `${result.actor} recorded ${result.resulting_state} for ${result.target} at ${result.timestamp}${result.idempotent ? " (idempotent replay)" : ""}`;
  state.selectedGate = null;
  await Promise.all([refresh(), loadAudit()]);
}

async function refresh() {
  $("refresh").disabled = true;
  try {
    const [dashboard, monitor, executions, agents, providers, reviews, founderPackets] = await Promise.all([
      fetchJson("/api/dashboard"),
      fetchJson("/api/monitor"),
      fetchJson("/api/executions"),
      fetchJson("/api/agents?limit=200"),
      fetchJson("/api/providers?limit=200"),
      fetchJson("/api/reviews?limit=200"),
      fetchJson("/api/founder-decisions"),
      loadProjects(),
      loadWork(),
      loadAudit(),
      loadSettings()
    ]);
    renderDashboard(dashboard); renderMonitor(monitor); renderExecutions(executions); renderRuntime(agents.items, providers.items, reviews.items); renderFounderInbox(founderPackets); state.lastSuccess = new Date();
    $("connection-dot").className = "online"; $("connection-text").textContent = "Local service online";
    $("updated").textContent = `Updated ${state.lastSuccess.toLocaleTimeString()}`; if (!$("notice").textContent.startsWith("Completed:")) $("notice").hidden = true;
  } catch (error) {
    $("connection-dot").className = "offline"; $("connection-text").textContent = "Service disconnected";
    $("notice").hidden = false; $("notice").textContent = state.lastSuccess ? "Live refresh failed. Showing the last successful local snapshot." : "Dashboard data is unavailable. Check the local service and retry.";
    if (!state.lastSuccess) ["metrics","run-list","approval-list","provider-list","failure-list","work-list","agent-list","routing-list","audit-list","settings-list"].forEach((id) => $(id).innerHTML = empty("Unable to load local data"));
  } finally { $("refresh").disabled = false; }
}

$("execution-list").addEventListener("click", (event) => { const action = event.target.closest("[data-execution-action]"); if (!action) return; const type = action.dataset.executionAction; const request = type === "release-lease" ? ["/api/executions/leases/release", { assignment_id: Number(action.dataset.assignment), fencing_token: Number(action.dataset.fence) }, "Release execution lease"] : type === "stop-session" ? [`/api/executions/sessions/${action.dataset.id}/stop`, {}, `Stop runtime session #${action.dataset.id}`] : [`/api/executions/runs/${action.dataset.id}/cancel`, {}, `Cancel workflow run #${action.dataset.id}`]; guardedCommand(request[0], request[1], request[2]).then(() => refresh()).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });

$("refresh").addEventListener("click", refresh);
$("work-filters").addEventListener("submit", (event) => { event.preventDefault(); loadWork().catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("backlog-import-form").addEventListener("submit", (event) => { handleBacklogImport(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("archive-all-work-items").addEventListener("click", () => { guardedCommand("/api/work-items/archive-all", { reason: "Bulk archive from Local Control Center" }, "Archive all active work items; active runs and leases will block this operation").then((result) => { if (result) { $("notice").hidden = false; $("notice").textContent = `Archived ${result.count} work item(s)`; refresh(); } }).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("spec-upload-form").addEventListener("submit", (event) => { handleSpecificationUpload(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("spec-analysis").addEventListener("click", (event) => { if (!event.target.closest("[data-import-analyzed]")) return; const panel = $("spec-analysis"); const command = { project_name: panel.dataset.projectName, project_description: "Imported from analyzed technical specification", backlog_path: panel.dataset.backlogPath }; guardedCommand("/api/backlog/import", command, `Import analyzed specification as ${command.project_name}`).then((result) => { if (result) refresh(); }).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("clear-filters").addEventListener("click", () => { $("work-filters").reset(); loadWork(); });
$("work-list").addEventListener("click", (event) => { const row = event.target.closest("[data-task-id]"); if (row) selectWorkItem(row.dataset.taskId).catch((error) => { $("work-detail").innerHTML = empty(error.message); }); });
$("work-detail").addEventListener("click", (event) => { const action = event.target.closest("[data-command],[data-review],[data-run-id]"); if (!action) return; if (action.dataset.runId) showRun(action.dataset.runId); else handleWorkAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("run-list").addEventListener("click", (event) => { const row = event.target.closest("[data-run-id]"); if (row) showRun(row.dataset.runId); });
$("run-detail").addEventListener("click", (event) => { const action = event.target.closest("[data-temporal-action]"); if (!action) return; const verb = action.dataset.temporalAction; guardedCommand(`/api/executions/runs/${action.dataset.runId}/${verb}`, { reason: `${verb} requested from Local Control Center` }, `${verb} Temporal workflow for run #${action.dataset.runId}`).then(() => showRun(action.dataset.runId)).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("approval-list").addEventListener("click", (event) => { const row = event.target.closest("[data-founder-gate]"); if (row) openFounderDecision(row.dataset.founderGate); });
$("agent-list").addEventListener("click", (event) => { const action = event.target.closest("[data-agent-toggle],[data-agent-provider]"); if (action) handleAgentAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("audit-filters").addEventListener("submit", (event) => { event.preventDefault(); loadAudit().catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("clear-audit").addEventListener("click", () => { $("audit-filters").reset(); loadAudit(); });
$("audit-list").addEventListener("click", (event) => { const row = event.target.closest("[data-run-id]"); if (row) showRun(row.dataset.runId); });
$("settings-list").addEventListener("click", (event) => { const action = event.target.closest("[data-setting-save]"); if (action) handleSettingAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("github-preview-form").addEventListener("submit", (event) => { handleGitHubPreview(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("close-run").addEventListener("click", () => $("run-dialog").close());
$("close-founder").addEventListener("click", () => $("founder-dialog").close());
$("founder-approve").addEventListener("click", () => handleFounderDecision("approved").catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }));
$("founder-reject").addEventListener("click", () => handleFounderDecision("rejected").catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }));
refresh(); state.timer = window.setInterval(refresh, 5000);
