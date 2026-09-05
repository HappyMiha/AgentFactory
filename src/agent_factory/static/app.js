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

const agentEditors = new Map();
const agentIdentity = (agent) => ({ provider: agent.provider, model: agent.model });
const sameIdentity = (left, right) => left.provider === right.provider && left.model === right.model;
function editorIdentity(card) {
  return { provider: card.querySelector('.agent-provider').value, model: card.querySelector('.agent-model').value };
}

function updateAgentEditor(card, editor) {
  const local = editorIdentity(card);
  editor.dirty = !sameIdentity(local, editor.base);
  const conflict = !sameIdentity(editor.base, agentIdentity(editor.server));
  editor.conflict = conflict;
  const warning = card.querySelector('[data-agent-conflict]');
  warning.hidden = !conflict;
  warning.querySelector('span').textContent = `The server changed to ${editor.server.provider} / ${editor.server.model}. Choose a version before saving.`;
  card.querySelector('[data-agent-provider]').disabled = editor.busy || editor.missing || conflict || !editor.dirty;
  card.querySelector('[data-agent-cancel]').disabled = editor.busy;
  card.querySelectorAll('[data-agent-use-server],[data-agent-keep-draft]').forEach((button) => button.disabled = editor.busy);
  card.querySelectorAll('.agent-provider,.agent-model').forEach((input) => input.disabled = editor.busy);
  card.querySelector('[data-agent-edit-status]').textContent = editor.missing ? 'This agent is no longer available. Your draft is kept here.' :
    editor.busy ? 'Waiting for the save result. Your draft is kept.' : editor.message || (editor.dirty ? 'Unsaved changes.' : 'No unsaved changes.');
}

function setEditorIdentity(card, identity) {
  const select = card.querySelector('.agent-provider');
  if (![...select.options].some((option) => option.value === identity.provider)) {
    select.add(new Option(`${identity.provider} (not currently available)`, identity.provider));
  }
  select.value = identity.provider;
  card.querySelector('.agent-model').value = identity.model;
}

function renderAgentCards(agents, providers) {
  const list = $('agent-list');
  const present = new Set();
  if (!agentEditors.size) list.replaceChildren();
  agents.forEach((agent) => {
    present.add(agent.id);
    let editor = agentEditors.get(agent.id);
    if (!editor) {
      const card = document.createElement('article');
      card.className = 'agent-card';
      card.dataset.agentId = agent.id;
      card.innerHTML = `<div data-agent-summary></div><div class="agent-controls"><button type="button" data-agent-toggle></button><label>Compatible provider<select class="agent-provider"></select></label><label>Model identity<input class="agent-model"></label><button type="button" data-agent-provider>Save changes</button><button type="button" class="secondary" data-agent-cancel>Cancel changes</button></div><div data-agent-conflict role="status" hidden><span></span> <button type="button" data-agent-use-server>Use server version</button> <button type="button" data-agent-keep-draft>Keep my draft</button></div><p data-agent-edit-status role="status"></p>`;
      list.append(card);
      editor = { card, base: agentIdentity(agent), server: agent, dirty: false, busy: false, message: '' };
      agentEditors.set(agent.id, editor);
      setEditorIdentity(card, editor.base);
    }
    const { card } = editor;
    const editing = editor.dirty || editor.busy || card.querySelector('.agent-controls').contains(document.activeElement);
    editor.server = agent;
    editor.missing = false;
    // Update facts separately: the controls, selection and caret keep their nodes.
    card.querySelector('[data-agent-summary]').innerHTML = `<div class="agent-title"><span><strong>${escapeHtml(agent.name)}</strong><small>${escapeHtml(agent.id)} &middot; ${escapeHtml(agent.role)}</small></span>${badge(agent.enabled ? 'enabled' : 'disabled')}</div><dl class="agent-facts"><div><dt>Provider / model</dt><dd>${escapeHtml(agent.provider)} / ${escapeHtml(agent.model)}</dd></div><div><dt>Recent work</dt><dd>${agent.last_claimed_task_id ? `Task #${agent.last_claimed_task_id}` : 'No claim'}</dd></div><div><dt>Reviewer use</dt><dd>${agent.reviewer_assignment_count}${agent.last_reviewed_run_id ? ` (last run #${agent.last_reviewed_run_id})` : ''}</dd></div><div><dt>Permissions</dt><dd>${escapeHtml(agent.permissions.join(', '))}</dd></div></dl>`;
    const toggle = card.querySelector('[data-agent-toggle]');
    toggle.dataset.agentToggle = String(!agent.enabled);
    toggle.textContent = agent.enabled ? 'Disable' : 'Enable';
    toggle.className = agent.enabled ? 'danger' : '';
    const select = card.querySelector('.agent-provider');
    const selected = select.value;
    const compatible = providers.filter((provider) => provider.enabled && (provider.id === 'deterministic' || provider.allowed_roles.includes(agent.role)));
    const available = new Set(compatible.map((provider) => provider.id));
    compatible.forEach((provider) => {
      let option = [...select.options].find((item) => item.value === provider.id);
      if (!option) { option = new Option('', provider.id); select.add(option); }
      const label = `${provider.id} (${provider.status})`;
      if (option.textContent !== label) option.textContent = label;
    });
    [...select.options].forEach((option) => {
      if (!available.has(option.value)) {
        if (option.value === selected) option.textContent = `${option.value} (not currently available)`;
        else option.remove();
      }
    });
    select.value = selected;
    if (!editing) {
      editor.base = agentIdentity(agent);
      setEditorIdentity(card, editor.base);
    }
    updateAgentEditor(card, editor);
  });
  agentEditors.forEach((editor, id) => {
    if (present.has(id)) return;
    if (editor.dirty || editor.busy || editor.card.contains(document.activeElement)) {
      editor.missing = true;
      updateAgentEditor(editor.card, editor);
    } else {
      editor.card.remove();
      agentEditors.delete(id);
    }
  });
  if (!agentEditors.size) list.innerHTML = empty('No agents configured');
}

function renderRuntime(agents, providers, reviews) {
  $("agent-list").classList.remove("loading-block");
  $("routing-list").classList.remove("loading-block");
  renderAgentCards(agents, providers);
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

let confirmationPending = false;
const pendingCommands = new Set();

function confirmCommand(summary) {
  if (confirmationPending) return Promise.resolve(false);
  const dialog = $("confirm-dialog");
  const initiator = document.activeElement;
  const form = dialog.querySelector("form");
  confirmationPending = true;
  dialog.returnValue = "";
  $("confirm-summary").textContent = summary;
  return new Promise((resolve, reject) => {
    let explicitlyConfirmed = false;
    const onSubmit = (event) => {
      explicitlyConfirmed = event.submitter === $("confirm-action");
    };
    const onCancel = () => { explicitlyConfirmed = false; };
    const cleanup = () => {
      form.removeEventListener("submit", onSubmit);
      dialog.removeEventListener("cancel", onCancel);
      dialog.removeEventListener("close", onClose);
      confirmationPending = false;
      if (initiator?.isConnected) initiator.focus();
    };
    const onClose = () => {
      const confirmed = explicitlyConfirmed && dialog.returnValue === "confirm";
      cleanup();
      resolve(confirmed);
    };
    form.addEventListener("submit", onSubmit);
    dialog.addEventListener("cancel", onCancel);
    dialog.addEventListener("close", onClose);
    try {
      dialog.showModal();
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}

async function guardedCommand(url, payload, summary, beforeSend = null) {
  const body = JSON.stringify({ ...payload, confirmed: true });
  const commandKey = JSON.stringify([url, body]);
  if (pendingCommands.has(commandKey)) return null;
  pendingCommands.add(commandKey);
  try {
    if (!await confirmCommand(summary)) return null;
    if (beforeSend && !await beforeSend()) return null;
    const result = await fetchJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Agent-Factory-Confirm": "true" },
      body
    });
    $("notice").hidden = false;
    $("notice").textContent = `Completed: ${summary}`;
    return result;
  } finally {
    pendingCommands.delete(commandKey);
  }
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
  const editor = agentEditors.get(agentId);
  if (target.matches('[data-agent-cancel],[data-agent-use-server],[data-agent-keep-draft]')) {
    if (editor.busy) return;
    const keep = target.hasAttribute('data-agent-keep-draft');
    editor.base = agentIdentity(editor.server);
    if (!keep) setEditorIdentity(card, editor.base);
    editor.message = keep ? 'Your draft is kept. Save changes to replace the server version.' : 'Changes cancelled. Latest server version shown.';
    updateAgentEditor(card, editor);
    return;
  }
  if (target.dataset.agentToggle) {
    const enabled = target.dataset.agentToggle === "true";
    const action = enabled ? "Enable" : "Disable";
    const result = await guardedCommand(`/api/agents/${encodeURIComponent(agentId)}/enabled`, { enabled }, `${action} ${agentId}; future work and reviewer routing may change`);
    if (result) $("notice").textContent = result.impact_summary;
  } else if (target.hasAttribute("data-agent-provider")) {
    updateAgentEditor(card, editor);
    if (editor.busy || editor.missing || editor.conflict || !editor.dirty) return;
    const provider = card.querySelector(".agent-provider").value;
    const model = card.querySelector(".agent-model").value.trim();
    const expected = { ...editor.base };
    editor.busy = true;
    editor.message = '';
    updateAgentEditor(card, editor);
    try {
      const result = await guardedCommand(`/api/agents/${encodeURIComponent(agentId)}/provider`, { provider, model }, `Replace ${agentId} provider with ${provider} / ${model || `provider:${provider}`}; prior approval snapshots will not be reused`, async () => {
        const latest = await fetchJson('/api/agents?limit=200');
        state.refreshGeneration = (state.refreshGeneration || 0) + 1;
        const current = latest.items.find((agent) => agent.id === agentId);
        if (!current) { editor.missing = true; return false; }
        editor.server = current;
        return sameIdentity(expected, agentIdentity(current));
      });
      if (result) {
        state.refreshGeneration = (state.refreshGeneration || 0) + 1;
        editor.server = result.agent;
        editor.base = agentIdentity(result.agent);
        setEditorIdentity(card, editor.base);
        editor.message = 'Changes saved. Future assignments use this provider and model.';
      } else {
        editor.message = 'Save cancelled. Your draft is kept.';
      }
    } catch (error) {
      editor.message = `Save failed: ${error.message}. Your draft is kept; refresh before retrying an uncertain result.`;
      throw error;
    } finally {
      editor.busy = false;
      updateAgentEditor(card, editor);
    }
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
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const response = await fetchJson("/api/backlog/analyze-upload", { method: "POST", body: form });
    const panel = $("spec-analysis");
    panel.innerHTML = `<div class="dry-run-banner"><strong>Deterministic import · Needs your review</strong><span>No AI analysis was run. These are editable proposals, not a confirmed plan.</span><span>Original source: <code>${escapeHtml(response.original_path)}</code></span></div><details><summary>Original extracted text</summary><pre>${escapeHtml(response.original_text)}</pre></details><form id="spec-preview-form">${response.items.map((item) => `<fieldset data-preview-item="${escapeHtml(item.stable_id)}"><legend>${escapeHtml(item.kind)} · ${escapeHtml(item.stable_id)}</legend><label>Title<input name="title" required value="${escapeHtml(item.title)}"></label><label>Requirements<textarea name="description" required rows="4">${escapeHtml(item.description)}</textarea></label><label>Acceptance criteria (one per line)<textarea name="acceptance_criteria" required rows="3">${escapeHtml(item.acceptance_criteria.join("\n"))}</textarea></label></fieldset>`).join("")}<button type="submit" data-import-analyzed>Confirm and import edited plan</button><p data-preview-status role="status"></p></form>`;
    panel.dataset.projectName = String(form.get("project_name") || "").trim();
    panel.dataset.backlogPath = response.source_path;
  } finally {
    button.disabled = false;
  }
}

async function handleSpecificationImport(event) {
  event.preventDefault();
  const form = event.target.closest('#spec-preview-form');
  if (!form || !form.reportValidity()) return;
  const panel = $("spec-analysis");
  const reviewedItems = [...form.querySelectorAll('[data-preview-item]')].map((item) => ({
    stable_id: item.dataset.previewItem,
    title: item.querySelector('[name="title"]').value,
    description: item.querySelector('[name="description"]').value,
    acceptance_criteria: item.querySelector('[name="acceptance_criteria"]').value.split("\n").map((value) => value.trim()).filter(Boolean),
  }));
  if (reviewedItems.some((item) => !item.acceptance_criteria.length)) throw new Error('Each item needs an acceptance criterion.');
  const button = form.querySelector('[data-import-analyzed]');
  button.disabled = true;
  try {
    const result = await guardedCommand('/api/backlog/import', {
      project_name: panel.dataset.projectName,
      project_description: 'User-reviewed deterministic specification import',
      backlog_path: panel.dataset.backlogPath,
      reviewed_items: reviewedItems,
    }, `Confirm this edited plan and import it into ${panel.dataset.projectName}; no AI analysis or product acceptance is implied`);
    if (!result) return;
    form.querySelector('[data-preview-status]').textContent = `Plan confirmed. Created ${result.created.length}; skipped ${result.skipped.length} existing items. Existing items were not updated; product acceptance is still separate.`;
    state.projectsLoaded = false;
    await refresh();
  } finally {
    button.disabled = false;
  }
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
  const generation = state.refreshGeneration = (state.refreshGeneration || 0) + 1;
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
    if (generation !== state.refreshGeneration) return;
    renderDashboard(dashboard); renderMonitor(monitor); renderExecutions(executions); renderRuntime(agents.items, providers.items, reviews.items); renderFounderInbox(founderPackets); state.lastSuccess = new Date();
    $("connection-dot").className = "online"; $("connection-text").textContent = "Local service online";
    $("updated").textContent = `Updated ${state.lastSuccess.toLocaleTimeString()}`; if (!$("notice").textContent.startsWith("Completed:")) $("notice").hidden = true;
  } catch (error) {
    if (generation !== state.refreshGeneration) return;
    $("connection-dot").className = "offline"; $("connection-text").textContent = "Service disconnected";
    $("notice").hidden = false; $("notice").textContent = state.lastSuccess ? "Live refresh failed. Showing the last successful local snapshot." : "Dashboard data is unavailable. Check the local service and retry.";
    if (!state.lastSuccess) ["metrics","run-list","approval-list","provider-list","failure-list","work-list","agent-list","routing-list","audit-list","settings-list"].forEach((id) => $(id).innerHTML = empty("Unable to load local data"));
  } finally { if (generation === state.refreshGeneration) $("refresh").disabled = false; }
}

$("execution-list").addEventListener("click", (event) => { const action = event.target.closest("[data-execution-action]"); if (!action) return; const type = action.dataset.executionAction; const request = type === "release-lease" ? ["/api/executions/leases/release", { assignment_id: Number(action.dataset.assignment), fencing_token: Number(action.dataset.fence) }, "Release execution lease"] : type === "stop-session" ? [`/api/executions/sessions/${action.dataset.id}/stop`, {}, `Stop runtime session #${action.dataset.id}`] : [`/api/executions/runs/${action.dataset.id}/cancel`, {}, `Cancel workflow run #${action.dataset.id}`]; guardedCommand(request[0], request[1], request[2]).then(() => refresh()).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });

$("refresh").addEventListener("click", refresh);
$("work-filters").addEventListener("submit", (event) => { event.preventDefault(); loadWork().catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("backlog-import-form").addEventListener("submit", (event) => { handleBacklogImport(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("archive-all-work-items").addEventListener("click", () => { guardedCommand("/api/work-items/archive-all", { reason: "Bulk archive from Local Control Center" }, "Archive all active work items; active runs and leases will block this operation").then((result) => { if (result) { $("notice").hidden = false; $("notice").textContent = `Archived ${result.count} work item(s)`; refresh(); } }).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("spec-upload-form").addEventListener("submit", (event) => { handleSpecificationUpload(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("spec-analysis").addEventListener("submit", (event) => { handleSpecificationImport(event).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("clear-filters").addEventListener("click", () => { $("work-filters").reset(); loadWork(); });
$("work-list").addEventListener("click", (event) => { const row = event.target.closest("[data-task-id]"); if (row) selectWorkItem(row.dataset.taskId).catch((error) => { $("work-detail").innerHTML = empty(error.message); }); });
$("work-detail").addEventListener("click", (event) => { const action = event.target.closest("[data-command],[data-review],[data-run-id]"); if (!action) return; if (action.dataset.runId) showRun(action.dataset.runId); else handleWorkAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("run-list").addEventListener("click", (event) => { const row = event.target.closest("[data-run-id]"); if (row) showRun(row.dataset.runId); });
$("run-detail").addEventListener("click", (event) => { const action = event.target.closest("[data-temporal-action]"); if (!action) return; const verb = action.dataset.temporalAction; guardedCommand(`/api/executions/runs/${action.dataset.runId}/${verb}`, { reason: `${verb} requested from Local Control Center` }, `${verb} Temporal workflow for run #${action.dataset.runId}`).then(() => showRun(action.dataset.runId)).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("approval-list").addEventListener("click", (event) => { const row = event.target.closest("[data-founder-gate]"); if (row) openFounderDecision(row.dataset.founderGate); });
$("agent-list").addEventListener("click", (event) => { const action = event.target.closest("[data-agent-toggle],[data-agent-provider],[data-agent-cancel],[data-agent-use-server],[data-agent-keep-draft]"); if (action) handleAgentAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
function handleAgentDraft(event) {
  if (!event.target.matches('.agent-provider,.agent-model')) return;
  const card = event.target.closest('[data-agent-id]');
  const editor = agentEditors.get(card.dataset.agentId);
  editor.message = '';
  updateAgentEditor(card, editor);
}
$('agent-list').addEventListener('input', handleAgentDraft);
$('agent-list').addEventListener('change', handleAgentDraft);
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
