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
  paths: {},
  expandedMonths: new Set(),
  settings: {},
  selected: new Set(),
  staged: null,
  sourceTarget: null,
  view: "list",
  receiptTarget: null,
  receiptShown: null,
  sendTarget: null,
  sendPreview: null,
  emailCreated: false,
  flashTimer: null,
  editingSource: null,
  sourceDraft: {},
};

const el = (id) => document.getElementById(id);

const MONTHS = [
  "januari", "februari", "mars", "april", "maj", "juni",
  "juli", "augusti", "september", "oktober", "november", "december",
];

const ICON_HIDE = `<svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"
  fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
  <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z"/>
  <circle cx="10" cy="10" r="2.3"/><path d="M3.5 16.5 16.5 3.5"/></svg>`;

const ICON_SHOW = `<svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true"
  fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
  <path d="M2 10s3-5 8-5 8 5 8 5-3 5-8 5-8-5-8-5z"/>
  <circle cx="10" cy="10" r="2.3"/></svg>`;

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
  state.paths = data.paths || {};
  state.transactions = data.transactions || [];
  // hide_not_required är utgångsläget: är den av börjar alla månader utfällda.
  if (state.settings.hide_not_required === false && !state.expandedMonths.size) {
    for (const row of state.transactions) state.expandedMonths.add(row.date.slice(0, 7));
  }
  fillSourceFilter();
  fillProfiles();
  render();
  if (state.view === "sources") renderSources();
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

/* Rader som klarar allt utom statusfiltret. Hinkarnas räknare bygger på den
   här mängden, så att siffran visar vad ett klick faktiskt skulle ge. */
function baseTransactions() {
  const query = el("filter-text").value.trim().toLowerCase();
  const source = el("filter-source").value;
  const from = el("filter-from").value;
  const to = el("filter-to").value;
  return state.transactions.filter((row) => {
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
}

function activeBuckets() {
  return new Set(
    [...document.querySelectorAll("input[data-bucket]:checked")].map((i) => i.dataset.bucket)
  );
}

function visibleTransactions() {
  const active = activeBuckets();
  const rows = baseTransactions().filter(
    (row) => active.size === 0 || active.has(row.status)
  );

  const [key, direction] = el("sort").value.split("-");
  const sign = direction === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    if (key === "amount") return (a.amount - b.amount) * sign;
    if (a.date !== b.date) return a.date < b.date ? -sign : sign;
    return a.id < b.id ? -sign : sign;
  });
}

/* ---------- rendering ---------- */

function render() {
  const rows = visibleTransactions();
  renderBuckets();
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

/* Dolda rader visas per månad. Man arbetar med en månad i taget, och en
   global växlare tvingar fram allt eller inget. */
function monthIsExpanded(key) {
  // Har man bett om dolda rader ska de visas, oavsett månadsväxlarna.
  if (activeBuckets().has("not_required")) return true;
  return state.expandedMonths.has(key);
}

const BUCKETS = [
  { status: "missing", label: "Saknar verifikat" },
  { status: "has_receipt", label: "Har verifikat" },
  { status: "sent", label: "Skickat" },
  { status: "not_required", label: "Dolda" },
];

function renderBuckets() {
  const active = activeBuckets();
  const counts = {};
  for (const row of baseTransactions()) {
    counts[row.status] = (counts[row.status] || 0) + 1;
  }
  el("buckets").innerHTML = BUCKETS.map((bucket) => {
    const count = counts[bucket.status] || 0;
    const on = active.has(bucket.status);
    return `<label class="bucket ${bucket.status}${on ? " on" : ""}${count ? "" : " zero"}">
      <input type="checkbox" data-bucket="${bucket.status}"${on ? " checked" : ""}>
      <span class="count">${count}</span>
      <span class="label">${escapeHtml(bucket.label)}</span>
    </label>`;
  }).join("");
}

el("buckets").addEventListener("change", render);

function renderMonth(key, allRows) {
  const section = document.createElement("section");
  section.className = "month";

  const hiddenCount = allRows.filter((row) => !row.requires_receipt).length;
  const expanded = monthIsExpanded(key);
  const rows = expanded ? allRows : allRows.filter((row) => row.requires_receipt);

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
    }</span>
    ${hiddenCount
      ? `<button class="link-quiet month-toggle" data-month="${key}">${
          expanded ? "Dölj igen" : "Visa dolda"
        } (<span class="num">${hiddenCount}</span>)</button>`
      : ""}`;
  section.appendChild(head);

  if (!rows.length) return section;

  const table = document.createElement("table");
  // Varje månad är en egen tabell. Utan låsta bredder räknar de ut sina
  // kolumner var för sig och slutar linjera med varandra.
  table.innerHTML = `
    <colgroup>
      <col class="c-select"><col class="c-date"><col class="c-text"><col class="c-amount">
      <col class="c-receipt"><col class="c-sent"><col class="c-actions">
    </colgroup>
    <thead><tr>
      <th class="select"></th>
      <th>Datum</th>
      <th>Text</th>
      <th class="amount">Belopp</th>
      <th>Verifikat</th>
      <th>Skickat</th>
      <th class="row-actions"><span class="sr-only">Åtgärder</span></th>
    </tr></thead>`;
  const body = document.createElement("tbody");
  for (const row of rows) {
    body.appendChild(renderRow(row));
  }
  table.appendChild(body);
  section.appendChild(table);
  return section;
}

/* Verifikatkolumnen bär hela verifikatet: en knapp när det saknas, annars en
   klickbar badge. Båda öppnar samma modal, där filen också kan visas, bytas
   och tas bort. Aldrig två saker i cellen. */
function receiptCell(row) {
  if (!row.requires_receipt) {
    return `<span class="badge not_required">${STATUS_LABEL.not_required}</span>`;
  }
  const files = row.receipts || [];
  if (!files.length) {
    return `<button class="tiny" data-action="receipt">Ladda upp</button>`;
  }
  const label = files.length > 1
    ? `<span class="num">${files.length}</span> verifikat`
    : STATUS_LABEL[row.status];
  return `<button class="badge ${row.status}" data-action="receipt"
    title="${escapeHtml(files.map((r) => r.stored_filename).join(", "))}">${label}</button>`;
}

/* Skickat-kolumnen bär utskicket. Saknas verifikat går det inte att skicka,
   och det ska stå — inte visas som en avstängd knapp utan förklaring. */
function sentCell(row) {
  if (!row.requires_receipt) return "—";
  if (row.sent_at) {
    return `<button class="badge sent" data-action="send"
      title="Skickat ${escapeHtml(row.sent_at)}"><span class="num">${
        row.sent_at.slice(0, 10)}</span></button>`;
  }
  if (!(row.receipts || []).length) return `<span class="cell-hint">Väntar på verifikat</span>`;
  return `<button class="tiny" data-action="send">Skicka</button>`;
}

function renderRow(row) {
  const source = sourceById(row.source_id);
  const tr = document.createElement("tr");
  tr.dataset.id = row.id;
  if (!row.requires_receipt) tr.classList.add("not-required");

  // Alltid exakt en sak under datumet: en pill när källan finns, annars en
  // länk som kopplar. Aldrig båda.
  const sourceCell = source
    ? `<button class="pill" data-action="source"
         title="${escapeHtml(source.company || source.name)} — klicka för att koppla om"
         >${escapeHtml(source.name)}</button>`
    : row.ambiguous_sources && row.ambiguous_sources.length
      ? `<button class="pill ambiguous" data-action="source"
           title="Flera källor matchar lika starkt">Tvetydig källa</button>`
      : `<button class="link-quiet" data-action="source">Koppla källa</button>`;

  tr.innerHTML = `
    <td class="select"><input type="checkbox" data-select="${escapeHtml(row.id)}"
      ${state.selected.has(row.id) ? "checked" : ""}></td>
    <td class="date">
      <span class="cell-main num">${row.date}</span>
      <span class="cell-meta">${sourceCell}</span>
    </td>
    <td class="text">
      <span class="cell-main">${escapeHtml(row.description) || "<em>utan text</em>"}</span>
      <span class="cell-meta">${escapeHtml(row.transaction_type)}${
        row.note ? ` · ${escapeHtml(row.note)}` : ""
      }</span>
    </td>
    <td class="amount ${row.amount < 0 ? "negative" : ""}">${formatAmount(row.amount)}</td>
    <td>${receiptCell(row)}</td>
    <td class="date">${sentCell(row)}</td>
    <td class="row-actions">
      <button class="icon" data-action="toggle-required"
        title="${row.requires_receipt
          ? "Dölj raden — den kräver inget verifikat"
          : "Visa raden — den kräver verifikat"}"
        aria-label="${row.requires_receipt ? "Dölj raden" : "Visa raden"}"
      >${row.requires_receipt ? ICON_HIDE : ICON_SHOW}</button>
    </td>`;
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
    } else if (button.dataset.action === "source") {
      await openSourceDialog(row);
    } else if (button.dataset.action === "receipt") {
      openReceiptDialog(row);
    } else if (button.dataset.action === "send") {
      await openSendDialog(row);
    }
  } catch (error) {
    window.alert(error.message);
  }
});

el("list").addEventListener("click", (event) => {
  const toggle = event.target.closest("button.month-toggle");
  if (!toggle) return;
  const key = toggle.dataset.month;
  if (state.expandedMonths.has(key)) state.expandedMonths.delete(key);
  else state.expandedMonths.add(key);
  render();
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

/* ---------- vyväxling ---------- */

function showView(name) {
  state.view = name;
  el("view-list").hidden = name !== "list";
  el("view-sources").hidden = name !== "sources";
  el("view-settings").hidden = name !== "settings";
  for (const button of document.querySelectorAll("button.nav")) {
    const active = button.dataset.view === name;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (name === "sources") renderSources();
  if (name === "settings") renderSettings();
}

for (const button of document.querySelectorAll("button.nav")) {
  button.addEventListener("click", () => showView(button.dataset.view));
}

/* ---------- källvyn ---------- */

function renderSources() {
  const list = el("sources-list");
  if (!state.sources.length) {
    list.innerHTML = `<p class="empty">Inga källor ännu. En källa skapas enklast
      från en transaktionsrad — klicka <em>Koppla källa</em> i arbetslistan — eller
      med <em>Ny källa</em> här.</p>`;
    return;
  }
  list.innerHTML = state.sources.map(renderSourceCard).join("");
}

function renderSourceCard(source) {
  const editing = state.editingSource === source.id;
  if (editing) return renderSourceEditor(source);

  const patterns = (source.match_patterns || []).map((raw) => {
    const pattern = typeof raw === "string" ? { pattern: raw, mode: "contains" } : raw;
    const label = (state.matchModes.find((m) => m.id === pattern.mode) || {}).label || pattern.mode;
    return `<span class="pattern"><span class="pattern-mode">${escapeHtml(label)}</span>
      ${escapeHtml(pattern.pattern)}</span>`;
  });

  return `<article class="source-card" data-source="${escapeHtml(source.id)}">
    <div class="source-head">
      <div>
        <h3>${escapeHtml(source.name)}</h3>
        <p class="muted small">${escapeHtml(source.company) || "—"} ·
          <span class="num">${source.transaction_count}</span> kopplade transaktioner ·
          ${source.receipt_type === "physical" ? "fotas/scannas" : "digitalt"} ·
          ${source.requires_receipt ? "kräver verifikat" : "kräver inget verifikat"}
          ${source.auto_send_configured ? " · mejlas automatiskt" : ""}</p>
      </div>
      <div class="actions">
        <button class="tiny" data-source-action="edit">Redigera</button>
      </div>
    </div>
    <div class="source-links">
      ${source.receipt_url
        ? `<a href="${escapeHtml(source.receipt_url)}" target="_blank" rel="noopener">Hämta verifikat ↗</a>`
        : `<span class="muted small">Ingen länk till verifikat</span>`}
      ${source.settings_url
        ? `<a href="${escapeHtml(source.settings_url)}" target="_blank" rel="noopener">Ställ in mejladress ↗</a>`
        : ""}
    </div>
    ${source.note ? `<p class="source-note">${escapeHtml(source.note)}</p>` : ""}
    <div class="patterns">${patterns.join("") || '<span class="muted small">Inga mönster — matchar inget automatiskt</span>'}</div>
  </article>`;
}

function renderSourceEditor(source) {
  const patterns = (source.match_patterns || []).map((raw) =>
    typeof raw === "string" ? { pattern: raw, mode: "contains" } : raw
  );
  const modeOptions = (selected) =>
    state.matchModes
      .map((m) => `<option value="${m.id}"${m.id === selected ? " selected" : ""}>${escapeHtml(m.label)}</option>`)
      .join("");

  return `<article class="source-card editing" data-source="${escapeHtml(source.id)}">
    <div class="grid-two">
      <label class="field block">Namn<input type="text" data-field="name" value="${escapeHtml(source.name)}"></label>
      <label class="field block">Bolag<input type="text" data-field="company" value="${escapeHtml(source.company)}"></label>
      <label class="field block">Länk till verifikat
        <input type="url" data-field="receipt_url" value="${escapeHtml(source.receipt_url)}"
               placeholder="https://…"></label>
      <label class="field block">Länk till mejlinställningar
        <input type="url" data-field="settings_url" value="${escapeHtml(source.settings_url)}"
               placeholder="https://…"></label>
      <label class="field block">Verifikattyp
        <select data-field="receipt_type">
          <option value="digital"${source.receipt_type !== "physical" ? " selected" : ""}>digitalt — hämtas via länk</option>
          <option value="physical"${source.receipt_type === "physical" ? " selected" : ""}>fysiskt — fotas eller scannas</option>
        </select></label>
      <label class="field block">Filnamnstagg
        <input type="text" data-field="filename_tag" value="${escapeHtml(source.filename_tag)}"></label>
    </div>
    <label class="field block">Anteckning — vägen till verifikatet hos leverantören
      <textarea data-field="note" rows="2">${escapeHtml(source.note)}</textarea></label>
    <div class="toggles">
      <label class="toggle"><input type="checkbox" data-field="requires_receipt"
        ${source.requires_receipt ? "checked" : ""}> Nya rader kräver verifikat</label>
      <label class="toggle"><input type="checkbox" data-field="auto_send_configured"
        ${source.auto_send_configured ? "checked" : ""}> Leverantören mejlar redan till bokföringen</label>
    </div>

    <h4>Matchningsmönster</h4>
    <div class="pattern-editor">
      ${patterns.map((pattern, index) => `
        <div class="pattern-row" data-index="${index}">
          <select data-pattern-mode>${modeOptions(pattern.mode)}</select>
          <input type="text" data-pattern-text value="${escapeHtml(pattern.pattern)}">
          <button class="tiny" data-source-action="drop-pattern" title="Ta bort mönstret">✕</button>
        </div>`).join("")}
    </div>
    <button class="tiny" data-source-action="add-pattern">Lägg till mönster</button>

    <div class="editor-actions">
      <button class="link danger" data-source-action="delete">Ta bort källan</button>
      <span class="spacer"></span>
      <button class="link" data-source-action="cancel">Avbryt</button>
      <button class="primary" data-source-action="save">Spara</button>
    </div>
    <p class="error" data-source-error hidden></p>
  </article>`;
}

el("sources-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-source-action]");
  if (!button) return;
  const card = button.closest("[data-source]");
  const id = card.dataset.source;
  const action = button.dataset.sourceAction;

  if (action === "edit") {
    state.editingSource = id;
    renderSources();
  } else if (action === "cancel") {
    state.editingSource = null;
    renderSources();
  } else if (action === "add-pattern") {
    collectDraft(card, id);
    state.sourceDraft.match_patterns.push({ pattern: "", mode: "contains" });
    applyDraft(id);
  } else if (action === "drop-pattern") {
    collectDraft(card, id);
    state.sourceDraft.match_patterns.splice(Number(button.closest(".pattern-row").dataset.index), 1);
    applyDraft(id);
  } else if (action === "save") {
    collectDraft(card, id);
    try {
      const result = await request(`/api/sources/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.sourceDraft),
      });
      state.editingSource = null;
      await load();
      showView("sources");
      message(result.coupled
        ? `Källan sparad. ${result.coupled} rader kopplades till den.`
        : "Källan sparad. Inga nya rader matchade.");
    } catch (error) {
      const box = card.querySelector("[data-source-error]");
      box.hidden = false;
      box.textContent = error.message;
    }
  } else if (action === "delete") {
    const source = sourceById(id);
    const count = source ? source.transaction_count : 0;
    const ok = window.confirm(
      count
        ? `Ta bort "${source.name}"? ${count} transaktioner kopplas loss. Raderna finns kvar.`
        : `Ta bort "${source ? source.name : id}"?`
    );
    if (!ok) return;
    try {
      const result = await request(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" });
      state.editingSource = null;
      await load();
      showView("sources");
      message(`Källan borttagen. ${result.uncoupled} rader kopplades loss.`);
    } catch (error) {
      window.alert(error.message);
    }
  }
});

/* Läser av formuläret innan en omritning, så att inskrivna värden inte
   försvinner när man lägger till eller tar bort ett mönster. */
function collectDraft(card, id) {
  const draft = {};
  for (const input of card.querySelectorAll("[data-field]")) {
    draft[input.dataset.field] = input.type === "checkbox" ? input.checked : input.value;
  }
  draft.match_patterns = [...card.querySelectorAll(".pattern-row")].map((row) => ({
    pattern: row.querySelector("[data-pattern-text]").value,
    mode: row.querySelector("[data-pattern-mode]").value,
  }));
  state.sourceDraft = draft;
  return draft;
}

function applyDraft(id) {
  const index = state.sources.findIndex((s) => s.id === id);
  if (index >= 0) state.sources[index] = { ...state.sources[index], ...state.sourceDraft };
  renderSources();
}

function message(text) {
  const box = el("sources-message");
  box.hidden = false;
  box.textContent = text;
  setTimeout(() => { box.hidden = true; }, 4000);
}

el("source-create").addEventListener("click", async () => {
  const name = window.prompt("Vad heter källan?");
  if (!name || !name.trim()) return;
  try {
    const created = await request("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    await load();
    state.editingSource = created.source.id;
    showView("sources");
  } catch (error) {
    window.alert(error.message);
  }
});

el("source-rematch").addEventListener("click", async () => {
  try {
    const result = await request("/api/sources/rematch", { method: "POST" });
    await load();
    showView("sources");
    message(
      result.changed
        ? `${result.changed} rader kopplades till en källa.`
        : "Inga okopplade rader matchade någon källa."
    );
  } catch (error) {
    window.alert(error.message);
  }
});

/* ---------- verifikat ---------- */

function openReceiptDialog(row) {
  state.receiptTarget = row;
  const source = sourceById(row.source_id);

  el("receipt-context").innerHTML =
    `<span class="num">${row.date}</span> · <span class="num">${formatAmount(row.amount)}</span> kr` +
    ` · ${escapeHtml(row.description)}`;

  renderReceiptLink(source);
  el("receipt-note").textContent = source && source.note ? source.note : "";

  // Finns ett verifikat är det filen man kommit för att se. Uppladdning
  // erbjuds inte förrän det gamla tagits bort — annars är det för lätt att
  // skriva över ett underlag av misstag.
  const files = row.receipts || [];
  const has = files.length > 0;
  state.receiptShown = has ? files[0].stored_filename : null;
  const dialog = el("receipt-dialog");
  dialog.classList.toggle("showing-receipt", has);
  el("receipt-fetch").hidden = has;
  el("receipt-upload-step").hidden = has;
  el("receipt-current").hidden = !has;
  el("receipt-remove").hidden = !has;
  el("receipt-upload").hidden = has;
  el("receipt-open").hidden = !has;
  el("receipt-add-more").hidden = !has;
  renderReceiptFiles(row);

  el("receipt-file").value = "";
  el("receipt-name").textContent = "";
  el("receipt-error").hidden = true;
  el("receipt-hint").hidden = true;
  el("receipt-hint").innerHTML =
    `<span class="muted">Letar efter:</span> Kvitto från ${
      escapeHtml(source ? source.name : row.description)} ·
     <span class="num">${formatAmount(Math.abs(row.amount))}</span> kr ·
     <span class="num">${row.date}</span>`;
  dialog.showModal();
}

function receiptUrl(row, filename) {
  return `/api/transactions/${encodeURIComponent(row.id)}/receipts/${
    encodeURIComponent(filename)}/file`;
}

function renderReceiptFiles(row) {
  const files = row.receipts || [];
  if (!files.length) {
    el("receipt-tabs").innerHTML = "";
    el("receipt-preview").innerHTML = "";
    el("receipt-current-info").innerHTML = "";
    return;
  }
  const shown = files.find((r) => r.stored_filename === state.receiptShown) || files[0];
  state.receiptShown = shown.stored_filename;

  // Flikar bara när det finns något att välja mellan.
  el("receipt-tabs").innerHTML = files.length > 1
    ? files.map((r) => `<button class="receipt-tab${
        r.stored_filename === shown.stored_filename ? " on" : ""}"
        data-file="${escapeHtml(r.stored_filename)}">${escapeHtml(r.stored_filename)}</button>`).join("")
    : "";

  el("receipt-preview").innerHTML = previewFor(shown.stored_filename, receiptUrl(row, shown.stored_filename));
  el("receipt-current-info").innerHTML =
    `<span class="num">${escapeHtml(shown.stored_filename)}</span>
     <br><span class="muted">Originalnamn: ${escapeHtml(shown.original_filename)} ·
     uppladdat ${escapeHtml(shown.uploaded_at.slice(0, 16).replace("T", " "))}${
       files.length > 1 ? ` · ${files.length} filer på raden` : ""}</span>`;
}

el("receipt-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest(".receipt-tab");
  if (!tab || !state.receiptTarget) return;
  event.preventDefault();
  state.receiptShown = tab.dataset.file;
  renderReceiptFiles(state.receiptTarget);
});

el("receipt-add-more").addEventListener("click", (event) => {
  event.preventDefault();
  el("receipt-upload-step").hidden = false;
  el("receipt-upload").hidden = false;
  el("receipt-add-more").hidden = true;
  el("receipt-file").focus();
});

/* HEIC renderas inte av webbläsare — där blir det en hänvisning i stället
   för en trasig ruta. */
function previewFor(filename, url) {
  const extension = filename.split(".").pop().toLowerCase();
  if (extension === "pdf") {
    return `<iframe src="${url}#toolbar=1&navpanes=0" title="Verifikat"></iframe>`;
  }
  if (["jpg", "jpeg", "png", "gif", "webp"].includes(extension)) {
    return `<img src="${url}" alt="Verifikat">`;
  }
  return `<p class="no-preview muted small">Filtypen .${escapeHtml(extension)} går inte att
    visa i webbläsaren. Öppna den i ett eget program med knappen nedan.</p>`;
}

/* Länken är en genväg till leverantörens sida, inget verktyget kan hämta åt
   dig — inloggningen ligger hos dem. Saknas den ska den gå att lägga till här,
   utan att man stänger fönstret och börjar om. */
function renderReceiptLink(source) {
  const row = el("receipt-link-row");
  el("receipt-link-edit").hidden = true;
  el("receipt-link-error").hidden = true;

  if (!source) {
    row.innerHTML = `<span class="muted small">Ingen källa kopplad. Kopplar du en
      källa med länk hamnar genvägen hit.</span>`;
    return;
  }
  row.innerHTML = source.receipt_url
    ? `<a class="button-like" href="${escapeHtml(source.receipt_url)}" target="_blank"
         rel="noopener">Öppna ${escapeHtml(source.name)} ↗</a>
       <button class="link-quiet" id="receipt-link-edit-open">Ändra länken</button>`
    : `<span class="muted small">${escapeHtml(source.name)} har ingen länk sparad.</span>
       <button class="link-quiet" id="receipt-link-edit-open">Lägg till länk</button>`;

  el("receipt-link-edit-open").addEventListener("click", (event) => {
    event.preventDefault();
    el("receipt-link-input").value = source.receipt_url || "";
    el("receipt-link-edit").hidden = false;
    el("receipt-link-input").focus();
  });
}

function currentReceiptSource() {
  return state.receiptTarget ? sourceById(state.receiptTarget.source_id) : null;
}

el("receipt-link-cancel").addEventListener("click", (event) => {
  event.preventDefault();
  el("receipt-link-edit").hidden = true;
  el("receipt-link-error").hidden = true;
});

el("receipt-link-save").addEventListener("click", async (event) => {
  event.preventDefault();
  const source = currentReceiptSource();
  if (!source) return;
  try {
    const result = await request(`/api/sources/${encodeURIComponent(source.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ receipt_url: el("receipt-link-input").value.trim() }),
    });
    // Länken hör till källan, inte till raden — den gäller alla dess köp.
    const index = state.sources.findIndex((s) => s.id === source.id);
    if (index >= 0) state.sources[index] = result.source;
    renderReceiptLink(result.source);
    render();
  } catch (error) {
    el("receipt-link-error").hidden = false;
    el("receipt-link-error").textContent = error.message;
  }
});

el("receipt-link-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    el("receipt-link-save").click();
  }
});

async function uploadReceipts(row, files) {
  const form = new FormData();
  for (const file of files) form.append("file", file);
  const result = await request(
    `/api/transactions/${encodeURIComponent(row.id)}/receipts`,
    { method: "POST", body: form }
  );
  const index = state.transactions.findIndex((item) => item.id === row.id);
  if (index >= 0) state.transactions[index] = result.transaction;
  return result;
}

function addedMessage(result) {
  const names = result.added.map((r) => r.stored_filename);
  return names.length === 1
    ? `Sparat som ${names[0]}`
    : `${names.length} filer sparade: ${names.join(", ")}`;
}

el("receipt-file").addEventListener("click", () => {
  el("receipt-hint").hidden = false;
});

el("receipt-file").addEventListener("change", () => {
  const files = [...el("receipt-file").files];
  el("receipt-name").textContent = files.length
    ? (files.length === 1 ? `Vald fil: ${files[0].name}` : `${files.length} filer valda`)
    : "";
  el("receipt-hint").hidden = true;
});

el("receipt-dialog").addEventListener("close", () => {
  el("receipt-hint").hidden = true;
});

el("receipt-upload").addEventListener("click", async (event) => {
  event.preventDefault();
  const row = state.receiptTarget;
  const files = [...el("receipt-file").files];
  if (!row) return;
  if (!files.length) {
    showReceiptError("Välj en fil först.");
    return;
  }
  try {
    const result = await uploadReceipts(row, files);
    render();
    flash(addedMessage(result));
    await openReceiptDialog(result.transaction);
  } catch (error) {
    showReceiptError(error.message);
  }
});

el("receipt-open").addEventListener("click", (event) => {
  event.preventDefault();
  const row = state.receiptTarget;
  if (!row || !state.receiptShown) return;
  window.open(receiptUrl(row, state.receiptShown), "_blank", "noopener");
});

el("receipt-remove").addEventListener("click", async (event) => {
  event.preventDefault();
  const row = state.receiptTarget;
  if (!row) return;
  const filename = state.receiptShown;
  if (!filename) return;
  if (!window.confirm(`Ta bort ${filename}? Filen flyttas till papperskorgen.`)) return;
  try {
    const result = await request(
      `/api/transactions/${encodeURIComponent(row.id)}/receipts/${encodeURIComponent(filename)}`,
      { method: "DELETE" }
    );
    const index = state.transactions.findIndex((item) => item.id === row.id);
    if (index >= 0) state.transactions[index] = result.transaction;
    render();
    await openReceiptDialog(result.transaction);
  } catch (error) {
    showReceiptError(error.message);
  }
});

function showReceiptError(text) {
  el("receipt-error").hidden = false;
  el("receipt-error").textContent = text;
}

function flash(text) {
  const box = el("flash");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(state.flashTimer);
  state.flashTimer = setTimeout(() => { box.hidden = true; }, 5000);
}

/* Drag-and-drop, både i modalen och direkt på raden (§7.1). */
function filesFrom(event) {
  const items = event.dataTransfer && event.dataTransfer.files;
  return items && items.length ? [...items] : [];
}

const dropzone = el("dropzone");
dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropzone.classList.add("over");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("over"));
dropzone.addEventListener("drop", async (event) => {
  event.preventDefault();
  dropzone.classList.remove("over");
  const files = filesFrom(event);
  if (!files.length || !state.receiptTarget) return;
  try {
    const result = await uploadReceipts(state.receiptTarget, files);
    render();
    flash(addedMessage(result));
    await openReceiptDialog(result.transaction);
  } catch (error) {
    showReceiptError(error.message);
  }
});

el("list").addEventListener("dragover", (event) => {
  const tr = event.target.closest("tr[data-id]");
  if (!tr) return;
  event.preventDefault();
  tr.classList.add("drop-target");
});
el("list").addEventListener("dragleave", (event) => {
  const tr = event.target.closest("tr[data-id]");
  if (tr) tr.classList.remove("drop-target");
});
el("list").addEventListener("drop", async (event) => {
  const tr = event.target.closest("tr[data-id]");
  if (!tr) return;
  event.preventDefault();
  tr.classList.remove("drop-target");
  const files = filesFrom(event);
  const row = state.transactions.find((item) => item.id === tr.dataset.id);
  if (!files.length || !row) return;
  try {
    const result = await uploadReceipts(row, files);
    render();
    flash(addedMessage(result));
  } catch (error) {
    window.alert(error.message);
  }
});

/* ---------- inställningar ---------- */

const SETTINGS_FIELDS = {
  "set-recipient": "recipient_email",
  "set-sender": "sender_email",
  "set-subject": "subject_template",
  "set-body": "body_template",
  "set-filename": "filename_template",
  "set-hide-not-required": "hide_not_required",
};

const PATH_LABELS = {
  data: "Transaktioner och källor",
  receipts: "Uppladdade verifikat",
  outbox: "Skapade mejlfiler",
  profiles: "Importprofiler",
  trash: "Papperskorg",
};

function renderSettings() {
  for (const [id, key] of Object.entries(SETTINGS_FIELDS)) {
    const input = el(id);
    if (input.type === "checkbox") input.checked = Boolean(state.settings[key]);
    else input.value = state.settings[key] || "";
  }
  el("settings-path").textContent = (state.paths || {}).settings || "settings.json";
  el("settings-paths").innerHTML = Object.entries(PATH_LABELS)
    .filter(([key]) => (state.paths || {})[key])
    .map(([key, label]) =>
      `<dt>${escapeHtml(label)}</dt><dd class="num">${escapeHtml(state.paths[key])}</dd>`)
    .join("");
  el("settings-error").hidden = true;
  el("settings-message").hidden = true;
}

el("settings-save").addEventListener("click", async (event) => {
  event.preventDefault();
  const payload = {};
  for (const [id, key] of Object.entries(SETTINGS_FIELDS)) {
    const input = el(id);
    payload[key] = input.type === "checkbox" ? input.checked : input.value.trim();
  }
  try {
    const result = await request("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.settings = result.settings;
    el("settings-error").hidden = true;
    el("settings-message").hidden = false;
    el("settings-message").textContent = "Sparat.";
    flash("Inställningarna är sparade.");
  } catch (error) {
    el("settings-message").hidden = true;
    el("settings-error").hidden = false;
    el("settings-error").textContent = error.message;
  }
});

/* ---------- utskick ---------- */

async function openSendDialog(row) {
  state.sendTarget = row;
  el("send-context").innerHTML =
    `<span class="num">${row.date}</span> · <span class="num">${formatAmount(row.amount)}</span> kr` +
    ` · ${escapeHtml(row.description)}`;
  el("send-result").hidden = true;
  el("send-error").hidden = true;
  el("send-dialog").showModal();
  await refreshSendDialog();
}

async function refreshSendDialog() {
  const row = state.sendTarget;
  if (!row) return;
  let details;
  try {
    details = await request(`/api/transactions/${encodeURIComponent(row.id)}/email`);
  } catch (error) {
    el("send-error").hidden = false;
    el("send-error").textContent = error.message;
    return;
  }
  state.sendPreview = details;

  const missing = Object.values(details.missing || {});
  el("send-settings").hidden = missing.length === 0;
  el("send-missing").textContent = missing.join(" ");

  el("send-to").textContent = details.to || "ingen mottagare inställd";
  el("send-from").textContent = details.from || "ditt konto i mejlklienten";
  el("send-subject").textContent = details.subject;
  el("send-attachment").textContent = (details.attachments || []).length
    ? details.attachments.join(", ")
    : "saknas";
  el("send-body").textContent = details.body;

  el("send-create").disabled = !details.can_send;
  el("send-create").textContent = details.sent_at ? "Skapa mejlet igen" : "Skapa och öppna mejl";
  el("send-unmark").hidden = !details.sent_at;
  // "Markera som skickad" visas först när mejlet skapats (§8.3), eller om
  // raden redan hunnit bli skickad och ångrats.
  el("send-mark").hidden = !state.emailCreated || Boolean(details.sent_at);
}

el("send-open-settings").addEventListener("click", (event) => {
  event.preventDefault();
  el("send-dialog").close();
  showView("settings");
});

el("send-create").addEventListener("click", async (event) => {
  event.preventDefault();
  const row = state.sendTarget;
  if (!row) return;
  try {
    const result = await request(
      `/api/transactions/${encodeURIComponent(row.id)}/email`, { method: "POST" }
    );
    state.emailCreated = true;
    el("send-error").hidden = true;
    el("send-result").hidden = false;
    el("send-result").textContent = result.message;
    el("send-mark").hidden = false;
  } catch (error) {
    el("send-error").hidden = false;
    el("send-error").textContent = error.message;
  }
});

el("send-mark").addEventListener("click", async (event) => {
  event.preventDefault();
  await setSent(true);
});

el("send-unmark").addEventListener("click", async (event) => {
  event.preventDefault();
  await setSent(false);
});

async function setSent(sent) {
  const row = state.sendTarget;
  if (!row) return;
  try {
    const result = await request(
      `/api/transactions/${encodeURIComponent(row.id)}/sent`,
      { method: sent ? "POST" : "DELETE" }
    );
    const index = state.transactions.findIndex((item) => item.id === row.id);
    if (index >= 0) state.transactions[index] = result.transaction;
    state.sendTarget = result.transaction;
    state.emailCreated = false;
    el("send-dialog").close();
    render();
    flash(sent ? "Raden är markerad som skickad." : "Markeringen är borttagen.");
  } catch (error) {
    el("send-error").hidden = false;
    el("send-error").textContent = error.message;
  }
}

el("send-dialog").addEventListener("close", () => {
  state.emailCreated = false;
});

/* ---------- källdialog ---------- */

async function openSourceDialog(row) {
  state.sourceTarget = row;
  el("source-context").innerHTML =
    `<span class="num">${row.date}</span> · <span class="num">${formatAmount(row.amount)}</span> kr` +
    ` · ${escapeHtml(row.description)}`;
  // Ny källa överst: det är det man kommer hit för när ingen befintlig passar.
  // <hr> i en select stöds av alla nuvarande webbläsare och ignoreras tyst av
  // äldre, så listan fungerar även utan avgränsaren.
  el("source-select").innerHTML =
    '<option value="__new__">Ny källa…</option><hr>' +
    '<option value="">Ingen källa</option>' +
    state.sources
      .map((source) => `<option value="${source.id}">${escapeHtml(source.name)}</option>`)
      .join("");
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
  el("source-dialog").showModal();
  await describeSelectedSource();
}

/* Visar vilka regler den valda källan redan har, och kryssar ur förslaget om
   källan redan träffar raden. Utan det här lägger varje koppling till ännu en
   regel — "Hyra Juni", "Hyra Juli" — trots att "börjar med Hyra" täcker dem. */
async function describeSelectedSource() {
  const box = el("source-existing");
  const sourceId = el("source-select").value;
  const row = state.sourceTarget;

  if (!row || !sourceId || sourceId === "__new__") {
    box.hidden = true;
    el("source-learn").checked = sourceId === "__new__";
    togglePatternFields();
    testPattern();
    return;
  }

  let info;
  try {
    info = await request("/api/sources/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: sourceId, description: row.description }),
    });
  } catch (error) {
    box.hidden = true;
    return;
  }

  const chips = (info.patterns || []).map((raw) => {
    const pattern = typeof raw === "string" ? { pattern: raw, mode: "contains" } : raw;
    const label = (state.matchModes.find((m) => m.id === pattern.mode) || {}).label || pattern.mode;
    return `<span class="pattern"><span class="pattern-mode">${escapeHtml(label)}</span>
      ${escapeHtml(pattern.pattern)}</span>`;
  });

  box.hidden = false;
  box.innerHTML = info.matches
    ? `<span class="already">Källan matchar redan den här raden — ${escapeHtml(info.explanation)}.</span>
       <div class="patterns">${chips.join("")}</div>`
    : `<span class="muted">Källans nuvarande regler träffar inte den här raden.</span>
       <div class="patterns">${chips.join("") ||
         '<span class="muted small">Inga regler ännu.</span>'}</div>`;

  // Föreslå bara ett nytt mönster när det faktiskt behövs.
  el("source-learn").checked = !info.matches;
  togglePatternFields();
  testPattern();
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

el("source-select").addEventListener("change", async () => {
  toggleNewSourceFields();
  await describeSelectedSource();
});
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
    const result = await patchTransaction(row.id, {
      source_id: sourceId || null,
      add_match_pattern: el("source-learn").checked && Boolean(sourceId),
      match_pattern: el("source-pattern").value.trim(),
      match_pattern_mode: el("source-pattern-mode").value,
    });
    el("source-dialog").close();
    await load();
    if (result.coupled) flash(`Regeln kopplade ${result.coupled} rader till.`);
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

/* Läggs på close, inte på Avbryt-knappen: krysset i hörnet och Esc stänger
   också rutan, och en obekräftad förhandsgranskning ska aldrig bli kvar i
   serverns minne. */
el("import-dialog").addEventListener("close", () => {
  if (!state.staged) return;
  request("/api/import/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: state.staged.token }),
  }).catch(() => {});
  state.staged = null;
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

for (const id of ["filter-text", "filter-source", "filter-from", "filter-to", "sort"]) {
  el(id).addEventListener("input", render);
  el(id).addEventListener("change", render);
}

el("filter-reset").addEventListener("click", (event) => {
  event.preventDefault();
  for (const id of ["filter-text", "filter-source", "filter-from", "filter-to"]) {
    el(id).value = "";
  }
  for (const box of document.querySelectorAll("input[data-bucket]")) box.checked = false;
  el("sort").value = "date-desc";
  render();
});

load().catch((error) => {
  el("empty").hidden = false;
  el("empty").textContent = `Kunde inte läsa data: ${error.message}`;
});
