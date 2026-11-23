"use strict";

const $ = (id) => document.getElementById(id);
const fields = ["startDate", "startTime", "endDate", "endTime"].map($);
let polling = null;
let available = null; // Reviewer's data range for the record, from the latest run that checked it.

function show(stamp) {
  const [d, t] = stamp.split("T"), [y, m, day] = d.split("-");
  return `${day}/${m}/${y} ${t}`;
}

function checkAvailable() {
  const box = $("available");
  if (!available) { box.hidden = true; return; }
  box.hidden = false;
  const start = read("start"), end = read("end");
  const outside = start && end && (start.text < available.start || end.text > available.end);
  box.classList.toggle("outside", !!outside);
  box.textContent = `Reviewer has data for ${available.record} from ${show(available.start)} to ${show(available.end)} IST`
    + (available.checked ? ` (checked ${available.checked}).` : ".")
    + (outside ? " Your range goes outside this, so the run will be refused unless new data has arrived since." : "");
}

function pad(n) { return String(n).padStart(2, "0"); }
function dateValue(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function timeValue(d) { return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }

// Dates are read as wall-clock values; the server adds +05:30.
function read(prefix) {
  const date = $(prefix + "Date").value, time = $(prefix + "Time").value;
  if (!date || !time) return null;
  const [y, m, d] = date.split("-").map(Number), [h, min] = time.split(":").map(Number);
  return { text: `${date}T${time}`, value: new Date(y, m - 1, d, h, min) };
}

function write(prefix, d) {
  $(prefix + "Date").value = dateValue(d);
  $(prefix + "Time").value = timeValue(d);
}

function duration(minutes) {
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return [h ? `${h} h` : "", m ? `${m} min` : ""].filter(Boolean).join(" ") || "0 min";
}

function updateSummary() {
  const start = read("start"), end = read("end");
  if (!start || !end) { $("summary").textContent = "Choose a start and end."; return false; }
  const minutes = Math.round((end.value - start.value) / 60000);
  if (minutes <= 0) { $("summary").textContent = "End must be after start."; return false; }
  const fmt = (r) => r.value.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  $("summary").textContent = `${fmt(start)} to ${fmt(end)} IST (${duration(minutes)})`;
  checkAvailable();
  return true;
}

function elapsed(seconds) {
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return h ? `${h}h ${pad(m)}m` : `${m}m ${pad(s)}s`;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function render(s) {
  available = s.dataRange || null;
  checkAvailable();
  const otherActive = !s.running && s.lock === "active";
  $("run").disabled = s.running || s.lock !== "none";
  fields.forEach((f) => { f.disabled = s.running; });
  $("showBrowser").disabled = s.running;
  $("stop").hidden = !s.running;
  $("stop").disabled = s.outcome === "Stopping";
  $("lockNotice").hidden = s.running || s.lock !== "stale";
  if (otherActive) {
    $("message").textContent = "Another automation run is active (started outside this page). Run is disabled until it finishes.";
    startPolling();
  } else if ($("message").dataset.kind === "lock") {
    $("message").textContent = "";
  }
  $("message").dataset.kind = otherActive ? "lock" : "";
  if (!s.outcome) { $("progressCard").hidden = true; return; }

  $("progressCard").hidden = false;
  const badge = $("badge");
  badge.textContent = s.outcome;
  badge.className = "badge " + ({ Running: "running", Stopping: "stopped", Completed: "done", Stopped: "stopped", Failed: "failed" }[s.outcome] || "");

  const total = s.messagesSkipped ? (s.totalReports / 3) * 2 : s.totalReports;
  const pct = total ? Math.min(100, Math.round((s.reportsDone / total) * 100)) : 0;
  $("barFill").style.width = pct + "%";
  let counts = `${s.reportsDone} of ${total} reports (${pct}%) · ${elapsed(s.elapsedSeconds)}`;
  if (s.running && s.reportsDone > 0 && s.reportsDone < total) {
    const left = Math.round((s.elapsedSeconds / s.reportsDone) * (total - s.reportsDone) / 60);
    counts += ` · about ${duration(left)} left`;
  }
  $("counts").textContent = counts;

  let now = `Range ${s.start.replace("T", " ")} to ${s.end.replace("T", " ")} IST, started ${s.startedAt}`;
  if (s.running && s.currentProfile) now = `Now: ${s.currentProfile}${s.currentChannel ? " – " + s.currentChannel : ""}`;
  if (s.messagesSkipped) now += " · no messages in this range, message PDFs skipped";
  $("now").textContent = now;

  const list = $("activity");
  list.replaceChildren(...(s.activity || []).map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    if (line.includes("FAILED")) li.className = "bad";
    return li;
  }));
  list.scrollTop = list.scrollHeight;

  if (s.outcome === "Failed" && s.error) {
    $("message").textContent = friendly(s.error);
  }
  $("openFolder").hidden = !s.folder;
  $("folder").textContent = s.folder || "";

  if (!s.running && !otherActive && polling) { clearInterval(polling); polling = null; }
}

function friendly(error) {
  if (error.includes("INTERVAL_OUTSIDE_INPUT")) return "The input file still needs importing and does not cover that range. Pick dates inside the file's recording.";
  if (/MISSING_DATA|no measurement samples|no recording range/i.test(error)) {
    // The automation says exactly what was requested, what Reviewer has, and which side misses.
    const detail = (error.match(/(Requested .*?)\)?$/s) || [])[1];
    const range = detail || (available ? `Reviewer has data from ${show(available.start)} to ${show(available.end)} IST.` : "");
    return `No reports were made: Reviewer has no data for this record in that range. ${range} Pick dates inside the data range, or wait until newer recordings reach Reviewer.`;
  }
  if (error.includes("Timeout")) return "Reviewer did not respond in time. Check that Reviewer is working, then press Run again with the same dates to continue where it stopped.";
  if (error.includes("ended unexpectedly")) return "The run was closed before it finished. Press Run again with the same dates to continue where it stopped.";
  return error;
}

$("clearLock").addEventListener("click", async () => {
  $("message").textContent = "";
  try { render(await api("/api/clear-lock", {})); } catch (e) { $("message").textContent = e.message; }
});

async function refresh() {
  try { render(await api("/api/status")); }
  catch (e) { $("message").textContent = "Cannot reach the Report Runner server. Is the Start window still open?"; }
}

function startPolling() {
  if (!polling) polling = setInterval(refresh, 3000);
}

$("run").addEventListener("click", async () => {
  $("message").textContent = "";
  if (!updateSummary()) { $("message").textContent = "Please set a valid start and end."; return; }
  try {
    render(await api("/api/run", { start: read("start").text, end: read("end").text, showBrowser: $("showBrowser").checked }));
    startPolling();
  } catch (e) { $("message").textContent = e.message; }
});

$("stop").addEventListener("click", async () => {
  try { render(await api("/api/stop", {})); } catch (e) { $("message").textContent = e.message; }
});

$("openFolder").addEventListener("click", async () => {
  try { await api("/api/open-folder", {}); } catch (e) { $("message").textContent = e.message; }
});

$("wholeDay").addEventListener("click", () => {
  const start = read("start");
  const base = start ? start.value : new Date();
  const day = new Date(base.getFullYear(), base.getMonth(), base.getDate());
  write("start", day);
  write("end", new Date(day.getTime() + 24 * 3600000));
  updateSummary();
});

document.querySelectorAll("[data-hours]").forEach((b) => b.addEventListener("click", () => {
  const start = read("start");
  if (!start) { $("message").textContent = "Set the start first."; return; }
  write("end", new Date(start.value.getTime() + Number(b.dataset.hours) * 3600000));
  updateSummary();
}));

fields.forEach((f) => f.addEventListener("input", updateSummary));

function syncHint() { $("browserHint").hidden = !$("showBrowser").checked; }
$("showBrowser").addEventListener("change", syncHint);

// Default: yesterday, whole day.
(() => {
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  write("start", yesterday);
  write("end", new Date(yesterday.getTime() + 24 * 3600000));
  updateSummary();
})();

api("/api/status").then((s) => {
  render(s);
  if (s.running) {
    // A run started earlier (or before the server restarted): show its dates and follow it.
    $("startDate").value = s.start.slice(0, 10); $("startTime").value = s.start.slice(11);
    $("endDate").value = s.end.slice(0, 10); $("endTime").value = s.end.slice(11);
    $("showBrowser").checked = !!s.showBrowser;
    syncHint();
    updateSummary();
    startPolling();
  }
}).catch(() => { $("message").textContent = "Cannot reach the Report Runner server. Is the Start window still open?"; });
