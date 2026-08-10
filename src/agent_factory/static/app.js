const state = { lastSuccess: null, timer: null };
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);

function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }
function badge(status) { return `<span class="badge status-${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</span>`; }
function metric(label, value, tone) { return `<article class="metric tone-${tone}"><span>${escapeHtml(label)}</span><strong>${value}</strong><i aria-hidden="true"></i></article>`; }

function render(data) {
  const c = data.counts;
  $("metrics").innerHTML = [
    metric("Ready", c.ready, "mint"), metric("Active", c.active, "blue"), metric("Blocked", c.blocked, "amber"),
    metric("Failed", c.failed, "red"), metric("Awaiting review", c.awaiting_review, "violet"), metric("Awaiting approval", c.awaiting_approval, "cyan")
  ].join("");
  $("run-list").innerHTML = data.runs.length ? data.runs.map((run) => `<a class="list-row" href="/api/runs/${run.id}"><span><strong>${escapeHtml(run.workflow_id)}</strong><small>Run #${run.id} · Task #${run.task_id}</small></span>${badge(run.status)}</a>`).join("") : empty("No workflow runs yet");
  $("approval-list").innerHTML = data.pending_approvals.length ? data.pending_approvals.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.kind)} approval</strong><small>${escapeHtml(item.target_type)} #${item.target_id}</small></span>${badge(item.status)}</div>`).join("") : empty("No decisions are waiting");
  $("provider-list").innerHTML = data.providers.length ? data.providers.map((item) => `<article class="provider"><span class="health health-${escapeHtml(item.status)}" aria-hidden="true"></span><span><strong>${escapeHtml(item.id)}</strong><small>${escapeHtml(item.type)} · ${escapeHtml(item.status)}</small></span></article>`).join("") : empty("No providers configured");
  $("failure-list").innerHTML = data.recent_failures.length ? data.recent_failures.map((item) => `<div class="list-row"><span><strong>${escapeHtml(item.event_type)}</strong><small>${escapeHtml(item.entity_type)} #${escapeHtml(item.entity_id)}</small></span><time>${escapeHtml(item.created_at)}</time></div>`).join("") : empty("No recent failures");
}

async function refresh() {
  $("refresh").disabled = true;
  try {
    const response = await fetch("/api/dashboard", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    render(data); state.lastSuccess = new Date();
    $("connection-dot").className = "online"; $("connection-text").textContent = "Local service online";
    $("updated").textContent = `Updated ${state.lastSuccess.toLocaleTimeString()}`; $("notice").hidden = true;
  } catch (error) {
    $("connection-dot").className = "offline"; $("connection-text").textContent = "Service disconnected";
    $("notice").hidden = false; $("notice").textContent = state.lastSuccess ? "Live refresh failed. Showing the last successful local snapshot." : "Dashboard data is unavailable. Check the local service and retry.";
    if (!state.lastSuccess) ["metrics","run-list","approval-list","provider-list","failure-list"].forEach((id) => $(id).innerHTML = empty("Unable to load local data"));
  } finally { $("refresh").disabled = false; }
}

$("refresh").addEventListener("click", refresh);
refresh(); state.timer = window.setInterval(refresh, 5000);
