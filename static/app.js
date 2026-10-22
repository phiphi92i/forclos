"use strict";
// FORCLOS front end: hash router over the §6 API. Every number comes from the API.

const S = {
  dash: null, feed: [], case: null, route: { page: "overview" },
  trail: { runId: null, after: 0, status: null, origin: "", caseId: null, customerId: null },
  seenCats: {}, benchSplit: null,
};

// ---------------------------------------------------------------- helpers
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (c, dec = false) => c == null ? "—" : "€" + (c / 100).toLocaleString("en-GB",
  { minimumFractionDigits: dec ? 2 : 0, maximumFractionDigits: dec ? 2 : 0 });
const day = (d) => new Date(String(d).slice(0, 10) + "T12:00:00");
const fr = (d) => d ? day(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
const short = (d) => d ? day(d).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "—";
const ago = (t) => { const m = Math.round((Date.now() - new Date(t)) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const urg = (d) => d == null ? "" : d < 15 ? "urgent" : d < 30 ? "soon" : "";
const title = (s) => /[a-z]/.test(s) ? s : s.toLowerCase().replace(/(^|[\s'(-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())
  .replace(/(\s)([DL])'/g, (m, a, b) => a + b.toLowerCase() + "'");
const who = (w) => w === "AGENT" ? '<span class="who agent">AGENT</span>' : '<span class="who">RULE</span>';
const PROC = { REDRESSEMENT: "Redressement (RJ)", LIQUIDATION: "Liquidation (LJ)", SAUVEGARDE: "Sauvegarde",
               SAUVEGARDE_ACCELEREE: "Accelerated safeguard" };
const KIND = { OPENING: "Opening", CONVERSION: "Conversion", PRONOUNCED_LJ: "Liquidation pronounced",
               PLAN_RESOLUTION: "Plan resolution", CLOSURE: "Closure", CLAIMS_LIST: "Claims list filed", PLAN: "Plan", OTHER: "Other" };
const STATUS = { READY: ["green", "Ready to sign"], NEEDS_REVIEW: ["amber", "Review"], INVESTIGATING: ["gray", "Investigating"],
                 DETECTED: ["gray", "Detected"], CLOSED: ["gray", "Closed"] };
const CAT = { DECLARE: ["green", "Declare"], POST_OPENING: ["gray", "Post-opening"], REVIEW: ["amber", "Review"], PAID: ["gray", "Paid"] };
const status = (s) => { const [c, l] = STATUS[s] || ["gray", s]; return `<span class="status ${c}">${l}</span>`; };
const cat = (s) => { const [c, l] = CAT[s] || ["gray", s]; return `<span class="status ${c}">${l}</span>`; };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 160)}`);
  return r.json();
}
function toast(msg, ms = 4200) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms);
}
const post = (path, body) => api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

// ---------------------------------------------------------------- router
function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [page, id] = h.split("/");
  if (page === "case" && id) return { page: "case", id: +id };
  return { page: ["customers", "feed", "benchmark", "data", "import"].includes(page) ? page : "overview" };
}
async function render() {
  S.route = parseRoute();
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === (S.route.page === "case" ? "overview" : S.route.page)));
  $("sidebar").classList.remove("open");
  const pages = { overview: renderOverview, case: renderCase, customers: renderCustomers, feed: renderFeed,
                  benchmark: renderBenchmark, data: renderData, import: renderImport };
  try { await pages[S.route.page](); } catch (e) { $("view").innerHTML = `<p class="muted">Could not load: ${esc(e.message)}</p>`; }
}
window.addEventListener("hashchange", () => { window.scrollTo(0, 0); render(); });

async function loadDash() {
  S.dash = await api("/api/dashboard");
  const live = S.dash.cases.filter((c) => c.status !== "CLOSED").length;
  const unv = S.dash.customers.filter((c) => c.identity_status !== "VERIFIED" && !c.has_case && !c.crm_siren).length;
  $("nav-count").hidden = !live; $("nav-count").textContent = live;
  $("nav-unverified").hidden = !unv; $("nav-unverified").textContent = unv;
  return S.dash;
}
async function loadFeed() { S.feed = await api("/api/feed?limit=40"); return S.feed; }

// ---------------------------------------------------------------- overview
async function renderOverview() {
  const [d] = await Promise.all([loadDash(), loadFeed()]);
  if (S.route.page !== "overview") return;
  const noSiren = d.customers.filter((c) => !c.crm_siren && c.identity_status !== "VERIFIED");
  const rows = d.cases.map((c) => `
    <tr class="link" data-href="#/case/${c.id}">
      <td><div class="cell-main">${esc(c.customer.crm_name)}</div><div class="cell-sub">${esc(title(c.denomination || ""))} · SIREN ${esc(c.siren)}</div></td>
      <td>${PROC[c.procedure] || "—"}</td>
      <td><div class="cell-main num ${urg(c.days_left)}">${c.days_left == null ? "Review" : "D-" + c.days_left}</div><div class="cell-sub">${fr(c.claim_deadline)}</div></td>
      <td class="right num"><div class="cell-main">${eur(c.declare_cents)}</div><div class="cell-sub">of ${eur(c.exposure_cents)} unpaid</div></td>
      <td>${status(c.status)}</td></tr>`).join("");
  $("view").innerHTML = `
    <div class="page-heading">
      <p class="eyebrow"><span class="dot"></span>Insolvency watch · ${fr(d.today)}${d.last_sync ? ` · BODACC synced ${ago(d.last_sync.finished_at)}, automatically every ${d.sync_every_minutes} min` : ""}</p>
      <h1>${d.customers_at_risk} customer${d.customers_at_risk === 1 ? "" : "s"} in insolvency proceedings.
        ${eur(d.declare_cents)} to declare.</h1>
      <p>Each claim (déclaration de créance) must reach the mandataire judiciaire within two months of the BODACC
        publication of the opening judgment, or it is time-barred: forclos.</p>
    </div>
    <div class="grid kpis">
      <div class="kpi"><p class="eyebrow">Exposure at risk</p><div class="value num">${eur(d.exposure_cents)}</div><div class="sub">unpaid by customers in proceedings</div></div>
      <div class="kpi"><p class="eyebrow">To declare</p><div class="value num">${eur(d.declare_cents)}</div><div class="sub">pre-opening, with evidence</div></div>
      <div class="kpi"><p class="eyebrow">Customers at risk</p><div class="value num">${d.customers_at_risk}</div><div class="sub">matched by exact SIREN</div></div>
      <div class="kpi"><p class="eyebrow">Next deadline</p><div class="value num ${urg(d.nearest_days_left)}">${d.nearest_days_left == null ? "—" : "D-" + d.nearest_days_left}</div>
        <div class="sub">${d.nearest_deadline ? fr(d.nearest_deadline) : "no open deadline"}</div></div>
    </div>
    ${noSiren.length ? `<div class="callout note"><span><b>${noSiren.length} customer${noSiren.length > 1 ? "s have" : " has"} no SIREN on file</b>
      (${noSiren.map((c) => esc(c.crm_name)).join(", ")}). Exact matching cannot see them.</span>
      <a class="button small" href="#/customers">Check identities</a></div>` : ""}
    <div class="two-col">
      <section>
        <div class="section-title"><h2>Cases</h2><span class="muted">${d.cases.length} open</span></div>
        <div class="scroll-x"><table class="table">
          <thead><tr><th>Customer</th><th>Procedure</th><th>Deadline</th><th class="right">To declare</th><th>Status</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5" class="muted">No customer matches a BODACC notice.</td></tr>`}</tbody></table></div>
      </section>
      <aside>
        <div class="section-title"><h2>Latest in the BODACC</h2><a class="muted" href="#/feed">All</a></div>
        <div class="feed">${feedItems(S.feed.slice(0, 9))}</div>
      </aside>
    </div>`;
  document.querySelectorAll("tr[data-href]").forEach((tr) => tr.onclick = () => { location.hash = tr.dataset.href; });
}

function feedItems(list) {
  return list.map((n) => {
    const cust = n.matched_customer_id ? S.dash?.customers.find((c) => c.id === n.matched_customer_id) : null;
    return `<div class="feed-item ${cust ? "match" : ""}">
      <span class="name">${esc(title(n.denomination || ""))}</span><span class="date">${short(n.date_parution)}</span>
      <span class="meta">${KIND[n.event_kind] || n.event_kind}${n.procedure ? " · " + (PROC[n.procedure] || n.procedure) : ""} · ${esc(n.ville || "")}</span>
      ${cust ? `<span class="yours">Your customer: ${esc(cust.crm_name)}</span>` : ""}</div>`;
  }).join("") || '<p class="muted">No notices stored yet.</p>';
}

// ---------------------------------------------------------------- case
async function renderCase(attach = true) {
  const id = S.route.id;
  const c = await api(`/api/cases/${id}`);
  if (S.route.page !== "case" || S.route.id !== id) return;
  S.case = c;
  const opening = c.timeline.find((n) => n.is_anchor);
  const declared = c.invoices.filter((i) => i.category === "DECLARE");
  const verifiedBy = c.customer.identity_status === "VERIFIED" ? c.customer.identity_evidence?.decided_by || "RULE" : null;
  const naiveLate = c.naive_deadline && c.claim_deadline && c.naive_deadline > c.claim_deadline
    ? Math.round((day(c.naive_deadline) - day(c.claim_deadline)) / 864e5) : 0;

  const fresh = !$("case-root") || $("case-root").dataset.id !== String(id);
  if (fresh) {
    $("view").innerHTML = `<div id="case-root" data-id="${id}">
      <a class="back" href="#/">← Overview</a>
      <div id="case-main" class="two-col"><div id="case-left"></div>
        <aside class="sticky"><div class="panel agent-panel" id="agent"></div><div id="actions" class="grid"></div></aside></div></div>`;
    S.seenCats = {};
  }
  const rows = c.invoices.map((i) => {
    const prevSeen = S.seenCats[i.id];
    const flipped = prevSeen && prevSeen !== i.category;
    S.seenCats[i.id] = i.category;
    let delta = "";
    if (i.changed && i.previous) {
      if (i.category === "DECLARE" && i.previous.category !== "DECLARE") delta = `<div class="delta">Added to claim: +${eur(i.outstanding_cents)}</div>`;
      else if (i.previous.category === "DECLARE" && i.category !== "DECLARE") delta = `<div class="delta out">Removed from claim: −${eur(i.outstanding_cents)}</div>`;
    }
    const was = i.changed && i.previous ? `<div class="was">${CAT[i.previous.category]?.[1] || i.previous.category} by ${i.previous.decided_by.toLowerCase()} (invoice date)</div>` : "";
    const tint = `${i.changed && i.category === "DECLARE" ? "changed" : ""} ${flipped ? "flash" : ""}`;
    const detail = i.decided_by === "AGENT" && i.rationale;
    return `<tr class="${tint} ${detail ? "has-detail" : ""}">
      <td><div class="cell-main mono">${esc(i.number)}</div><div class="cell-sub">due ${short(i.due_date)}</div></td>
      <td class="num">${short(i.invoice_date)}</td>
      <td class="num">${i.fait_generateur ? `<span class="cell-main">${short(i.fait_generateur)}</span>` : "—"}
        <div class="cell-sub">${esc((i.basis || "").replace("_", " ").toLowerCase())}${i.evidence_document_id ? ` · doc #${i.evidence_document_id}` : ""}</div></td>
      <td class="right num cell-main">${eur(i.outstanding_cents)}</td>
      <td><div class="cat-cell">${i.category ? `${cat(i.category)} ${who(i.decided_by)}` : (i.outstanding_cents > 0 ? '<span class="muted">Not classified</span>' : cat("PAID"))}</div>
        ${was}${delta}</td></tr>
      ${detail ? `<tr class="detail ${tint}"><td></td><td colspan="4"><div class="rationale">${who("AGENT")} ${esc(i.rationale)}</div></td></tr>` : ""}`;
  }).join("");

  $("case-left").innerHTML = `
    <div class="page-heading" style="margin-bottom:0">
      <p class="eyebrow"><span class="dot"></span>Case · SIREN ${esc(c.siren)} · ${PROC[c.current_procedure] || "—"}</p>
      <h1>${esc(title(c.denomination || c.customer.crm_name))}</h1>
      <p>CRM record “${esc(c.customer.crm_name)}”, ${esc(c.customer.postal_code || "")} ${esc(c.customer.city || "")}.
        ${verifiedBy ? `Identity verified ${who(verifiedBy)}` : `Matched on the SIREN typed in the CRM ${who("RULE")}`}</p>
      <div class="button-row" style="margin-top:16px">${status(c.status)}
        ${c.contracts.some((k) => k.retention_of_title) ? `<span class="status amber">Retention of title</span>` : ""}
        ${c.customer.payment_terms === "CASH" ? `<span class="status green">Cash on delivery</span>` : ""}</div>
    </div>
    <div class="deadline-band">
      <div class="big num ${urg(c.days_left)}">${c.days_left == null ? "Review" : "D-" + c.days_left}</div>
      <div><div class="when">${c.claim_deadline ? "File the claim by <b>" + fr(c.claim_deadline) + "</b>" : "No opening judgment in the history"}</div>
        <div class="why">${who("RULE")} ${opening ? `Anchored on the opening judgment published ${fr(opening.date_parution)}. Two months, art. 641 and 642 CPC.` : "Never computed from a conversion."}</div></div>
    </div>
    ${naiveLate > 0 ? `<div class="callout danger"><span>A tool that restarts a 60-day clock at the latest notice says <b>${fr(c.naive_deadline)}</b>.
      Filing then is <b>${naiveLate} days too late</b>: the claim would be time-barred.</span></div>` : ""}
    <div class="grid stats">
      <div class="stat"><p class="eyebrow">To declare</p><div class="value green num">${eur(c.declare_cents)}</div><div class="sub">${declared.length} invoice${declared.length === 1 ? "" : "s"}, pre-opening</div></div>
      <div class="stat"><p class="eyebrow">Unpaid exposure</p><div class="value num">${eur(c.exposure_cents)}</div><div class="sub">all unpaid invoices</div></div>
      <div class="stat"><p class="eyebrow">Opening judgment</p><div class="value num">${fr(c.opening_judgment_date)}</div><div class="sub">takes effect from 0h that day</div></div>
    </div>
    <div class="section-title"><h2>Invoices: what dates each claim</h2><span class="muted">fait générateur, not invoice date</span></div>
    <div class="scroll-x"><table class="table">
      <thead><tr><th>Invoice</th><th>Invoiced</th><th>Fait générateur</th><th class="right">Unpaid</th><th>Category</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <details class="soft" style="margin-top:16px" id="doc-form" ${S.docOpen ? "open" : ""}>
      <summary style="cursor:pointer;font-weight:500">Add a delivery note</summary>
      <p class="muted" style="font-size:.875rem;margin-top:8px">New evidence re-opens the investigation. The category follows the evidence.</p>
      <label class="field"><span>Invoice</span><select id="doc-invoice">${c.invoices.filter((i) => i.outstanding_cents > 0)
        .map((i) => `<option value="${i.id}">${esc(i.number)} · invoiced ${short(i.invoice_date)} · ${eur(i.outstanding_cents)}</option>`).join("")}</select></label>
      <label class="field"><span>Delivery date</span><input id="doc-date" type="date"></label>
      <label class="field"><span>Text of the note</span><textarea id="doc-body" rows="3"></textarea></label>
      <div class="button-row end"><button class="button primary" id="btn-doc">Add and re-investigate</button></div>
    </details>
    <div class="section-title"><h2>BODACC history</h2><span class="muted">${c.timeline.length} notice${c.timeline.length === 1 ? "" : "s"}</span></div>
    <div class="timeline">${c.timeline.map((n) => `
      <div class="tl-item ${n.is_anchor ? "anchor" : ""}"><div class="tl-dot"></div><div>
        <div class="tl-title">${KIND[n.event_kind] || n.event_kind}${n.procedure ? " · " + (PROC[n.procedure] || n.procedure) : ""}
          ${n.is_anchor ? '<span class="status gray">Deadline anchor</span>' : ""}
          ${n.event_kind === "CONVERSION" ? '<span class="status amber">Does not restart the deadline</span>' : ""}</div>
        <div class="tl-meta">Judgment ${fr(n.jugement_date)} · published ${fr(n.date_parution)} · ${esc(n.tribunal || "")}</div>
        <div class="tl-meta mono">${esc(n.id)}${n.url ? ` · <a target="_blank" rel="noopener" href="${esc(n.url)}">bodacc.fr</a>` : ""}</div>
      </div></div>`).join("")}</div>
    ${(c.notes || []).length ? `<div class="callout note">${c.notes.map(esc).join("<br>")}</div>` : ""}`;

  wireDocForm(c);
  renderActions(c);
  if (fresh || S.trail.caseId !== c.id) {
    renderAgentShell("agent", `Investigate ${c.customer.crm_name}`, c.status === "INVESTIGATING");
    $("btn-run").onclick = async () => {
      $("btn-run").disabled = true;
      const r = await post(`/api/cases/${c.id}/investigate`, { trigger: "Investigation requested from the dashboard." });
      watchRun(r.run_id, { caseId: c.id, origin: c.customer.crm_name });
    };
    if (attach && c.latest_run) watchRun(c.latest_run.id, { caseId: c.id, origin: c.customer.crm_name });
  }
}

function wireDocForm(c) {
  const sel = $("doc-invoice"), date = $("doc-date"), body = $("doc-body");
  const fill = () => {
    const inv = c.invoices.find((i) => String(i.id) === sel.value);
    const d = date.value ? date.value.split("-").reverse().join("/") : "__/__/____";
    if (inv) body.value = `Bon de livraison complémentaire. Date de livraison : ${d}. Livré à : ${c.customer.crm_name}. Facture associée : ${inv.number}. Signé par le client.`;
  };
  if (S.docDraft) { sel.value = S.docDraft.inv; date.value = S.docDraft.date; body.value = S.docDraft.body; } else fill();
  sel.onchange = date.onchange = () => { fill(); keep(); };
  const keep = () => { S.docDraft = { inv: sel.value, date: date.value, body: body.value }; };
  body.oninput = keep;
  $("doc-form").ontoggle = () => { S.docOpen = $("doc-form").open; };
  $("btn-doc").onclick = async () => {
    $("btn-doc").disabled = true;
    try {
      const r = await post("/api/documents", { customer_id: c.customer.id, invoice_id: +sel.value, kind: "DELIVERY_NOTE",
                                               doc_date: date.value || null, body: body.value });
      S.docDraft = null; S.docOpen = false;
      toast(`Document #${r.document_id} added. The agent is re-investigating.`);
      if (r.run_id) watchRun(r.run_id, { caseId: c.id, origin: `${c.customer.crm_name}, new evidence` });
    } catch (e) { toast(e.message); $("btn-doc").disabled = false; }
  };
}

function renderActions(c) {
  const by = Object.fromEntries(c.actions.map((a) => [a.kind, a]));
  const out = [];
  const claim = by.CLAIM_DRAFT;
  if (claim) {
    const p = claim.payload, ready = claim.status === "APPLIED";
    out.push(`<div class="panel action ${ready ? "ready" : ""}">
      <div class="row"><h3>Claim draft</h3>${ready ? '<span class="status green">Ready to sign</span>' : '<span class="status gray">Draft, not sent</span>'}</div>
      <p style="margin-top:2px">Déclaration de créance · chirographaire</p>
      <div class="amount num">${eur(p.total_cents, true)}</div>
      <div class="kv"><span>Due (échu)</span><span class="num">${eur(p.due_split.echu_cents, true)}</span>
        <span>To fall due (à échoir)</span><span class="num">${eur(p.due_split.a_echoir_cents, true)}</span>
        <span>Deadline</span><span class="num"><b>${fr(p.claim_deadline)}</b></span>
        <span>To</span><span style="text-align:right;max-width:200px">${esc(p.officer?.name || "officer to confirm")}</span></div>
      <p>${p.lines.length} invoice${p.lines.length === 1 ? "" : "s"} with evidence · ${p.excluded_post_opening.length} post-opening excluded${p.pending_review.length ? ` · ${p.pending_review.length} pending review` : ""}</p>
      <div class="button-row"><a class="button small" target="_blank" href="/api/actions/${claim.id}/claim.txt">Open draft</a>
        <button class="button small ${ready ? "" : "primary"}" data-apply="${claim.id}" ${ready ? "disabled" : ""}>Mark ready to sign</button></div></div>`);
  }
  const cash = by.PAYMENT_TERMS_CASH;
  if (cash) {
    const done = cash.status === "APPLIED";
    out.push(`<div class="panel action"><div class="row"><h3>New deliveries</h3>${done ? '<span class="status green">Cash on delivery</span>' : '<span class="status gray">Proposed</span>'}</div>
      <p>${esc(cash.payload.text)}</p>
      <div class="button-row"><button class="button small ${done ? "" : "primary"}" data-apply="${cash.id}" ${done ? "disabled" : ""}>Switch to cash on delivery</button></div></div>`);
  }
  const rev = by.REVENDICATION_ALERT;
  if (rev) out.push(`<div class="panel action"><div class="row"><h3>Reclaim goods</h3><span class="status amber">By ${short(rev.payload.deadline)}</span></div>
      <p>${esc(rev.payload.text)}</p></div>`);
  const law = by.LAWYER_REVIEW;
  if (law) out.push(`<div class="panel action" style="background:var(--note);border-color:transparent"><div class="row"><h3>Lawyer review</h3>
      <span class="status amber">${law.payload.reasons.length} item${law.payload.reasons.length > 1 ? "s" : ""}</span></div>
      <ul>${law.payload.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`);
  if (!out.length) out.push(`<div class="soft"><h3 style="font-size:1.125rem">Actions</h3>
      <p class="muted" style="font-size:.875rem;margin-top:6px">Run the investigation: the agent prepares the claim and protective actions for your sign-off.</p></div>`);
  $("actions").innerHTML = out.join("");
  document.querySelectorAll("[data-apply]").forEach((b) => b.onclick = async () => {
    b.disabled = true; await post(`/api/actions/${b.dataset.apply}/apply`); renderCase(false);
  });
}

// ---------------------------------------------------------------- agent trail
function renderAgentShell(target, title, running) {
  $(target).innerHTML = `
    <div class="agent-head"><h3><span id="live-dot"></span>Agent</h3>
      <button class="button small primary" id="btn-run" ${running ? "disabled" : ""}>${running ? "Investigating…" : "Run investigation"}</button></div>
    <div class="agent-meta" id="trail-meta">${esc(title)}</div>
    <div class="trail" id="trail"><p class="empty">No run yet. The agent reads the customer file, the register, the BODACC history and the documents; code applies the law.</p></div>`;
}

function watchRun(runId, { caseId = null, customerId = null, origin = "" } = {}) {
  S.trail = { runId, after: 0, status: "RUNNING", origin, caseId, customerId };
  if ($("trail")) $("trail").innerHTML = "";
  pollRun(runId);
}

function line(step) {
  const p = step.payload || {}, t = step.tool;
  if (step.kind === "NOTE") return { cls: "note", html: esc(p.text) };
  if (step.kind === "ERROR") return { cls: "error", html: `Error in ${esc(t || "run")}: ${esc(p.error)}` };
  if (step.kind === "TOOL_CALL") {
    switch (t) {
      case "get_customer_file": return { who: "AGENT", html: "Opens the customer file" };
      case "read_document": return { who: "AGENT", html: `Reads document #${p.document_id}` };
      case "search_company": return { who: "AGENT", html: `Searches the company register for “${esc(p.query)}”${p.postal_code ? " in " + esc(p.postal_code) : ""}` };
      case "get_company": return { who: "AGENT", html: `Looks up SIREN ${esc(p.siren)} in the register` };
      case "get_bodacc_history": return { who: "AGENT", html: `Fetches the BODACC history of SIREN ${esc(p.siren)}` };
      case "record_identity": return { who: "AGENT", html: `Identity <b>${esc(p.status.toLowerCase())}</b>${p.siren ? ": SIREN " + esc(p.siren) : ""}. <span class="ev">${esc(p.evidence)}</span>` };
      case "record_claim_classification": return { who: "AGENT", html: `Invoice #${p.invoice_id} arose on <b>${p.fait_generateur_date ? fr(p.fait_generateur_date) : "unknown date"}</b> (${esc(p.basis.toLowerCase())}${p.evidence_document_id ? ", doc #" + p.evidence_document_id : ""}). <span class="ev">${esc(p.rationale)}</span>` };
      case "flag_lawyer_review": return { who: "AGENT", cls: "flag", html: `Sends to a lawyer: ${esc(p.reason)}` };
      default: return null;
    }
  }
  switch (t) {
    case "get_customer_file": { const c = p.customer || {};
      return { sub: true, html: `${esc(c.crm_name)} · CRM SIREN ${esc(c.crm_siren || "none")} · ${esc(c.postal_code || "")} ${esc(c.city || "")} · ${(p.invoices || []).length} invoices, ${(p.documents || []).length} documents` }; }
    case "read_document": {
      const m = (p.body || "").match(/Date de livraison\s*:\s*([0-9/_]+)/);
      return { sub: true, html: `${esc((p.kind || "").replace("_", " ").toLowerCase())}${m ? `: <b>delivered ${esc(m[1])}</b>` : ""}` }; }
    case "search_company": { const r = p.results || [];
      return { sub: true, html: r.length ? r.slice(0, 3).map((x) => `${esc(x.nom_complet)} · ${esc(x.siren)} · ${x.etat_administratif === "A" ? "active" : "ceased"} · ${esc(x.siege?.code_postal || "")} ${esc(x.siege?.commune || "")}`).join("<br>") : "No match" }; }
    case "get_company": { const x = p.company;
      return { sub: true, html: x ? `${esc(x.nom_complet)} · ${x.etat_administratif === "A" ? "active" : "ceased"} · ${esc(x.siege?.adresse || "")}` : esc(p.note) }; }
    case "get_bodacc_history": { const n = p.notices || [];
      return { sub: true, html: n.length ? n.map((x) => `${KIND[x.event_kind] || x.event_kind}${x.procedure ? " " + (PROC[x.procedure] || x.procedure) : ""}, published ${short(x.date_parution)}`).join(" → ")
                                       : "No collective-procedure notice" }; }
    case "record_identity": return p.note ? { sub: true, who: "RULE", html: esc(p.note) } : null;
    case "compute_deadlines": return { who: "RULE", html: p.claim_deadline
        ? `Claim deadline <b>${fr(p.claim_deadline)}</b> (D-${p.days_left}), anchored on the opening published ${fr(p.anchor_publication)}.${(p.notes || []).map((x) => `<div class="ev">${esc(x)}</div>`).join("")}`
        : `No deadline. ${esc((p.notes || []).join(" "))}` };
    case "record_claim_classification": {
      const d = p.declare_delta_cents > 0 ? ` <span class="gain">Added to claim: +${eur(p.declare_delta_cents)}</span>`
              : p.declare_delta_cents < 0 ? ` <span class="loss">Removed from claim: −${eur(-p.declare_delta_cents)}</span>` : "";
      return { sub: true, who: "RULE", html: `${esc(p.number)} is <b>${(CAT[p.category]?.[1] || p.category).toLowerCase()}</b>${p.changed ? ` (was ${(CAT[p.previous_category]?.[1] || "").toLowerCase()})` : ""}.${d}` }; }
    case "propose_actions": return { who: "RULE", html: `Prepared ${(p.actions || []).map((a) => a.kind === "CLAIM_DRAFT" ? `the claim draft (${a.total})` : a.kind === "PAYMENT_TERMS_CASH" ? "cash terms for new deliveries" : "a revendication alert").join(", ") || "nothing"}.${(p.warnings || []).map((w) => `<div class="ev">${esc(w)}</div>`).join("")}` };
    case "finish": return { cls: "finish", html: `<b>${esc(p.status.replace("_", " ").toLowerCase())}.</b> ${esc(p.summary)}` };
    default: return null;
  }
}

function stepHtml(step) {
  const l = line(step);
  if (!l) return "";
  return `<div class="step ${l.sub ? "sub" : ""} ${l.cls || ""}">${l.who ? who(l.who) : "<span></span>"}<div>${l.html}</div></div>`;
}

async function pollRun(runId) {
  if (S.trail.runId !== runId) return;
  let r;
  try { r = await api(`/api/runs/${runId}/steps?after=${S.trail.after}`); } catch { setTimeout(() => pollRun(runId), 1500); return; }
  if (S.trail.runId !== runId) return;
  const box = $("trail");
  if (r.steps.length) {
    S.trail.after = r.steps[r.steps.length - 1].id;
    if (box) { box.insertAdjacentHTML("beforeend", r.steps.map(stepHtml).join("")); box.scrollTop = box.scrollHeight; }
    const touched = r.steps.some((s) => s.kind === "TOOL_RESULT" && ["record_claim_classification", "compute_deadlines",
      "propose_actions", "record_identity", "flag_lawyer_review", "finish"].includes(s.tool));
    if (touched) refreshAfterStep(r);
  }
  S.trail.status = r.status;
  const running = r.status === "RUNNING";
  if ($("live-dot")) $("live-dot").className = running ? "live" : "";
  if ($("btn-run")) { $("btn-run").disabled = running; $("btn-run").textContent = running ? "Investigating…" : "Run again"; }
  if ($("trail-meta")) $("trail-meta").textContent = `${S.trail.origin} · ${running ? "live" : r.status.toLowerCase()}` +
    (r.input_tokens ? ` · ${(r.input_tokens + r.output_tokens).toLocaleString("en-GB")} tokens` : "");
  if (running) setTimeout(() => pollRun(runId), 900);
  else refreshAfterStep(r, true);
}

function refreshAfterStep(r, done = false) {
  if (S.route.page === "case" && S.route.id === (r.case_id || S.trail.caseId)) renderCase(false);
  else if (S.route.page === "customers") renderCustomers(false, done ? r : null);
  loadDash().catch(() => {});
}

// ---------------------------------------------------------------- customers
async function renderCustomers(full = true, finished = null) {
  const d = await loadDash();
  if (S.route.page !== "customers") return;
  const caseFor = (cid) => d.cases.find((c) => c.customer.id === cid);
  const rows = d.customers.map((c) => {
    let ident;
    if (c.identity_status === "VERIFIED") ident = `<span class="status green">Verified</span><div class="cell-sub mono">${esc(c.verified_siren)}</div>`;
    else if (c.identity_status === "REVIEW") ident = '<span class="status amber">Review</span>';
    else if (c.identity_status === "NOT_FOUND") ident = '<span class="status amber">Not found</span>';
    else if (c.crm_siren) ident = `<span class="status gray">SIREN on file</span><div class="cell-sub mono">${esc(c.crm_siren)}</div>`;
    else ident = '<span class="status red">No SIREN</span>';
    const k = caseFor(c.id);
    return `<tr>
      <td><div class="cell-main">${esc(c.crm_name)}</div><div class="cell-sub">${esc(c.postal_code || "")} ${esc(c.city || "")} · ${c.payment_terms === "CASH" ? "cash on delivery" : "30 days"}</div></td>
      <td>${ident}</td>
      <td class="right num">${eur(c.outstanding_cents)}</td>
      <td class="right">${k ? `<a class="button small" href="#/case/${k.id}">Open case</a>`
        : c.identity_status === "VERIFIED" ? '<span class="muted" style="font-size:.8rem">No proceedings</span>'
        : `<button class="button small soft" data-resolve="${c.id}">Check identity</button>`}</td></tr>`;
  }).join("");
  if (full || !$("cust-table")) {
    $("view").innerHTML = `
      <div class="page-heading"><p class="eyebrow"><span class="dot"></span>CRM repair</p>
        <h1>Customers</h1>
        <p>Exact SIREN matching only sees customers whose identity is right. Sales types trade names, typos and stale SIRENs:
          the agent finds the legal entity in the register, with evidence.</p>
        <div class="button-row" style="margin-top:20px"><button class="button primary" id="btn-add">Add a customer</button></div></div>
      <div class="two-col"><div class="scroll-x"><table class="table" id="cust-table">
        <thead><tr><th>Customer, as in the CRM</th><th>Identity</th><th class="right">Unpaid</th><th></th></tr></thead>
        <tbody></tbody></table></div>
        <aside class="sticky"><div class="panel agent-panel" id="agent"></div><div id="run-result"></div></aside></div>`;
    renderAgentShell("agent", "Pick a customer to check its identity", false);
    $("btn-run").hidden = true;
    $("btn-add").onclick = openModal;
    if (S.trail.runId && S.trail.customerId) { const id = S.trail.runId; S.trail.after = 0; $("trail").innerHTML = ""; pollRun(id); }
  }
  $("cust-table").querySelector("tbody").innerHTML = rows;
  document.querySelectorAll("[data-resolve]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    const name = d.customers.find((c) => c.id === +b.dataset.resolve)?.crm_name;
    const r = await post(`/api/customers/${b.dataset.resolve}/resolve`);
    $("run-result").innerHTML = "";
    watchRun(r.run_id, { customerId: +b.dataset.resolve, origin: `Identity check: ${name}` });
  });
  if (finished && $("run-result")) {
    const k = finished.case_id ? d.cases.find((c) => c.id === finished.case_id) : null;
    $("run-result").innerHTML = k ? `<div class="callout danger" style="margin-top:0"><span><b>Insolvency proceedings found.</b> Case opened for ${esc(k.customer.crm_name)}.</span>
        <a class="button small primary" href="#/case/${k.id}">Open case</a></div>`
      : `<div class="callout note" style="margin-top:0;background:var(--green-soft);color:var(--green)"><span><b>No proceedings.</b> No false alarm: supply continues normally.</span></div>`;
  }
}

function openModal() { $("modal").hidden = false; $("new-name").focus(); }
$("btn-cancel").onclick = () => { $("modal").hidden = true; };
$("modal").onclick = (e) => { if (e.target === $("modal")) $("modal").hidden = true; };
$("btn-create").onclick = async () => {
  const name = $("new-name").value.trim(), cp = $("new-cp").value.trim();
  if (name.length < 2 || !/^\d{5}$/.test(cp)) { toast("A name and a 5-digit postal code are needed."); return; }
  try {
    const r = await post("/api/customers", { crm_name: name, postal_code: cp });
    $("modal").hidden = true; $("new-name").value = ""; $("new-cp").value = "";
    if (S.route.page !== "customers") location.hash = "#/customers";
    setTimeout(() => watchRun(r.run_id, { customerId: r.customer_id, origin: `Identity check: ${name}` }), 150);
  } catch (e) { toast(e.message); }
};

// ---------------------------------------------------------------- feed
async function renderFeed() {
  await loadDash(); const f = await loadFeed();
  if (S.route.page !== "feed") return;
  $("view").innerHTML = `
    <div class="page-heading"><p class="eyebrow"><span class="dot"></span>Source · BODACC, official open data</p>
      <h1>BODACC feed</h1>
      <p>Collective-procedure notices for legal persons, latest first. Your customers are highlighted. Ingestion is idempotent:
        a notice seen twice is stored once.</p>
      <div class="button-row" style="margin-top:20px"><button class="button primary" id="btn-ingest">Fetch the last 2 days</button>
        <span class="muted" style="font-size:.875rem">${f.length} notices shown</span></div></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>Published</th><th>Company</th><th>Event</th><th>Court</th><th>Your customer</th></tr></thead>
      <tbody>${f.map((n) => {
        const cust = n.matched_customer_id ? S.dash.customers.find((c) => c.id === n.matched_customer_id) : null;
        return `<tr style="${cust ? "background:var(--accent-soft)" : ""}"><td class="num mono">${short(n.date_parution)}</td>
          <td><div class="cell-main">${esc(title(n.denomination || ""))}</div><div class="cell-sub">SIREN ${esc(n.siren || "—")} · ${esc(n.cp || "")} ${esc(n.ville || "")}</div></td>
          <td>${KIND[n.event_kind] || n.event_kind}<div class="cell-sub">${PROC[n.procedure] || ""}</div></td>
          <td class="muted" style="font-size:.8rem">${esc((n.tribunal || "").replace(/^Greffe du /, ""))}</td>
          <td>${cust ? `<span class="status red">${esc(cust.crm_name)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div>`;
  $("btn-ingest").onclick = async () => {
    const b = $("btn-ingest"); b.disabled = true; b.textContent = "Fetching…";
    try { const r = await post("/api/ingest", { days: 2 }); toast(`${r.fetched} notices fetched, ${r.inserted} new, ${r.new_cases} new case(s).`); }
    catch (e) { toast("BODACC unreachable: showing stored notices."); }
    renderFeed();
  };
}

// ---------------------------------------------------------------- benchmark
async function renderBenchmark() {
  const rows = await api("/api/benchmark");
  if (S.route.page !== "benchmark") return;
  const head = `<div class="page-heading"><p class="eyebrow"><span class="dot"></span>Evidence it works</p><h1>€ lost to forclusion</h1>
    <p>What a creditor fails to claim on time: a customer missed, a deadline later than the legal one, or an invoice wrongly left out. Lower is better.</p></div>`;
  if (!rows.length) { $("view").innerHTML = head + '<p class="muted">No benchmark run yet: <span class="mono">python -m benchmark.run --split dev</span></p>'; return; }
  const splits = [...new Set(rows.map((r) => r.split))];
  S.benchSplit = splits.includes(S.benchSplit) ? S.benchSplit : (splits.includes("holdout") ? "holdout" : splits[0]);
  const sys = ["NAIVE", "RULES", "FORCLOS"].map((s) => rows.find((r) => r.split === S.benchSplit && r.system === s)).filter(Boolean);
  const desc = { NAIVE: "A BODACC alert: SIREN or exact name, 60 days from the latest notice, invoice date.",
                 RULES: "Exact SIREN and the legal engine, invoice date. FORCLOS without the agent.",
                 FORCLOS: "Rules plus the agent: identity repair, full history, documents." };
  const m0 = sys[0].metrics;
  $("view").innerHTML = head + `
    <div class="button-row" style="margin-bottom:20px">${splits.map((s) => `<button class="button small ${s === S.benchSplit ? "primary" : "soft"}" data-split="${s}">${s === "holdout" ? "Held-out set" : "Dev set"}</button>`).join("")}</div>
    <div class="grid bench">${sys.map((r) => { const m = r.metrics; return `
      <div class="bench-col ${r.system === "FORCLOS" ? "us" : ""}">
        <h3>${r.system === "FORCLOS" ? "FORCLOS" : r.system.charAt(0) + r.system.slice(1).toLowerCase()}</h3>
        <p class="muted" style="font-size:.875rem;margin-top:6px;min-height:40px">${desc[r.system]}</p>
        <div class="lost num">${eur(m.eur_lost_cents)}</div>
        <p class="muted" style="font-size:.875rem;margin-top:6px">lost of ${eur(m.truth_declare_cents)} to declare</p>
        <div class="kv">
          <span>Affected customers found</span><span class="num">${m.found} / ${m.affected}</span>
          <span>False alarms (healthy flagged)</span><span class="num">${m.false_alarms} / ${m.healthy}</span>
          <span>Exact claim deadline</span><span class="num">${m.deadline_ok} / ${m.affected}</span>
          <span>Escalated to review</span><span class="num">${m.reviewed}</span>
          <span>Tokens per case</span><span class="num">${m.tokens_per_case ? Math.round(m.tokens_per_case).toLocaleString("en-GB") : "0"}</span>
          <span>Median time per case</span><span class="num">${m.median_seconds ? m.median_seconds.toFixed(1) + " s" : "instant"}</span>
        </div></div>`; }).join("")}</div>
    <p class="muted" style="font-size:.8rem;margin-top:20px">Real BODACC notices and register records, synthetic CRM perturbations, n=${m0.n}
      (${S.benchSplit === "holdout" ? "held-out set, run once" : "dev set"}). Run ${new Date(sys[0].run_at).toLocaleString("en-GB")}.</p>`;
  document.querySelectorAll("[data-split]").forEach((b) => b.onclick = () => { S.benchSplit = b.dataset.split; renderBenchmark(); });
}

// ---------------------------------------------------------------- data layer
async function renderData() {
  const d = await api("/api/data");
  if (S.route.page !== "data") return;
  const n = (x) => Number(x || 0).toLocaleString("en-GB");
  const box = (eyebrow, title, lines) => `<div class="flow-box"><p class="eyebrow">${eyebrow}</p><h3>${title}</h3>
    <div class="flow-lines">${lines.map((l) => `<div>${l}</div>`).join("")}</div></div>`;
  $("view").innerHTML = `
    <div class="page-heading"><p class="eyebrow"><span class="dot"></span>${esc(d.database.provider)} · ${esc(d.database.engine.replace(/ \(.*\)/, ""))} · ${esc(d.database.size)}</p>
      <h1>Data layer</h1>
      <p>Everything the agent knows lives in one Postgres database: public notices, register records, your ledger, and the
        cases it builds up over time. Rules read it; the agent adds evidence to it; nothing is decided from a prompt alone.</p></div>
    <div class="flow">
      <div class="flow-col">
        ${box("Source · live", "BODACC notices", [`<b class="num">${n(d.bodacc.rows)}</b> notices stored`, `${n(d.bodacc.procedure_notices)} openings and conversions`,
          `latest publication ${fr(d.bodacc.latest_publication)}`, `synced every ${d.sync_every_minutes} min, upsert on notice id`])}
        ${box("Source · cached 7 days", "Company register", [`<b class="num">${n(d.register.rows)}</b> lookups cached`, `${n(d.register.stale)} stale (refetched on use)`,
          "stale copy used, and labelled, if the API is down"])}
        ${box("Source · yours", "Receivables ledger", [`<b class="num">${n(d.ledger.customers)}</b> customers`, `${n(d.ledger.invoices)} invoices, ${n(d.ledger.documents)} documents`, "fictional in this demo"])}
      </div>
      <div class="flow-arrow">→</div>
      <div class="flow-col">
        ${box("Memory", "Cases", [`<b class="num">${n(d.memory.cases)}</b> cases`, `${n(d.memory.case_events)} notices linked (never re-alerted)`,
          `${n(d.memory.decisions)} decisions, append-only`, `${n(d.memory.agent_decisions)} by the agent, each with its evidence`])}
        <div class="flow-split">
          ${box("Code", "Legal rules", ["deadlines (art. 641, 642 CPC)", "pre / post opening", "amounts, claim split"])}
          ${box("Agent", "Investigator", [`<b class="num">${n(d.agent.runs)}</b> runs, ${n(d.agent.steps)} steps`, `${n(d.agent.tokens)} tokens`,
            `median ${d.agent.median_seconds ? Number(d.agent.median_seconds).toFixed(0) + " s" : "—"} per run`])}
        </div>
      </div>
      <div class="flow-arrow">→</div>
      <div class="flow-col">${box("Output · for sign-off", "Actions", [`<b class="num">${n(d.memory.actions)}</b> prepared`, "claim drafts to the mandataire",
          "cash terms for new deliveries", "revendication alerts", "lawyer review items"])}</div>
    </div>
    <div class="section-title"><h2>Sync log</h2><span class="muted">automatic and manual pulls from the BODACC</span></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>Finished</th><th>Trigger</th><th class="right">Fetched</th><th class="right">New</th>
      <th class="right">Updated</th><th class="right">New cases</th><th class="right">Agent runs started</th></tr></thead>
      <tbody>${d.syncs.map((r) => `<tr><td class="num">${r.finished_at ? new Date(r.finished_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "running"}</td>
        <td>${r.error ? `<span class="status red">error</span>` : `<span class="status ${r.trigger === "schedule" ? "green" : "gray"}">${esc(r.trigger)}</span>`}</td>
        <td class="right num">${n(r.fetched)}</td><td class="right num">${n(r.inserted)}</td><td class="right num">${n(r.updated)}</td>
        <td class="right num">${n(r.new_cases)}</td><td class="right num">${n(r.investigations)}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------------------------------------------------------------- import
const SAMPLE_CSV = `customer;siren;postal_code;city;invoice_number;invoice_date;due_date;amount;paid
Maison Vivier;;69500;Bron;FA-2026-1201;28/08/2026;27/09/2026;3120,40;0
Maison Vivier;;69500;Bron;FA-2026-1240;04/09/2026;04/10/2026;1845,00;0
Chimere;;42000;Saint-Etienne;FA-2026-1188;15/09/2026;15/10/2026;2210,00;0
Brasserie Georges;;69002;Lyon;FA-2026-1207;02/09/2026;02/10/2026;4980,00;4980,00`;

async function renderImport() {
  $("view").innerHTML = `
    <div class="page-heading"><p class="eyebrow"><span class="dot"></span>Onboarding · 2 minutes</p>
      <h1>Import your receivables</h1>
      <p>Export the aged receivables (balance âgée clients) from your accounting software as CSV. FORCLOS repairs the
        customer identities, checks every one against the BODACC, and keeps watching every day after.</p></div>
    <div class="two-col">
      <section>
        <label class="field" style="margin-top:0"><span>CSV, comma or semicolon separated. French headers work too (client, code postal, n° facture, échéance, montant, réglé).</span>
          <textarea id="csv" rows="12" class="mono" style="font-size:.8rem"></textarea></label>
        <div class="button-row" style="margin-top:14px">
          <button class="button primary" id="btn-import">Import and check</button>
          <label class="button soft" style="cursor:pointer">Choose a file<input type="file" id="csv-file" accept=".csv,text/csv" hidden></label>
          <button class="button" id="btn-sample">Use the sample</button>
        </div>
        <div id="import-result"></div>
      </section>
      <aside class="soft">
        <h3 style="font-size:1.125rem">What happens</h3>
        <ol class="steps">
          <li><b>Rules first.</b> A SIREN in the file is matched exactly against every BODACC notice stored.</li>
          <li><b>Register check.</b> A SIREN the register reports as ceased or unknown is not trusted.</li>
          <li><b>Agent repair.</b> Customers with no usable SIREN go to the agent: name, postal code, trade names, active status.</li>
          <li><b>Cases.</b> Every match opens a case: deadline, claim, protective actions, for your sign-off.</li>
          <li><b>Every day after.</b> The BODACC is synced every ${S.dash?.sync_every_minutes || 30} min; new notices trigger the agent.</li>
        </ol>
        <p class="muted" style="font-size:.8rem;margin-top:12px">Columns: customer, siren (optional), postal_code, city, invoice_number, invoice_date, due_date, amount, paid.</p>
      </aside>
    </div>`;
  $("btn-sample").onclick = () => { $("csv").value = SAMPLE_CSV; };
  $("csv-file").onchange = async (e) => { const f = e.target.files[0]; if (f) $("csv").value = await f.text(); };
  $("btn-import").onclick = async () => {
    const b = $("btn-import"); b.disabled = true; b.textContent = "Importing…";
    try {
      const r = await post("/api/import", { csv: $("csv").value });
      $("import-result").innerHTML = `<div class="callout note" style="background:var(--green-soft);color:var(--ink)">
        <span><b>${r.customers_created} customers, ${r.invoices_created} invoices imported.</b>
        ${r.cases_opened} case${r.cases_opened === 1 ? "" : "s"} opened by exact SIREN · ${r.identity_checks_queued} identity check${r.identity_checks_queued === 1 ? "" : "s"} queued for the agent.</span>
        <a class="button small primary" href="#/customers">Follow on Customers</a></div>
        ${r.errors.length ? `<div class="callout note"><span>${r.errors.map(esc).join("<br>")}</span></div>` : ""}`;
      loadDash();
    } catch (e) { $("import-result").innerHTML = `<div class="callout danger"><span>${esc(e.message)}</span></div>`; }
    b.disabled = false; b.textContent = "Import and check";
  };
}

// ---------------------------------------------------------------- global wiring
$("btn-reset").onclick = async () => {
  if (!confirm("Restore the frozen demo seed? Agent runs and decisions are cleared.")) return;
  const r = await post("/api/demo/reset");
  S.trail = { runId: null, after: 0, status: null, origin: "", caseId: null, customerId: null };
  toast(`Demo reset: ${r.customers} customers, ${r.cases} cases found by the exact SIREN rule.`);
  location.hash = "#/"; render();
};
$("btn-menu").onclick = () => $("sidebar").classList.toggle("open");
setInterval(() => {
  if (S.trail.status === "RUNNING" || document.hidden) return;
  if (S.route.page === "overview") renderOverview().catch(() => {});
  if (S.route.page === "customers") renderCustomers(false).catch(() => {});
}, 10000);
render();
