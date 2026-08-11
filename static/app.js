"use strict";

/* Kvittokoll — arbetslistan.
   Vanilla JS, inget byggsteg. Servern skickar hela listan; filtrering,
   sortering och gruppering sker här eftersom en månads transaktioner är
   några hundra rader, inte några hundra tusen. */

const state = {
  transactions: [],
  sources: [],
  profiles: [],
  matchModes: [],
  settings: {},
  selected: new Set(),
  openNotes: new Set(),
  staged: null,
  sourceTarget: null,
};

const el = (id) => document.getElementById(id);

const MONTHS = [
  "januari", "februari", "mars", "april", "maj", "juni",
  "juli", "augusti", "september", "oktober", "november", "december",
];

const STATUS_LABEL = {
  missing: "Saknar verifikat",
  has_receipt: "Har verifikat",
  sent: "Skickat",
  not_required: "Inget krav",
};

/* ---------- hjälpare ---------- */

function formatAmount(value) {
  return value.toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function monthLabel(key) {
  const [year, month] = key.split("-");
  return `${MONTHS[Number(month) - 1]} ${year}`;
}

async function request(url, options) {
  const response = await fetch(url, options);
  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = { error: "Servern svarade oväntat." };
  }
  if (!response.ok) throw new Error(payload.error || `Fel ${response.status}`);
  return payload;
}

function sourceById(id) {
  return state.sources.find((source) => source.id === id) || null;
}

/* ---------- inläsning ---------- */

async function load() {
  const data = await request("/api/state");
  state.settings = data.settings || {};
  state.sources = data.sources || [];
  state.profiles = data.profiles || [];
  state.matchModes = data.match_modes || [];
  state.transactions = data.transactions || [];
  if (!el("show-not-required").dataset.touched) {
    el("show-not-required").checked = state.settings.hide_not_required === false;
  }
  fillSourceFilter();
  fillProfiles();
  render();
}

function fillSourceFilter() {
  const select = el("filter-source");
  const current = select.value;
  select.innerHTML =
    '<option value="">Alla källor</option><option value="__none__">Utan källa</option>' +
    state.sources
      .map((source) => `<option value="${source.id}">${escapeHtml(source.name)}</option>`)
      .join("");
  select.value = current;
}

function fillProfiles() {
  const select = el("import-profile");
  select.innerHTML =
    '<option value="">Välj automatiskt</option>' +
    state.profiles
      .map((profile) => `<option value="${profile.id}">${escapeHtml(profile.name)}</option>`)
      .join("");
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

/* ---------- filter och sortering ---------- */

function visibleTransactions() {
  const query = el("filter-text").value.trim().toLowerCase();
  const status = el("filter-status").value;
  const source = el("filter-source").value;
  const from = el("filter-from").value;
  const to = el("filter-to").value;
  const showNotRequired = el("show-not-required").checked;

  let rows = state.transactions.filter((row) => {
    if (!showNotRequired && !row.requires_receipt && status !== "not_required") return false;
    if (status && row.status !== status) return false;
    if (source === "__none__" && row.source_id) return false;
    if (source && source !== "__none__" && row.source_id !== source) return false;
    if (from && row.date < from) return false;
    if (to && row.date > to) return false;
    if (query) {
      const name = sourceById(row.source_id);
      const haystack = [
        row.description, row.note, row.transaction_type,
        name ? name.name : "", name ? name.company : "",
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });

  const [key, direction] = el("sort").value.split("-");
  const sign = direction === "asc" ? 1 : -1;
  rows = rows.slice().sort((a, b) => {
    if (key === "amount") return (a.amount - b.amount) * sign;
    if (a.date !== b.date) return a.date < b.date ? -sign : sign;
    return a.id < b.id ? -sign : sign;
  });
  return rows;
}

/* ---------- rendering ---------- */

function render() {
  const rows = visibleTransactions();
  renderSummary(rows);
  renderBulk();

  const list = el("list");
  list.innerHTML = "";

  if (!state.transactions.length) {
    el("empty").hidden = false;
    el("empty").textContent =
      "Inga transaktioner ännu. Importera en export från internetbanken för att börja.";
    return;
  }
  if (!rows.length) {
    el("empty").hidden = false;
    el("empty").textContent = "Inga rader matchar filtret.";
    return;
  }
  el("empty").hidden = true;

  const groups = new Map();
  for (const row of rows) {
    const key = row.date.slice(0, 7);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }

  for (const [key, groupRows] of groups) {
    list.appendChild(renderMonth(key, groupRows));
  }
}

function renderSummary(rows) {
  const summary = el("summary");
  if (!state.transactions.length) {
    summary.hidden = true;
    return;
  }
  summary.hidden = false;

  const requiring = rows.filter((row) => row.requires_receipt);
  const missing = requiring.filter((row) => row.status === "missing").length;
  const hasReceipt = requiring.filter((row) => row.status === "has_receipt").length;
  const sent = requiring.filter((row) => row.status === "sent").length;
  const period = describePeriod(rows);

  summary.innerHTML = `
    <span class="headline">Av <span class="count">${rows.length}</span> transaktioner${period}
      saknar <span class="count missing">${missing}</span> verifikat.</span>
    <span class="muted"><span class="num">${hasReceipt}</span> har verifikat men är inte
      skickade · <span class="num">${sent}</span> skickade ·
      <span class="num">${rows.length - requiring.length}</span> utan verifikatkrav</span>`;
}

function describePeriod(rows) {
  if (!rows.length) return "";
  const months = new Set(rows.map((row) => row.date.slice(0, 7)));
  if (months.size === 1) return ` i ${monthLabel(rows[0].date.slice(0, 7))}`;
  return "";
}

function renderMonth(key, rows) {
  const section = document.createElement("section");
  section.className = "month";

  const missing = rows.filter((row) => row.status === "missing").length;
  const total = rows.reduce((sum, row) => sum + row.amount, 0);

  const head = document.createElement("h2");
  head.className = "month-head";
  head.innerHTML = `${monthLabel(key)}
    <span class="muted"><span class="num">${rows.length}</span> rader ·
      netto <span class="num">${formatAmount(total)}</span> kr${
      missing
        ? ` · <strong class="badge missing"><span class="num">${missing}</span> saknar verifikat</strong>`
        : ""
    }</span>`;
  section.appendChild(head);

  const table = document.createElement("table");
  table.innerHTML = `
    <thead><tr>
      <th class="select"></th>
      <th>Datum</th>
      <th>Text</th>
      <th class="amount">Belopp</th>
      <th>Källa</th>
      <th>Verifikat</th>
      <th>Skickat</th>
      <th>Åtgärder</th>
    </tr></thead>`;
  const body = document.createElement("tbody");
  for (const row of rows) {
    body.appendChild(renderRow(row));
    if (state.openNotes.has(row.id)) body.appendChild(renderNoteRow(row));
  }
  table.appendChild(body);
  section.appendChild(table);
  return section;
}

function renderRow(row) {
  const source = sourceById(row.source_id);
  const tr = document.createElement("tr");
  tr.dataset.id = row.id;
  if (!row.requires_receipt) tr.classList.add("not-required");

  const sourceCell = source
    ? `<span class="source-name">${escapeHtml(source.name)}</span>` +
      (source.receipt_url
        ? `<a href="${escapeHtml(source.receipt_url)}" target="_blank" rel="noopener"
             title="${escapeHtml(source.note || "")}">Öppna källa ↗</a>`
        : "")
    : row.ambiguous_sources && row.ambiguous_sources.length
      ? '<span class="badge ambiguous">Tvetydig — välj källa</span>'
      : '<span class="source-none">Ingen källa</span>';

  tr.innerHTML = `
    <td class="select"><input type="checkbox" data-select="${escapeHtml(row.id)}"
      ${state.selected.has(row.id) ? "checked" : ""}></td>
    <td class="date">${row.date}</td>
    <td class="text">
      <span class="text-main">${escapeHtml(row.description) || "<em>utan text</em>"}</span>
      <span class="text-meta">${escapeHtml(row.transaction_type)}${
        row.note ? ` · ${escapeHtml(row.note)}` : ""
      }</span>
    </td>
    <td class="amount ${row.amount < 0 ? "negative" : ""}">${formatAmount(row.amount)}</td>
    <td><div class="source-cell">${sourceCell}
      <button class="tiny" data-action="source">Koppla…</button></div></td>
    <td><span class="badge ${row.status}">${STATUS_LABEL[row.status]}</span></td>
    <td class="date">${row.sent_at ? row.sent_at.slice(0, 10) : "—"}</td>
    <td class="actions">
      <button class="tiny" data-action="toggle-required">${
        row.requires_receipt ? "Kräver inget" : "Kräver verifikat"
      }</button>
      <button class="tiny" data-action="note">${row.note ? "Anteckning ✱" : "Anteckning"}</button>
    </td>`;
  return tr;
}

function renderNoteRow(row) {
  const tr = document.createElement("tr");
  tr.className = "note-row";
  tr.dataset.id = row.id;
  tr.innerHTML = `<td></td><td colspan="7">
    <textarea data-note="${escapeHtml(row.id)}"
      placeholder="Anteckning om raden">${escapeHtml(row.note)}</textarea>
    <div class="actions"><button class="tiny primary" data-action="note-save">Spara</button>
      <button class="tiny link" data-action="note-close">Stäng</button></div></td>`;
  return tr;
}

function renderBulk() {
  const bulk = el("bulk");
  bulk.hidden = state.selected.size === 0;
  el("bulk-count").innerHTML = `<span class="num">${state.selected.size}</span> rader markerade`;
}

/* ---------- åtgärder ---------- */

async function patchTransaction(id, changes) {
  const result = await request(`/api/transactions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  });
  const index = state.transactions.findIndex((row) => row.id === id);
  if (index >= 0) state.transactions[index] = result.transaction;
  return result;
}

el("list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const id = button.closest("tr").dataset.id;
  const row = state.transactions.find((item) => item.id === id);
  if (!row) return;

  try {
    if (button.dataset.action === "toggle-required") {
      const next = !row.requires_receipt;
      const changes = { requires_receipt: next };
      if (row.source_id) {
        const source = sourceById(row.source_id);
        changes.apply_to_source = window.confirm(
          `Ska "${source ? source.name : row.source_id}" få detta som standard för nya rader?`
        );
      }
      await patchTransaction(id, changes);
      if (changes.apply_to_source) await load();
      else render();
    } else if (button.dataset.action === "note") {
      if (state.openNotes.has(id)) state.openNotes.delete(id);
      else state.openNotes.add(id);
      render();
    } else if (button.dataset.action === "note-close") {
      state.openNotes.delete(id);
      render();
    } else if (button.dataset.action === "note-save") {
      const textarea = document.querySelector(`textarea[data-note="${CSS.escape(id)}"]`);
      await patchTransaction(id, { note: textarea.value });
      state.openNotes.delete(id);
      render();
    } else if (button.dataset.action === "source") {
      openSourceDialog(row);
    }
  } catch (error) {
    window.alert(error.message);
  }
});

el("list").addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-select]");
  if (!checkbox) return;
  if (checkbox.checked) state.selected.add(checkbox.dataset.select);
  else state.selected.delete(checkbox.dataset.select);
  renderBulk();
});

el("bulk").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-bulk]");
  if (!button) return;
  const action = button.dataset.bulk;
  if (action === "clear") {
    state.selected.clear();
    render();
    return;
  }
  try {
    const result = await request("/api/transactions/bulk", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ids: [...state.selected],
        changes: { requires_receipt: action === "required" },
      }),
    });
    for (const updated of result.updated) {
      const index = state.transactions.findIndex((row) => row.id === updated.id);
      if (index >= 0) state.transactions[index] = updated;
    }
    state.selected.clear();
    render();
  } catch (error) {
    window.alert(error.message);
  }
});

/* ---------- källdialog ---------- */

function openSourceDialog(row) {
  state.sourceTarget = row;
  el("source-context").innerHTML =
    `<span class="num">${row.date}</span> · <span class="num">${formatAmount(row.amount)}</span> kr` +
    ` · ${escapeHtml(row.description)}`;
  el("source-select").innerHTML =
    '<option value="">Ingen källa</option>' +
    state.sources
      .map((source) => `<option value="${source.id}">${escapeHtml(source.name)}</option>`)
      .join("") +
    '<option value="__new__">Ny källa…</option>';
  el("source-select").value = row.source_id || "";
  el("source-name").value = row.description;
  el("source-company").value = "";
  el("source-url").value = "";
  el("source-error").hidden = true;

  el("source-pattern-mode").innerHTML = state.matchModes
    .map((mode) => `<option value="${mode.id}">${escapeHtml(mode.label)}</option>`)
    .join("");
  el("source-pattern").value = row.description;
  el("source-pattern-result").textContent = "";
  el("source-pattern-result").className = "muted small";

  toggleNewSourceFields();
  togglePatternFields();
  testPattern();
  el("source-dialog").showModal();
}

function toggleNewSourceFields() {
  el("source-new").hidden = el("source-select").value !== "__new__";
}

function togglePatternFields() {
  el("source-pattern-fields").hidden = !el("source-learn").checked;
}

/* Provar mönstret på servern så att normaliseringen är densamma som vid
   riktig matchning. Att välja läge blint är svårt; det här visar utfallet.

   Biljetten finns för att svaren kan komma i annan ordning än frågorna. Utan
   den kan resultatet för "HYR" skriva över resultatet för "HYRA" och visa fel
   antal träffar för det mönster som står i fältet. */
let patternTimer = null;
let patternTicket = 0;

function testPattern() {
  const ticket = ++patternTicket;
  if (!el("source-learn").checked || !state.sourceTarget) return;
  clearTimeout(patternTimer);
  patternTimer = setTimeout(async () => {
    const result = el("source-pattern-result");
    const pattern = el("source-pattern").value.trim();
    if (!pattern) {
      result.textContent = "";
      result.className = "muted small";
      return;
    }
    try {
      const outcome = await request("/api/sources/test-pattern", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pattern,
          mode: el("source-pattern-mode").value,
          description: state.sourceTarget.description,
        }),
      });
      if (ticket !== patternTicket) return;
      const others = outcome.total - (outcome.matches ? 1 : 0);
      result.className = `small ${outcome.matches ? "hit" : "miss"}`;
      result.textContent = outcome.matches
        ? `Träffar den här raden${others > 0 ? ` och ${others} till` : " — och ingen annan"}.`
        : `Träffar inte den här raden${outcome.total ? ` (men ${outcome.total} andra)` : ""}.`;
    } catch (error) {
      if (ticket !== patternTicket) return;
      result.className = "small miss";
      result.textContent = error.message;
    }
  }, 220);
}

el("source-select").addEventListener("change", toggleNewSourceFields);
el("source-learn").addEventListener("change", () => {
  togglePatternFields();
  testPattern();
});
el("source-pattern").addEventListener("input", testPattern);
el("source-pattern-mode").addEventListener("change", testPattern);

el("source-save").addEventListener("click", async (event) => {
  event.preventDefault();
  const row = state.sourceTarget;
  if (!row) return;
  try {
    let sourceId = el("source-select").value;
    if (sourceId === "__new__") {
      const created = await request("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: el("source-name").value.trim(),
          company: el("source-company").value.trim(),
          receipt_url: el("source-url").value.trim(),
        }),
      });
      sourceId = created.source.id;
    }
    await patchTransaction(row.id, {
      source_id: sourceId || null,
      add_match_pattern: el("source-learn").checked && Boolean(sourceId),
      match_pattern: el("source-pattern").value.trim(),
      match_pattern_mode: el("source-pattern-mode").value,
    });
    el("source-dialog").close();
    await load();
  } catch (error) {
    el("source-error").hidden = false;
    el("source-error").textContent = error.message;
  }
});

/* ---------- import ---------- */

el("import-open").addEventListener("click", () => {
  state.staged = null;
  el("import-step-file").hidden = false;
  el("import-step-preview").hidden = true;
  el("import-preview").hidden = false;
  el("import-confirm").hidden = true;
  el("import-error").hidden = true;
  el("import-file").value = "";
  el("import-dialog").showModal();
});

el("import-cancel").addEventListener("click", () => {
  if (state.staged) {
    request("/api/import/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: state.staged.token }),
    }).catch(() => {});
    state.staged = null;
  }
});

el("import-preview").addEventListener("click", async (event) => {
  event.preventDefault();
  const file = el("import-file").files[0];
  if (!file) {
    showImportError("Välj en fil först.");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  const profile = el("import-profile").value;
  if (profile) form.append("profile_id", profile);

  try {
    const preview = await request("/api/import/preview", { method: "POST", body: form });
    state.staged = preview;
    renderPreview(preview);
  } catch (error) {
    showImportError(error.message);
  }
});

el("import-confirm").addEventListener("click", async (event) => {
  event.preventDefault();
  if (!state.staged) return;
  try {
    const result = await request("/api/import/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: state.staged.token }),
    });
    state.staged = null;
    el("import-dialog").close();
    await load();
    window.alert(`${result.added} nya transaktioner importerade.`);
  } catch (error) {
    showImportError(error.message);
  }
});

function showImportError(message) {
  el("import-error").hidden = false;
  el("import-error").textContent = message;
}

function renderPreview(preview) {
  const summary = preview.summary;
  el("import-error").hidden = true;
  el("import-step-file").hidden = true;
  el("import-step-preview").hidden = false;
  el("import-preview").hidden = true;
  el("import-confirm").hidden = false;
  el("import-confirm").disabled = summary.new === 0;

  el("import-summary").innerHTML = `
    <div><b>${summary.new}</b><span>nya</span></div>
    <div><b>${summary.known}</b><span>redan kända</span></div>
    <div><b>${summary.failed}</b><span>ej tolkbara</span></div>
    <div><b>${summary.matched}</b><span>kopplade till källa</span></div>
    ${summary.ambiguous ? `<div><b>${summary.ambiguous}</b><span>tvetydig källa</span></div>` : ""}`;

  const format = preview.format === "camt053" ? "camt.053" : `CSV (${preview.profile_id || "?"}, ${preview.encoding})`;
  const months = summary.months.length ? summary.months.map(monthLabel).join(", ") : "—";

  el("import-sample").innerHTML = `<p class="muted small">${escapeHtml(preview.filename)} ·
    ${escapeHtml(format)} · perioder: ${escapeHtml(months)}</p>`;

  el("import-errors").innerHTML = preview.errors.length
    ? `<p class="error small">${preview.errors.length} rader kunde inte tolkas. Bekräftar du
         importen hoppas de över — inget skrivs för dem.</p>
       <div class="error-list"><table><tbody>${preview.errors
         .map((error) => `<tr><td>rad <span class="num">${error.line}</span></td><td>${escapeHtml(error.reason)}</td>
           <td class="muted">${escapeHtml(error.raw)}</td></tr>`)
         .join("")}</tbody></table></div>`
    : "";
}

/* ---------- filter-lyssnare ---------- */

for (const id of ["filter-text", "filter-status", "filter-source", "filter-from", "filter-to", "sort"]) {
  el(id).addEventListener("input", render);
  el(id).addEventListener("change", render);
}

el("show-not-required").addEventListener("change", (event) => {
  event.target.dataset.touched = "1";
  render();
});

el("filter-reset").addEventListener("click", (event) => {
  event.preventDefault();
  for (const id of ["filter-text", "filter-status", "filter-source", "filter-from", "filter-to"]) {
    el(id).value = "";
  }
  el("sort").value = "date-desc";
  render();
});

load().catch((error) => {
  el("empty").hidden = false;
  el("empty").textContent = `Kunde inte läsa data: ${error.message}`;
});
