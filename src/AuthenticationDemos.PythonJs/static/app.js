(() => {
  const page = document.body.dataset.page;
  if (!page || (page !== "service_principal" && page !== "obo")) return;

  const mode = page === "service_principal" ? "service_principal" : "obo";
  const runBtn = document.getElementById("run-demo");
  const clearBtn = document.getElementById("clear-logs");
  const logBody = document.getElementById("log-body");
  const containerSelect = document.getElementById("container-select");
  const storageItems = document.getElementById("storage-items");
  const breadcrumb = document.getElementById("breadcrumb");
  const tableSelect = document.getElementById("table-select");
  const topNInput = document.getElementById("top-n");
  const queryBtn = document.getElementById("query-btn");
  const sqlResults = document.getElementById("sql-results");

  let currentPrefix = null;
  let tables = [];

  const levelClass = (lvl) => `log-${String(lvl || "info").toLowerCase()}`;

  async function api(url, options = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      let err = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        err = body.error || err;
      } catch (_) {}
      throw new Error(err);
    }
    return res.json();
  }

  async function refreshLogs() {
    const entries = await api(`/api/logs?mode=${mode}`);
    logBody.innerHTML = "";
    entries.forEach((entry) => {
      const row = document.createElement("div");
      row.className = `log-entry ${levelClass(entry.level)}`;
      row.innerHTML = `<span class="log-time">${new Date(entry.timestamp).toLocaleTimeString()}</span><span class="log-level">[${entry.level}]</span><span>${escapeHtml(entry.message)}</span>`;
      logBody.appendChild(row);
    });
    logBody.scrollTop = logBody.scrollHeight;
  }

  async function runDemo() {
    runBtn.disabled = true;
    runBtn.textContent = "Running...";
    try {
      await api(`/api/${mode === "obo" ? "on-behalf-of" : "service-principal"}/run`, { method: "POST" });
      await refreshLogs();
      await loadContainers();
      await loadTables();
    } catch (err) {
      await refreshLogs();
      alert(`Run failed: ${err.message}`);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "▶ Run Demo";
    }
  }

  async function loadContainers() {
    const containers = await api(`/api/${mode}/storage/containers`);
    containerSelect.innerHTML = `<option value="">— Select a container —</option>`;
    containers.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      containerSelect.appendChild(opt);
    });
    storageItems.innerHTML = `<tr><td colspan="3" class="text-muted text-center"><em>Select a container</em></td></tr>`;
    breadcrumb.innerHTML = "";
    currentPrefix = null;
  }

  function displayName(fullName) {
    const trimmed = fullName.replace(/\/$/, "");
    const i = trimmed.lastIndexOf("/");
    return i >= 0 ? trimmed.slice(i + 1) : trimmed;
  }

  function formatSize(bytes) {
    if (bytes === null || bytes === undefined) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderBreadcrumb(prefix) {
    breadcrumb.innerHTML = "";
    const root = document.createElement("li");
    root.className = "breadcrumb-item";
    root.innerHTML = `<a href="#">🏠 Root</a>`;
    root.querySelector("a").addEventListener("click", (e) => {
      e.preventDefault();
      navigateTo(null);
    });
    breadcrumb.appendChild(root);

    if (!prefix) return;
    const parts = prefix.replace(/\/$/, "").split("/");
    parts.forEach((part, idx) => {
      const item = document.createElement("li");
      item.className = "breadcrumb-item";
      const p = `${parts.slice(0, idx + 1).join("/")}/`;
      item.innerHTML = `<a href="#">${escapeHtml(part)}</a>`;
      item.querySelector("a").addEventListener("click", (e) => {
        e.preventDefault();
        navigateTo(p);
      });
      breadcrumb.appendChild(item);
    });
  }

  async function loadBlobs(container, prefix = null) {
    const query = new URLSearchParams({ container });
    if (prefix) query.set("prefix", prefix);
    const items = await api(`/api/${mode}/storage/blobs?${query.toString()}`);
    storageItems.innerHTML = "";
    if (!items.length) {
      storageItems.innerHTML = `<tr><td colspan="3" class="text-muted text-center"><em>No items</em></td></tr>`;
      return;
    }

    items.forEach((item) => {
      const tr = document.createElement("tr");
      const nameCell = document.createElement("td");
      if (item.isFolder) {
        const a = document.createElement("a");
        a.href = "#";
        a.textContent = `📁 ${displayName(item.name)}`;
        a.addEventListener("click", (e) => {
          e.preventDefault();
          navigateTo(item.name);
        });
        nameCell.appendChild(a);
      } else {
        nameCell.textContent = `📄 ${displayName(item.name)}`;
      }
      const sizeCell = document.createElement("td");
      sizeCell.textContent = item.isFolder ? "—" : formatSize(item.size);
      const modCell = document.createElement("td");
      modCell.textContent = item.lastModified ? new Date(item.lastModified).toLocaleString() : "—";
      tr.appendChild(nameCell);
      tr.appendChild(sizeCell);
      tr.appendChild(modCell);
      storageItems.appendChild(tr);
    });
  }

  async function navigateTo(prefix) {
    currentPrefix = prefix;
    renderBreadcrumb(currentPrefix);
    const container = containerSelect.value;
    if (!container) return;
    await loadBlobs(container, currentPrefix);
  }

  async function loadTables() {
    tables = await api(`/api/${mode}/sql/tables`);
    tableSelect.innerHTML = `<option value="">— Select a table —</option>`;
    tables.forEach((t, idx) => {
      const opt = document.createElement("option");
      opt.value = String(idx);
      opt.textContent = t.fullName;
      tableSelect.appendChild(opt);
    });
    queryBtn.disabled = true;
    sqlResults.innerHTML = "";
  }

  async function runQuery() {
    const selected = tableSelect.value;
    if (selected === "") return;
    const table = tables[Number(selected)];
    const topN = Number(topNInput.value || 10);

    const result = await api(`/api/${mode}/sql/query`, {
      method: "POST",
      body: JSON.stringify({ schema: table.schema, tableName: table.tableName, topN }),
    });

    if (!result.columns || !result.columns.length) {
      sqlResults.innerHTML = `<div class="text-muted"><em>Query returned no results.</em></div>`;
      return;
    }

    const head = `<thead class="table-dark"><tr>${result.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>`;
    const body = `<tbody>${result.rows
      .map((r) => `<tr>${result.columns.map((c) => `<td>${escapeHtml(r[c] === null || r[c] === undefined ? "<NULL>" : String(r[c]))}</td>`).join("")}</tr>`)
      .join("")}</tbody>`;
    sqlResults.innerHTML = `<table class="table table-sm table-striped table-hover mb-0">${head}${body}</table>`;
    await refreshLogs();
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  runBtn?.addEventListener("click", runDemo);
  clearBtn?.addEventListener("click", async () => {
    await api(`/api/logs?mode=${mode}`, { method: "DELETE" });
    await refreshLogs();
  });

  containerSelect?.addEventListener("change", async () => {
    currentPrefix = null;
    renderBreadcrumb(null);
    if (!containerSelect.value) return;
    await loadBlobs(containerSelect.value, null);
    await refreshLogs();
  });

  tableSelect?.addEventListener("change", () => {
    queryBtn.disabled = tableSelect.value === "";
  });

  queryBtn?.addEventListener("click", async () => {
    try {
      await runQuery();
    } catch (err) {
      alert(`Query failed: ${err.message}`);
    }
  });

  refreshLogs().catch(() => {});
})();
