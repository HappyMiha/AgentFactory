const state = { lastSuccess: null, timer: null, selectedTask: null, projectsLoaded: false };
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
  $("run-list").innerHTML = data.runs.length ? data.runs.map((run) => `<button class="list-row row-button" type="button" data-run-id="${run.id}"><span><strong>${escapeHtml(run.workflow_id)}</strong><small>Run #${run.id} &middot; Task #${run.task_id}</small></span>${badge(run.status)}</button>`).join("") : empty("No workflow runs yet");
  $("approval-list").innerHTML = data.pending_approvals.length ? data.pending_approvals.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.kind)} approval</strong><small>${escapeHtml(item.target_type)} #${item.target_id}</small></span>${badge(item.status)}</div>`).join("") : empty("No decisions are waiting");
  $("provider-list").innerHTML = data.providers.length ? data.providers.map((item) => `<article class="provider"><span class="health health-${escapeHtml(item.status)}" aria-hidden="true"></span><span><strong>${escapeHtml(item.id)}</strong><small>${escapeHtml(item.type)} &middot; ${escapeHtml(item.status)}${item.version ? ` &middot; ${escapeHtml(item.version)}` : ""}</small><small>${escapeHtml(item.path || item.error || "No executable detail")}</small><small>Execution ${item.execution_enabled ? "enabled" : "disabled"} &middot; Roles: ${escapeHtml(item.allowed_roles.join(", ") || "simulation only")}</small><details><summary>Redacted health detail</summary><pre>${escapeHtml(JSON.stringify(item.health_details, null, 2))}</pre></details></span></article>`).join("") : empty("No providers configured");
  $("failure-list").innerHTML = data.recent_failures.length ? data.recent_failures.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.event_type)}</strong><small>${escapeHtml(item.entity_type)} #${escapeHtml(item.entity_id)}</small></span><time>${escapeHtml(item.created_at)}</time></div>`).join("") : empty("No recent failures");
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
    <div class="command-bar"><label>Claim as<input id="claim-agent" value="${escapeHtml(item.assignee || "coding-worker-codex")}" aria-label="Agent ID for claim"></label><button type="button" data-command="claim">Claim</button><button type="button" data-command="run">Run simulation</button></div>`;
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
    $("run-detail-title").textContent = `Run #${detail.run.id} - ${detail.run.workflow_id}`;
    const stages = detail.artifacts.map((artifact, index) => {
      const payload = parseArtifact(artifact.content);
      const review = detail.reviews.find((item) => (item.reviewed_artifact_ids || []).includes(artifact.id));
      const evidence = payload.acceptance_evidence || payload.evidence || payload.output || "No structured evidence";
      const errors = payload.errors || payload.error || "None recorded";
      return `<article class="stage-card"><div class="stage-number">${index + 1}</div><div><div class="stage-head"><h3>${escapeHtml(artifact.stage)}</h3>${badge(artifact.status)}</div><p>${escapeHtml(artifact.agent_id)} &middot; ${escapeHtml(artifact.provider)}</p><dl class="evidence"><div><dt>Verdict</dt><dd>${escapeHtml(review?.verdict || payload.verdict || "Not reviewed")}</dd></div><div><dt>Evidence</dt><dd>${escapeHtml(typeof evidence === "string" ? evidence : JSON.stringify(evidence))}</dd></div><div><dt>Errors</dt><dd>${escapeHtml(typeof errors === "string" ? errors : JSON.stringify(errors))}</dd></div></dl></div></article>`;
    }).join("");
    $("run-detail").innerHTML = `<div class="stop-reason"><strong>Stopped because:</strong> ${escapeHtml(detail.stopped_reason)}</div>${stages || empty("No stages have produced artifacts")}<div class="command-bar"><button type="button" disabled title="Resume is not supported in the MVP">Resume unavailable</button><button type="button" disabled title="Cancellation is not supported in the MVP">Cancel unavailable</button></div>`;
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

async function refresh() {
  $("refresh").disabled = true;
  try {
    const [dashboard, agents, providers, reviews] = await Promise.all([
      fetchJson("/api/dashboard"),
      fetchJson("/api/agents?limit=200"),
      fetchJson("/api/providers?limit=200"),
      fetchJson("/api/reviews?limit=200"),
      loadProjects(),
      loadWork()
    ]);
    renderDashboard(dashboard); renderRuntime(agents.items, providers.items, reviews.items); state.lastSuccess = new Date();
    $("connection-dot").className = "online"; $("connection-text").textContent = "Local service online";
    $("updated").textContent = `Updated ${state.lastSuccess.toLocaleTimeString()}`; if (!$("notice").textContent.startsWith("Completed:")) $("notice").hidden = true;
  } catch (error) {
    $("connection-dot").className = "offline"; $("connection-text").textContent = "Service disconnected";
    $("notice").hidden = false; $("notice").textContent = state.lastSuccess ? "Live refresh failed. Showing the last successful local snapshot." : "Dashboard data is unavailable. Check the local service and retry.";
    if (!state.lastSuccess) ["metrics","run-list","approval-list","provider-list","failure-list","work-list","agent-list","routing-list"].forEach((id) => $(id).innerHTML = empty("Unable to load local data"));
  } finally { $("refresh").disabled = false; }
}

$("refresh").addEventListener("click", refresh);
$("work-filters").addEventListener("submit", (event) => { event.preventDefault(); loadWork().catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("clear-filters").addEventListener("click", () => { $("work-filters").reset(); loadWork(); });
$("work-list").addEventListener("click", (event) => { const row = event.target.closest("[data-task-id]"); if (row) selectWorkItem(row.dataset.taskId).catch((error) => { $("work-detail").innerHTML = empty(error.message); }); });
$("work-detail").addEventListener("click", (event) => { const action = event.target.closest("[data-command],[data-review],[data-run-id]"); if (!action) return; if (action.dataset.runId) showRun(action.dataset.runId); else handleWorkAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("run-list").addEventListener("click", (event) => { const row = event.target.closest("[data-run-id]"); if (row) showRun(row.dataset.runId); });
$("agent-list").addEventListener("click", (event) => { const action = event.target.closest("[data-agent-toggle],[data-agent-provider]"); if (action) handleAgentAction(action).catch((error) => { $("notice").hidden = false; $("notice").textContent = error.message; }); });
$("close-run").addEventListener("click", () => $("run-dialog").close());
refresh(); state.timer = window.setInterval(refresh, 5000);
