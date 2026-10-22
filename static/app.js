"use strict";
// FORCLOS front end: hash router over the §6 API. Every number comes from the API.

const S = {
  dash: null, feed: [], case: null, route: { page: "home" },
  trail: { runId: null, after: 0, status: null, origin: "", caseId: null, customerId: null },
  seenCats: {},
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
const dday = (d) => d == null ? null : d < 0 ? "Passed" : `D-${d}`;
const title = (s) => /[a-z]/.test(s) ? s : s.toLowerCase().replace(/(^|[\s'(-])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())
  .replace(/(\s)([DL])'/g, (m, a, b) => a + b.toLowerCase() + "'");
const who = (w) => w === "AGENT" ? '<span class="who agent">AGENT</span>' : '<span class="who">RULE</span>';
const PROC = { REDRESSEMENT: "Redressement (RJ)", LIQUIDATION: "Liquidation (LJ)", SAUVEGARDE: "Sauvegarde",
               SAUVEGARDE_ACCELEREE: "Accelerated safeguard" };
const KIND = { OPENING: "Opening", CONVERSION: "Conversion", PRONOUNCED_LJ: "Liquidation pronounced",
               PLAN_RESOLUTION: "Plan resolution", CLOSURE: "Closure", CLAIMS_LIST: "Claims list filed", PLAN: "Plan", OTHER: "Other" };
const STATUS = { READY: ["green", "Claim ready"], NEEDS_REVIEW: ["amber", "To review"], INVESTIGATING: ["running", "Investigating"],
                 DETECTED: ["gray", "Not investigated"], CLOSED: ["gray", "Closed"] };
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
const ROUTES = { "": "home", cases: "cases", agent: "agent", runs: "agent", proof: "proof", benchmark: "proof",
                 customers: "customers", feed: "feed", data: "data", import: "import" };
function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [page, id] = h.split("/");
  if (page === "case" && id) return { page: "case", id: +id };
  if (page === "run" && id) return { page: "run", id };
  return { page: ROUTES[page] || "home" };
}
async function render() {
  S.route = parseRoute();
  if (S.wf && location.hash !== S.wf.origin) closeWorkflow(true);
  document.body.dataset.page = S.route.page;
  const nav = { case: "cases", customers: "cases", import: "cases", run: "agent" }[S.route.page] || S.route.page;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
  const pages = { home: renderHome, cases: renderCases, case: renderCase, customers: renderCustomers, feed: renderFeed,
                  proof: renderProof, data: renderData, import: renderImport, agent: renderRuns, run: renderRunPage };
  try { await pages[S.route.page](); } catch (e) { $("view").innerHTML = `<section class="page"><p class="muted">Could not load: ${esc(e.message)}</p></section>`; }
}
window.addEventListener("hashchange", () => { window.scrollTo({ top: 0, behavior: "instant" }); render(); });

async function loadDash() {
  S.dash = await api("/api/dashboard");
  const open = S.dash.cases.filter((c) => c.status !== "CLOSED").length;
  $("nav-count").hidden = !open; $("nav-count").textContent = open;
  $("nav-runs").hidden = !S.dash.live_runs; $("nav-runs").textContent = S.dash.live_runs ? `${S.dash.live_runs} live` : "";
  $("sync-text").textContent = S.dash.last_sync ? `BODACC synced ${ago(S.dash.last_sync.finished_at)}` : "Watching the BODACC";
  return S.dash;
}
async function loadFeed() { S.feed = await api("/api/feed?limit=40"); return S.feed; }

// ---------------------------------------------------------------- home
const agentFound = (k) => k.invoices.filter((i) => i.changed && i.category === "DECLARE" && i.previous?.category !== "DECLARE")
  .reduce((t, i) => t + i.outstanding_cents, 0);
const howCard = (i, h, p, stat, caption) => `<div class="how-card"><span class="how-n">${i}</span><h3>${h}</h3><p>${p}</p>
  <div class="how-stat num">${stat}</div><div class="how-cap">${caption}</div></div>`;

function homePreview(k) {
  const found = agentFound(k), looked = !!k.latest_run, claim = k.actions.find((a) => a.kind === "CLAIM_DRAFT");
  const steps = [
    [k.customer.identity_status === "VERIFIED", `Company found: <b>${esc(title(k.denomination || ""))}</b>`],
    [looked, `${k.documents.length} delivery note${k.documents.length === 1 ? "" : "s"} read`],
    [!!k.claim_deadline, `Legal deadline: <b>${fr(k.claim_deadline)}</b>`],
    [!!claim, claim ? "Claim drafted, ready for your signature" : "Claim not drafted yet"],
  ];
  return `<a class="preview" href="#/case/${k.id}">
    <div class="pv-top"><div><span class="pv-name">${esc(k.customer.crm_name)}</span>
      <span class="pv-sub">${PROC[k.current_procedure] || "Insolvency proceedings"} · ${esc(k.customer.city || "")}</span></div>${status(k.status)}</div>
    <div class="pv-stats">
      <div><b class="num ${urg(k.days_left)}">${dday(k.days_left) ?? "—"}</b><span>${k.claim_deadline ? "to file, by " + short(k.claim_deadline) : "deadline to confirm"}</span></div>
      <div><b class="num">${eur(k.declare_cents)}</b><span>to declare</span></div>
      <div class="${found ? "gain" : ""}"><b class="num">${found ? "+" + eur(found) : looked ? "€0" : "—"}</b>
        <span>${found ? "found by the agent" : looked ? "nothing the rules missed" : "the agent has not looked yet"}</span></div>
    </div>
    <ul class="pv-steps">${steps.map(([ok, t]) => `<li class="${ok ? "ok" : ""}">${ico(ok ? "done" : "clock")}<span>${t}</span></li>`).join("")}</ul>
    <span class="pv-cta">${looked ? "Open the case" : "Watch the agent investigate"} ${ico("next")}</span></a>`;
}

async function renderHome() {
  const [d, data, bench] = await Promise.all([loadDash(), api("/api/data").catch(() => null), api("/api/benchmark").catch(() => [])]);
  const pick = d.cases.filter((c) => c.status !== "CLOSED").sort((a, b) => b.exposure_cents - a.exposure_cents)[0];
  const k = pick ? await api(`/api/cases/${pick.id}`).catch(() => null) : null;
  if (S.route.page !== "home") return;
  const n = (x) => Number(x || 0).toLocaleString("en-GB");
  const m = (s) => bench.find((r) => r.split === "holdout" && r.system === s)?.metrics;
  const bars = ["NAIVE", "RULES", "FORCLOS"].filter((s) => m(s));
  const max = Math.max(1, ...bars.map((s) => m(s).eur_lost_cents));
  $("view").innerHTML = `
    <section class="hero"><div class="wrap">
      <span class="hero-pill"><span class="sync-dot"></span>Live · ${data ? `${n(data.bodacc.rows)} insolvency notices read` : "reading the BODACC"}${d.last_sync ? ` · updated ${ago(d.last_sync.finished_at)}` : ""}</span>
      <h1>Your customer is insolvent.<br><span>You have two months.</span></h1>
      <p class="hero-sub">Alerts tell you a customer went under. FORCLOS investigates, finds what you are owed and gets your claim ready to sign before the deadline.</p>
      <div class="hero-cta">${pick ? `<a class="button primary xl" href="#/case/${pick.id}">See it on a live case ${ico("next")}</a>`
        : `<a class="button primary xl" href="#/cases">Open the app ${ico("next")}</a>`}<button class="button xl" data-scroll="how">How it works</button></div>
      ${k ? homePreview(k) : ""}
    </div></section>
    <section class="how" id="how"><div class="wrap">
      <h2 class="sec-h">Three jobs nobody in an SME has time for.</h2>
      <div class="how-grid">
        ${howCard(1, "Watch", "Every insolvency notice published in France, read every 30 minutes.", data ? n(data.bodacc.rows) : "—", "notices read in 45 days")}
        ${howCard(2, "Investigate", "Finds the real company behind each customer record and reads your delivery notes.", data ? n(data.agent.runs) : "—", "investigations so far")}
        ${howCard(3, "Prepare", "The claim, the legal deadline and the protective steps, ready for your signature.", data ? n(data.memory.actions) : "—", "actions prepared")}
      </div></div></section>
    ${bars.length === 3 ? `<section class="proof-band"><div class="wrap">
      <div class="proof-copy"><h2 class="sec-h">Tested on ${m("FORCLOS").n} real insolvent companies.</h2>
        <p>With customer records as messy as real ones. Here is the value of the claims each tool would have let slip.</p>
        <a class="button xl" href="#/proof">See the test ${ico("next")}</a></div>
      <div class="hbars">${bars.map((s) => `<div class="hbar ${s === "FORCLOS" ? "us" : ""}">
        <span class="hbar-label">${{ NAIVE: "Basic alert", RULES: "Rules only", FORCLOS: "FORCLOS" }[s]}</span>
        <span class="hbar-track"><span class="hbar-fill" style="width:${Math.max(1.5, (m(s).eur_lost_cents / max) * 100)}%"></span></span>
        <span class="hbar-value num">${eur(m(s).eur_lost_cents)}</span></div>`).join("")}</div>
    </div></section>` : ""}
    <section class="final"><div class="wrap">
      <h2 class="sec-h">Start with your receivables.</h2>
      <p>Export your aged receivables from your accounting software. FORCLOS checks every customer today and keeps watching every day after.</p>
      <div class="hero-cta"><a class="button primary xl" href="#/import">Import receivables</a><a class="button xl" href="#/cases">Open the app</a></div>
    </div></section>`;
  document.querySelectorAll("[data-scroll]").forEach((b) => b.onclick = () => $(b.dataset.scroll).scrollIntoView({ behavior: "smooth" }));
}

// ---------------------------------------------------------------- cases
function wireResolve(d) {
  document.querySelectorAll("[data-resolve]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    const name = d.customers.find((c) => c.id === +b.dataset.resolve)?.crm_name;
    try {
      const r = await post(`/api/customers/${b.dataset.resolve}/resolve`);
      watchRun(r.run_id, { customerId: +b.dataset.resolve, origin: `Identity check: ${name}` });
      openWorkflow(r.run_id);
    } catch (e) { toast(e.message); b.disabled = false; }
  });
}

async function renderCases() {
  const [d, recent] = await Promise.all([loadDash(), api("/api/runs?limit=3").catch(() => [])]);
  if (S.route.page !== "cases") return;
  const open = d.cases.filter((c) => c.status !== "CLOSED");
  const noId = d.customers.filter((c) => !c.crm_siren && c.identity_status !== "VERIFIED" && !c.has_case);
  const running = recent.find(liveRun);
  const rows = d.cases.map((c) => `<a class="case-row" href="#/case/${c.id}">
      <span><b>${esc(c.customer.crm_name)}</b><span>${esc(title(c.denomination || ""))} · ${PROC[c.procedure] || "—"}</span></span>
      <span class="case-dl ${urg(c.days_left)}"><b class="num">${dday(c.days_left) ?? "Review"}</b><span>${c.claim_deadline ? "file by " + fr(c.claim_deadline) : "no deadline yet"}</span></span>
      <span class="case-amt"><b class="num">${eur(c.declare_cents)}</b><span>to declare</span></span>
      <span class="case-st">${status(c.status)}</span><span class="chev">${ico("next")}</span></a>`).join("");
  $("view").innerHTML = `<section class="page">
    <div class="page-head"><div><h1>Cases</h1>
      <p class="lead">${open.length ? `${open.length} of your customers ${open.length === 1 ? "is" : "are"} in insolvency proceedings.` : "None of your customers is in insolvency proceedings."}</p></div>
      <div class="button-row"><a class="button" href="#/import">Import receivables</a><button class="button primary" id="btn-add">Add a customer</button></div></div>
    ${running ? `<button class="live-banner" data-run="${running.id}"><span class="live"></span><span>The agent is working on <b>${esc(running.crm_name)}</b></span><span class="go">Watch it think →</span></button>` : ""}
    <div class="stats3">
      <div class="stat-card"><span class="label">To declare</span><b class="big num">${eur(d.declare_cents)}</b><span class="hint">owed to you before the judgments</span></div>
      <div class="stat-card ${urg(d.nearest_days_left)}"><span class="label">Next deadline</span><b class="big num">${dday(d.nearest_days_left) ?? "—"}</b><span class="hint">${d.nearest_deadline ? fr(d.nearest_deadline) : "nothing open"}</span></div>
      <div class="stat-card"><span class="label">Customers in proceedings</span><b class="big num">${d.customers_at_risk}</b><span class="hint">of ${d.customers.length} customers watched</span></div>
    </div>
    <div class="case-list">${rows || '<p class="empty">No customer matches a BODACC notice.</p>'}</div>
    ${noId.length ? `<div class="check-card"><div><b>${noId.length} customer${noId.length === 1 ? " has" : "s have"} no company ID</b>
      <p>A basic alert cannot see them. The agent can find them.</p></div>
      <div class="chips">${noId.map((c) => `<button class="chip-btn" data-resolve="${c.id}">Find ${esc(c.crm_name)}</button>`).join("")}</div></div>` : ""}
  </section>`;
  $("btn-add").onclick = openModal;
  document.querySelectorAll(".live-banner[data-run]").forEach((b) => b.onclick = () => openWorkflow(b.dataset.run));
  wireResolve(d);
}

// ---------------------------------------------------------------- case
const CLAIM = { DECLARE: ["green", "In the claim"], POST_OPENING: ["gray", "Not in the claim"], REVIEW: ["amber", "To review"], PAID: ["gray", "Paid"] };
const claimChip = (s) => { const [c, l] = CLAIM[s] || ["gray", "Not checked"]; return `<span class="status ${c}">${l}</span>`; };
const VERB = { DELIVERY: "Delivered", SERVICE_PERFORMED: "Service performed", ORDER_ACCEPTANCE: "Order accepted", CONTRACT_CONCLUSION: "Contract signed" };

async function renderCase() {
  const id = S.route.id;
  const c = await api(`/api/cases/${id}`);
  if (S.route.page !== "case" || S.route.id !== id) return;
  S.case = c;
  if (!$("case-root") || $("case-root").dataset.id !== String(id)) S.seenCats = {};
  const found = agentFound(c), running = liveRun(c.latest_run);
  const naiveLate = c.naive_deadline && c.claim_deadline && c.naive_deadline > c.claim_deadline
    ? Math.round((day(c.naive_deadline) - day(c.claim_deadline)) / 864e5) : 0;
  const unpaid = c.invoices.filter((i) => i.outstanding_cents > 0);
  const declared = unpaid.filter((i) => i.category === "DECLARE");
  const invoices = unpaid.map((i) => {
    const flipped = S.seenCats[i.id] && S.seenCats[i.id] !== i.category;
    S.seenCats[i.id] = i.category;
    const gain = i.changed && i.category === "DECLARE" && i.previous?.category !== "DECLARE";
    const when = i.category === "DECLARE" ? ", before the judgment" : i.category === "POST_OPENING" ? ", after the judgment" : "";
    const why = i.decided_by === "AGENT"
      ? (i.fait_generateur ? `${VERB[i.basis] || "Dated"} ${short(i.fait_generateur)}${when}${i.evidence_document_id ? ` · document #${i.evidence_document_id}` : ""}` : esc(i.rationale || "Evidence missing"))
      : i.category ? `Invoice dated ${short(i.invoice_date)}${when}` : "Not checked yet";
    return `<div class="inv ${gain ? "gain" : ""} ${flipped ? "flash" : ""}">
      <span class="inv-no"><b class="mono">${esc(i.number)}</b><span>invoiced ${short(i.invoice_date)}</span></span>
      <span class="inv-amt num">${eur(i.outstanding_cents)}</span>
      <span class="inv-cat">${claimChip(i.category)}${i.decided_by ? who(i.decided_by) : ""}</span>
      <span class="inv-why">${why}${gain ? `<span class="gain-text">+${eur(i.outstanding_cents)} found by the agent</span>` : ""}</span></div>`;
  }).join("");
  const timeline = c.timeline.map((n) => `<div class="tl-item ${n.is_anchor ? "anchor" : ""}"><div class="tl-dot"></div><div>
      <div class="tl-title">${KIND[n.event_kind] || n.event_kind}${n.procedure ? " · " + (PROC[n.procedure] || n.procedure) : ""}
        ${n.is_anchor ? '<span class="status gray">The deadline counts from here</span>' : ""}
        ${n.event_kind === "CONVERSION" ? '<span class="status amber">Does not restart the deadline</span>' : ""}</div>
      <div class="tl-meta">Published ${fr(n.date_parution)} · judgment of ${fr(n.jugement_date)}${n.url ? ` · <a target="_blank" rel="noopener" href="${esc(n.url)}">bodacc.fr</a>` : ""}</div></div></div>`).join("");
  $("view").innerHTML = `<div id="case-root" data-id="${id}" class="page">
    <a class="back" href="#/cases">${ico("back")}Cases</a>
    <div class="case-grid"><div>
      <div class="page-head" style="margin-bottom:22px"><div><h1>${esc(c.customer.crm_name)}</h1>
        <p class="lead">${esc(title(c.denomination || ""))} · ${PROC[c.current_procedure] || "insolvency proceedings"} · SIREN ${esc(c.siren)}</p></div>${status(c.status)}</div>
      <div class="stats3">
        <div class="stat-card ${urg(c.days_left)}"><span class="label">Deadline</span><b class="big num">${dday(c.days_left) ?? "Review"}</b>
          <span class="hint">${c.claim_deadline ? "file by " + fr(c.claim_deadline) : "no opening judgment found"}</span></div>
        <div class="stat-card"><span class="label">To declare</span><b class="big num">${eur(c.declare_cents)}</b>
          <span class="hint">${declared.length} of ${unpaid.length} unpaid invoice${unpaid.length === 1 ? "" : "s"}</span></div>
        <div class="stat-card ${found ? "gain" : ""}"><span class="label">Found by the agent</span><b class="big num">${found ? "+" + eur(found) : c.latest_run ? "€0" : "—"}</b>
          <span class="hint">${found ? "a rules engine would have left it out" : c.latest_run ? "the rules had it right" : "not investigated yet"}</span></div>
      </div>
      ${naiveLate > 0 ? `<div class="warn">${ico("alert")}<span>A basic alert restarts the clock at the latest notice and says <b>${fr(c.naive_deadline)}</b>. That is <b>${naiveLate} days too late</b>.</span></div>` : ""}
      <div class="button-row" style="margin-top:22px">
        <button class="button primary xl" id="btn-run" ${running ? "disabled" : ""}>${running ? "Investigating…" : c.latest_run ? "Investigate again" : "Let the agent investigate"}</button>
        ${c.latest_run ? `<button class="button xl" id="btn-watch">${ico("play")}Watch the last run</button>` : ""}</div>
      <h2 class="block-h">Invoices</h2>
      <div class="inv-list">${invoices || '<p class="empty">No unpaid invoice.</p>'}</div>
      <details class="evidence" id="doc-form" ${S.docOpen ? "open" : ""}><summary>Add a delivery note</summary><div class="evidence-in">
        <label class="field"><span>Invoice</span><select id="doc-invoice">${unpaid.map((i) => `<option value="${i.id}">${esc(i.number)} · invoiced ${short(i.invoice_date)} · ${eur(i.outstanding_cents)}</option>`).join("")}</select></label>
        <label class="field"><span>Delivery date</span><input id="doc-date" type="date"></label>
        <label class="field"><span>Text of the note</span><textarea id="doc-body" rows="3"></textarea></label>
        <div class="button-row end"><button class="button primary" id="btn-doc">Add and re-investigate</button></div></div></details>
      <h2 class="block-h">Official notices</h2>
      <div class="timeline">${timeline}</div>
    </div><aside class="side" id="actions"></aside></div></div>`;
  wireDocForm(c);
  renderActions(c);
  $("btn-run").onclick = async () => {
    $("btn-run").disabled = true;
    try {
      const r = await post(`/api/cases/${c.id}/investigate`, { trigger: "Investigation requested from the dashboard." });
      watchRun(r.run_id, { caseId: c.id, origin: c.customer.crm_name });
      openWorkflow(r.run_id);
    } catch (e) { toast(e.message); $("btn-run").disabled = false; }
  };
  if ($("btn-watch")) $("btn-watch").onclick = () => openWorkflow(c.latest_run.id);
  if (running && S.trail.runId !== c.latest_run.id) watchRun(c.latest_run.id, { caseId: c.id, origin: c.customer.crm_name });
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
      if (r.run_id) { watchRun(r.run_id, { caseId: c.id, origin: `${c.customer.crm_name}, new evidence` }); openWorkflow(r.run_id); }
    } catch (e) { toast(e.message); $("btn-doc").disabled = false; }
  };
}

function renderActions(c) {
  const by = Object.fromEntries(c.actions.map((a) => [a.kind, a]));
  const out = [];
  const claim = by.CLAIM_DRAFT;
  if (claim) {
    const p = claim.payload, ready = claim.status === "APPLIED";
    out.push(`<div class="act-card ${ready ? "ready" : ""}">
      <div class="act-top"><span class="act-title">${ico("clipboard")}Claim draft</span>${ready ? '<span class="status green">Ready to sign</span>' : '<span class="status gray">Not sent</span>'}</div>
      <b class="act-amount num">${eur(p.total_cents)}</b>
      <p class="act-text">To ${esc(p.officer?.name || "the mandataire judiciaire")}, by <b>${fr(p.claim_deadline)}</b>.</p>
      <div class="button-row"><a class="button small" target="_blank" href="/api/actions/${claim.id}/claim.txt">Open the draft</a>
        ${ready ? "" : `<button class="button small primary" data-apply="${claim.id}">Mark ready to sign</button>`}</div></div>`);
  }
  const cash = by.PAYMENT_TERMS_CASH;
  if (cash) {
    const done = cash.status === "APPLIED";
    out.push(`<div class="act-card"><div class="act-top"><span class="act-title">${ico("done")}New deliveries</span>${done ? '<span class="status green">Cash on delivery</span>' : ""}</div>
      <p class="act-text">Keep supplying, and get paid on delivery from now on.</p>
      ${done ? "" : `<div class="button-row"><button class="button small" data-apply="${cash.id}">Switch to cash on delivery</button></div>`}</div>`);
  }
  const rev = by.REVENDICATION_ALERT;
  if (rev) out.push(`<div class="act-card"><div class="act-top"><span class="act-title">${ico("flag")}Reclaim your goods</span><span class="status amber">by ${short(rev.payload.deadline)}</span></div>
      <p class="act-text">Your retention-of-title clause lets you take back unsold goods until <b>${fr(rev.payload.deadline)}</b>.</p></div>`);
  const law = by.LAWYER_REVIEW;
  if (law) out.push(`<div class="act-card review"><div class="act-top"><span class="act-title">${ico("alert")}For your lawyer</span><span class="status amber">${law.payload.reasons.length}</span></div>
      ${law.payload.reasons.map((r) => `<p class="act-text">${esc(r)}</p>`).join("")}</div>`);
  if (!out.length) out.push(`<div class="act-card empty"><span class="act-title">Nothing prepared yet</span>
      <p class="act-text">Let the agent investigate. It prepares the claim and the protective steps for your signature.</p></div>`);
  $("actions").innerHTML = `<h2 class="block-h">Ready for you</h2>${out.join("")}`;
  document.querySelectorAll("[data-apply]").forEach((b) => b.onclick = async () => {
    b.disabled = true; await post(`/api/actions/${b.dataset.apply}/apply`); renderCase(false);
  });
}

// ---------------------------------------------------------------- background run watcher
function watchRun(runId, { caseId = null, customerId = null, origin = "" } = {}) {
  S.trail = { runId, after: 0, status: "RUNNING", origin, caseId, customerId };
  pollRun(runId);
}

async function pollRun(runId) {
  if (S.trail.runId !== runId) return;
  let r;
  try { r = await api(`/api/runs/${runId}/steps?after=${S.trail.after}`); } catch { setTimeout(() => pollRun(runId), 1500); return; }
  if (S.trail.runId !== runId) return;
  if (r.steps.length) {
    S.trail.after = r.steps[r.steps.length - 1].id;
    const touched = r.steps.some((s) => s.kind === "TOOL_RESULT" && ["record_claim_classification", "compute_deadlines",
      "propose_actions", "record_identity", "flag_lawyer_review", "finish"].includes(s.tool));
    if (touched) refreshAfterStep(r);
  }
  const running = liveRun(r);
  S.trail.status = running ? "RUNNING" : r.stalled ? "INTERRUPTED" : r.status;
  if (running) setTimeout(() => pollRun(runId), 900);
  else refreshAfterStep(r);
}

function refreshAfterStep(r) {
  loadDash().catch(() => {});
  if (S.wf) return;
  if (S.route.page === "case" && S.route.id === (r.case_id || S.trail.caseId)) renderCase().catch(() => {});
  else if (S.route.page === "customers") renderCustomers().catch(() => {});
  else if (S.route.page === "cases") renderCases().catch(() => {});
}

// ---------------------------------------------------------------- agent workflow view
const ICONS = {
  folder: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>',
  doc: '<path d="M14 3H7.5A2.5 2.5 0 0 0 5 5.5v13A2.5 2.5 0 0 0 7.5 21h9a2.5 2.5 0 0 0 2.5-2.5V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  building: '<path d="M5 21V5.5A2.5 2.5 0 0 1 7.5 3h6A2.5 2.5 0 0 1 16 5.5V21M16 10h2.5a1.5 1.5 0 0 1 1.5 1.5V21M3 21h18M9 7h3M9 11h3M9 15h3"/>',
  news: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h10A1.5 1.5 0 0 1 17 5.5V19a2 2 0 0 0 2 2H6a2 2 0 0 1-2-2z"/><path d="M17 9h2.5a.5.5 0 0 1 .5.5V19a2 2 0 0 1-2 2M8 8.5h5M8 12.5h5M8 16.5h3"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  scale: '<path d="M12 4v16M8 20h8M5 7h14M7 7l-3 6.5a3 3 0 0 0 6 0zM17 7l-3 6.5a3 3 0 0 0 6 0z"/>',
  clipboard: '<rect x="5.5" y="4.5" width="13" height="16.5" rx="2.5"/><path d="M9 4.5V3.5h6v1M9 11h6M9 15h4"/>',
  flag: '<path d="M5.5 21V4M5.5 4.5h11l-2.2 4 2.2 4h-11"/>',
  done: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/>',
  check: '<path d="m6 12.5 4 4 8-9"/>',
  spark: '<path d="M12 3.5 13.7 9 19 10.5l-5.3 1.6L12 17.5l-1.7-5.4L5 10.5 10.3 9z"/><path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
  alert: '<circle cx="12" cy="12" r="8.5"/><path d="M12 8v4.5M12 16h.01"/>',
  db: '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  back: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  prev: '<path d="m14.5 18-6-6 6-6"/>',
  next: '<path d="m9.5 18 6-6-6-6"/>',
  play: '<path d="M8 5.5v13l10-6.5z"/>',
  expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5"/>',
};
const ico = (n) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ICONS.spark}</svg>`;
const STAGES = [
  { key: "file", label: "Customer file", sub: "CRM record, invoices, documents" },
  { key: "identity", label: "Legal entity", sub: "register: name, address, active status" },
  { key: "bodacc", label: "BODACC history", sub: "every notice published for the SIREN" },
  { key: "deadlines", label: "Deadlines", sub: "code: art. 641 and 642 CPC" },
  { key: "invoices", label: "Invoices", sub: "fait générateur, from the documents" },
  { key: "actions", label: "Actions", sub: "claim draft, cash terms, alerts" },
  { key: "report", label: "Report", sub: "status for your sign-off" },
];
const TOOL = {
  get_customer_file: { app: "Customer file", icon: "folder", stage: "file" },
  read_document: { app: "Document reader", icon: "doc", stage: "invoices" },
  search_company: { app: "Company register", icon: "search", stage: "identity" },
  get_company: { app: "Company register", icon: "building", stage: "identity" },
  get_bodacc_history: { app: "BODACC", icon: "news", stage: "bodacc" },
  record_identity: { app: "Identity decision", icon: "person", stage: "identity" },
  compute_deadlines: { app: "Legal engine", icon: "clock", stage: "deadlines" },
  record_claim_classification: { app: "Legal engine", icon: "scale", stage: "invoices" },
  propose_actions: { app: "Claim builder", icon: "clipboard", stage: "actions" },
  flag_lawyer_review: { app: "Escalation", icon: "flag", stage: "actions" },
  finish: { app: "Report", icon: "done", stage: "report" },
};
const DOC_KIND = { DELIVERY_NOTE: "delivery note", ORDER: "order", PAYMENT: "payment advice", CONTRACT: "contract" };
const BASIS = { DELIVERY: "delivery", SERVICE_PERFORMED: "service performed", ORDER_ACCEPTANCE: "order accepted",
                CONTRACT_CONCLUSION: "contract signed", INVOICE_DATE: "invoice date" };
const IDENT = { VERIFIED: "Verified", REVIEW: "Review", NOT_FOUND: "Not found", UNVERIFIED: "Unverified" };
const RUN_END = { READY: "Ready for sign-off", NEEDS_REVIEW: "Needs review", NO_CASE: "No proceedings", IDENTITY_RESOLVED: "Identity resolved" };
const ACTION = { CLAIM_DRAFT: "Claim draft (déclaration de créance)", PAYMENT_TERMS_CASH: "Cash on delivery for new deliveries",
                 REVENDICATION_ALERT: "Reclaim goods (revendication)", LAWYER_REVIEW: "Lawyer review" };
const secs = (ms) => ms == null ? "—" : ms < 1000 ? `${Math.max(0, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
const ts = (t) => new Date(t).getTime();
const cap = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
const liveRun = (r) => !!r && r.status === "RUNNING" && !r.stalled;
const runState = (r) => r.stalled ? ["amber", "Interrupted"] : r.status === "RUNNING" ? ["running", "Live"]
  : r.status === "ERROR" ? ["red", "Error"] : ["green", "Done"];
const deliveryLine = (body) => (body || "").match(/Date de livraison\s*:\s*[0-9/]+/)?.[0] || null;

function wfModel(w) {
  const run = w.run, steps = w.replay ? w.steps.slice(0, w.replay.cut) : w.steps;
  const actions = [], turns = [];
  let turn = null, lastAt = ts(run.started_at), lastKind = null, identity = false;
  const open = (at) => { turn = { k: turns.length, think: Math.max(0, at - lastAt), notes: [], acts: [] }; turns.push(turn); };
  for (const s of steps) {
    const at = ts(s.created_at);
    if (s.kind === "TOOL_RESULT" || (s.kind === "ERROR" && s.tool)) {
      const a = [...actions].reverse().find((x) => x.tool === s.tool && !x.res);
      if (a) { a.res = s; a.ms = at - a.at; }
    } else if (s.kind === "NOTE") {
      if (!turn || lastKind !== "NOTE") open(at);
      turn.notes.push({ text: s.payload?.text || "" });
    } else if (s.kind === "TOOL_CALL") {
      if (!turn || (lastKind !== "NOTE" && at - lastAt > 400)) open(at);
      const stage = s.tool === "read_document" && run.task === "RESOLVE_IDENTITY" && !identity ? "identity" : TOOL[s.tool]?.stage || "report";
      if (s.tool === "record_identity") identity = true;
      const a = { i: actions.length, id: s.id, tool: s.tool, p: s.payload || {}, res: null, at, ms: null, stage };
      actions.push(a); turn.acts.push(a);
    } else if (s.kind === "ERROR") {
      if (!turn) open(at);
      turn.notes.push({ text: `Error: ${s.payload?.error || "the run failed"}`, error: true });
    }
    lastAt = at; lastKind = s.kind;
  }
  return { actions, turns, lastAt, n: steps.length };
}
const lastRes = (m, tool) => [...m.actions].reverse().find((a) => a.tool === tool && a.res?.kind === "TOOL_RESULT");
const chosenSiren = (m) => [...m.actions].reverse().find((a) => a.tool === "record_identity" && a.p.status === "VERIFIED")?.p.siren || null;
const anchorId = (m) => lastRes(m, "compute_deadlines")?.res.payload.anchor_notice_id || null;
const docFromRun = (m, id) => m.actions.find((a) => a.tool === "read_document" && a.res?.payload?.id === id)?.res.payload || null;
const invNo = (a, m, w) => a.res?.payload?.number
  || lastRes(m, "get_customer_file")?.res.payload.invoices?.find((i) => i.id === a.p.invoice_id)?.number
  || w.kase?.invoices?.find((i) => i.id === a.p.invoice_id)?.number || `#${a.p.invoice_id}`;
const wfLive = (w) => !!w.replay || liveRun(w.run);
const wfNow = (w) => w.replay ? w.replay.base.virt + (Date.now() - w.replay.base.real) : Date.now() + (w.offset || 0);

function actTitle(a, m, w) {
  const p = a.p;
  switch (a.tool) {
    case "get_customer_file": return "Opens the customer file";
    case "read_document": { const k = a.res?.payload?.kind; return `Reads ${DOC_KIND[k] || "document"} #${esc(p.document_id)}`; }
    case "search_company": return `Searches the company register for “${esc(p.query)}”${p.postal_code ? ` in ${esc(p.postal_code)}` : ""}`;
    case "get_company": return `Looks up SIREN ${esc(p.siren)} in the register`;
    case "get_bodacc_history": return `Reads the BODACC history of SIREN ${esc(p.siren)}`;
    case "record_identity": return `Identity <b>${esc((IDENT[p.status] || p.status || "").toLowerCase())}</b>${p.siren ? ` · SIREN ${esc(p.siren)}` : ""}`;
    case "compute_deadlines": return "Asks the legal engine for the deadlines";
    case "record_claim_classification": return `Invoice ${esc(invNo(a, m, w))} arose on <b>${p.fait_generateur_date ? fr(p.fait_generateur_date) : "an unknown date"}</b>
      · ${esc(BASIS[p.basis] || p.basis || "")}${p.evidence_document_id ? ` · doc #${esc(p.evidence_document_id)}` : ""}`;
    case "propose_actions": return "Prepares the protective actions";
    case "flag_lawyer_review": return "Escalates to a lawyer";
    case "finish": return `Final report: <b>${esc(RUN_END[p.status] || p.status)}</b>`;
  }
  return esc(a.tool);
}

function actResult(a, m) {
  const r = a.res.payload || {}, p = a.p, plural = (n, s) => `${n} ${s}${n === 1 ? "" : "s"}`;
  switch (a.tool) {
    case "get_customer_file": { const c = r.customer || {}, unpaid = (r.invoices || []).filter((i) => i.outstanding_cents > 0);
      return `${esc(c.crm_name)} · CRM SIREN ${esc(c.crm_siren || "none")} · ${esc(c.postal_code || "")} ${esc(c.city || "")} · ${plural(unpaid.length, "unpaid invoice")}, ${plural((r.documents || []).length, "document")}`; }
    case "read_document": { const d = deliveryLine(r.body);
      return d ? `<b>${esc(d.replace("Date de livraison", "Delivered"))}</b>${r.invoice_id ? ` · invoice #${r.invoice_id}` : ""}`
        : `${esc(cap(DOC_KIND[r.kind] || r.kind || "document"))}${r.doc_date ? " dated " + short(r.doc_date) : ""}`; }
    case "search_company": { const x = r.results || [];
      return x.length ? `${plural(x.length, "result")} · ${x.slice(0, 2).map((c) => `${esc(title(c.nom_complet || ""))} (${c.etat_administratif === "A" ? "active" : "ceased"}, ${esc(c.siege?.code_postal || "")})`).join(" · ")}` : "No match"; }
    case "get_company": { const c = r.company;
      return c ? `${esc(title(c.nom_complet || ""))} · ${c.etat_administratif === "A" ? "active" : "ceased"} · ${esc(c.siege?.code_postal || "")} ${esc(title(c.siege?.commune || ""))}` : esc(r.note || "Not found"); }
    case "get_bodacc_history": { const n = r.notices || [];
      return n.length ? n.map((x) => `${KIND[x.event_kind] || esc(x.event_kind)}${x.procedure ? " " + (PROC[x.procedure] || esc(x.procedure)) : ""} (${short(x.date_parution)})`).join(" → ") : "No collective-procedure notice"; }
    case "record_identity": return `${who("RULE")} ${esc(r.note || (r.case_id ? "Case opened." : "No case."))}`;
    case "compute_deadlines": return r.claim_deadline ? `${who("RULE")} File by <b>${fr(r.claim_deadline)}</b> · ${dday(r.days_left)} · anchored on the opening published ${fr(r.anchor_publication)}`
      : `${who("RULE")} ${esc((r.notes || []).join(" ") || "No opening judgment in the history")}`;
    case "record_claim_classification": {
      const was = r.changed && r.previous_category ? `<span class="was-inline">was ${esc((CAT[r.previous_category]?.[1] || r.previous_category).toLowerCase())}</span>` : "";
      const d = r.declare_delta_cents > 0 ? `<span class="gain">+${eur(r.declare_delta_cents)} added to claim</span>`
        : r.declare_delta_cents < 0 ? `<span class="loss">−${eur(-r.declare_delta_cents)} removed from claim</span>` : "";
      return `${who("RULE")} ${cat(r.category)} ${was} ${d}`; }
    case "propose_actions": return `${who("RULE")} ` + ((r.actions || []).map((x) => x.kind === "CLAIM_DRAFT" ? `claim draft <b>${esc(x.total)}</b>`
      : x.kind === "PAYMENT_TERMS_CASH" ? "cash on delivery" : x.kind === "REVENDICATION_ALERT" ? `reclaim goods by ${short(x.deadline)}` : esc(x.kind)).join(" · ")
      || esc((r.warnings || []).join(" ") || "nothing to prepare"));
    case "flag_lawyer_review": return plural((r.reasons || []).length, "item") + " for the lawyer";
    case "finish": return esc(p.summary || r.summary || "");
  }
  return "";
}

function wfActHtml(a, m, w) {
  const t = TOOL[a.tool] || { icon: "spark" }, err = a.res?.kind === "ERROR";
  const kind = { record_identity: "decision", record_claim_classification: "decision", flag_lawyer_review: "flag", finish: "final",
                 compute_deadlines: "rule", propose_actions: "rule" }[a.tool] || "read";
  const badge = ["decision", "flag", "final"].includes(kind) ? who("AGENT") : "";
  const quote = { record_identity: a.p.evidence, record_claim_classification: a.p.rationale, flag_lawyer_review: a.p.reason }[a.tool];
  const res = !a.res ? '<span class="wf-spin"></span>working…' : err ? esc(a.res.payload?.error || "Tool error") : actResult(a, m);
  return `<button class="wf-act ${kind} ${err ? "err" : ""} ${w.seen.has(a.id) ? "" : "fresh"}" data-wf="act" data-i="${a.i}">
    <span class="wf-act-ico">${ico(t.icon)}</span>
    <span class="wf-act-main"><span class="wf-act-title">${actTitle(a, m, w)}</span><span class="wf-act-res">${res}</span>
      ${quote ? `<span class="wf-quote">${esc(quote)}</span>` : ""}</span>
    <span class="wf-act-side">${badge}<span class="wf-dur">${a.res ? secs(a.ms) : ""}</span></span></button>`;
}

const wfTurnSig = (t, w) => `${t.notes.length}.${t.acts.map((a) => (a.res ? 2 : 1)).join("")}.${w.kase ? 1 : 0}`;
function wfTurnHtml(t, m, w) {
  const notes = t.notes.map((n) => `<div class="wf-note ${n.error ? "error" : ""}">${esc(n.text)}</div>`).join("");
  return `<div class="wf-turn" id="wf-turn-${t.k}" data-sig="${wfTurnSig(t, w)}">
    <div class="wf-think">${ico("spark")}<span>Thought for ${secs(t.think)}</span></div>${notes}
    ${t.acts.length ? `<div class="wf-acts">${t.acts.map((a) => wfActHtml(a, m, w)).join("")}</div>` : ""}</div>`;
}

function wfTaskHtml(run) {
  const text = (run.prompt || "").replace(/^Task \w+(?: \w+=\d+)*\.\s*/, "") || (run.task === "RESOLVE_IDENTITY"
    ? "Read the customer file and the delivery addresses in its documents, find the legal entity in the official register, record the identity, then check the BODACC history for the verified SIREN. If a case opens, investigate it in the same run."
    : "Confirm the identity, get the full BODACC history, compute deadlines, classify every unpaid invoice from its documents, propose actions, escalate what is out of scope, finish.");
  return `<div class="wf-task"><p class="eyebrow">Task given to the agent</p><p>${esc(text)}</p>
    <p class="wf-rules">${who("AGENT")} supplies evidence, with ids · ${who("RULE")} code applies the law: dates, categories, amounts</p></div>`;
}

const wfChip = (label, value, sub, tone = "", key = "") => `<div class="wf-chip ${tone}" ${key ? `data-key="${key}"` : ""}>
  <p class="eyebrow">${label}</p><div class="v num">${esc(value)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>`;

function wfHeadHtml(m, w) {
  const run = w.run;
  const [tone, label] = w.replay ? ["replay", "Replay · recorded run"] : runState(run);
  const name = w.kase?.customer?.crm_name || run.crm_name || "customer";
  const trig = run.trigger || (run.task === "RESOLVE_IDENTITY" ? "Identity check requested" : "Investigation requested");
  const auto = /automatic sync|at import/i.test(trig);
  const chips = [];
  const idr = lastRes(m, "record_identity");
  if (idr?.res.payload.case_id) chips.push(wfChip("BODACC", idr.res.payload.case_created ? "Case opened" : "In proceedings", "collective procedure", "red"));
  else if (idr) chips.push(wfChip("Identity", IDENT[idr.p.status] || idr.p.status, idr.p.siren ? `SIREN ${idr.p.siren}` : "", idr.p.status === "VERIFIED" ? "green" : "amber"));
  const dl = lastRes(m, "compute_deadlines")?.res.payload;
  if (dl) chips.push(wfChip("Claim deadline", dl.claim_deadline ? dday(dl.days_left) : "Review", dl.claim_deadline ? fr(dl.claim_deadline) : "no opening found",
                            dl.claim_deadline && dl.days_left < 15 ? "red" : ""));
  const cls = m.actions.filter((a) => a.tool === "record_claim_classification" && a.res?.kind === "TOOL_RESULT");
  const delta = cls.reduce((t, a) => t + (a.res.payload.declare_delta_cents || 0), 0);
  const first = w.steps.find((s) => s.kind === "TOOL_RESULT" && s.tool === "record_claim_classification")?.payload;
  const before = first ? first.case_declare_cents - (first.declare_delta_cents || 0) : run.case_id && w.kase ? w.kase.declare_cents : null;
  const declare = cls.length ? cls[cls.length - 1].res.payload.case_declare_cents : before;
  if (declare != null) chips.push(wfChip("To declare", eur(declare), delta ? `${delta > 0 ? "+" : "−"}${eur(Math.abs(delta))} this run` : "pre-opening, with evidence",
                                         delta > 0 ? "gain" : "", "declare"));
  return `
    <button class="button small soft" data-wf="close" title="Close (Esc)">${ico("back")}Back</button>
    <div class="wf-titles">
      <p class="eyebrow"><span class="wf-state ${tone}">${label}</span>${run.task === "RESOLVE_IDENTITY" ? "Identity check" : "Investigation"} · ${esc(run.model || "")}</p>
      <h2>${run.task === "RESOLVE_IDENTITY" ? "Identity check: " : "Investigating "}${esc(name)}</h2>
      <p class="wf-sub">${auto ? '<span class="wf-auto">Started by itself</span>' : ""}<span>${esc(trig)}</span><span>· started ${new Date(run.started_at).toLocaleTimeString("en-GB")}</span>
        <span>· <span id="wf-elapsed" class="num"></span></span>${run.input_tokens ? `<span>· ${(run.input_tokens + run.output_tokens).toLocaleString("en-GB")} tokens</span>` : ""}</p>
    </div>
    <div class="wf-impact">${chips.join("")}${run.case_id ? '<button class="button small" data-wf="case">Open case</button>' : ""}</div>`;
}

function wfStagesHtml(m, w) {
  const run = w.run, live = wfLive(w);
  const reached = new Set(m.actions.map((a) => a.stage));
  const cur = live && m.actions.length ? m.actions[m.actions.length - 1].stage : null;
  const idr = lastRes(m, "record_identity");
  const noCase = run.task === "RESOLVE_IDENTITY" && ((idr && !idr.res.payload.case_id) || (!live && !run.case_id));
  const st = STAGES.map((s) => {
    let state = reached.has(s.key) ? "done" : "todo";
    if (s.key === cur) state = "active";
    if (state === "todo" && (!live || (noCase && ["deadlines", "invoices", "actions"].includes(s.key)))) state = "skipped";
    return { ...s, state, first: m.actions.find((a) => a.stage === s.key)?.i };
  });
  const total = st.filter((s) => s.state !== "skipped").length, done = st.filter((s) => s.state === "done").length;
  return `<div class="wf-progress"><b class="num">${done}/${total}</b> stages</div>` + st.map((s, k) => `${k ? '<span class="wf-sep"></span>' : ""}
    <button class="wf-stage ${s.state}" data-wf="stage" data-i="${s.first ?? ""}" title="${esc(s.sub)}" ${s.first == null ? "disabled" : ""}>
      <span class="wf-dot">${s.state === "done" ? ico("check") : s.state === "active" ? '<span class="wf-spin"></span>' : k + 1}</span><span class="wf-stage-label">${esc(s.label)}</span></button>`).join("");
}

const companyCard = (c, chosen) => `<div class="wf-co ${c.siren === chosen ? "chosen" : ""}">
  <div class="wf-co-head"><b>${esc(title(c.nom_complet || c.nom_raison_sociale || ""))}</b>
    <span class="status ${c.etat_administratif === "A" ? "green" : "red"}">${c.etat_administratif === "A" ? "Active" : "Ceased"}</span>
    ${c.siren === chosen ? '<span class="who agent">CHOSEN BY THE AGENT</span>' : ""}</div>
  <div class="wf-co-meta mono">SIREN ${esc(c.siren)}</div><div class="wf-co-meta">${esc(c.siege?.adresse || "")}</div>
  ${(c.enseignes || []).length ? `<div class="wf-co-meta">Trade name${c.enseignes.length > 1 ? "s" : ""}: ${c.enseignes.map(esc).join(", ")}</div>` : ""}
  ${c.sigle ? `<div class="wf-co-meta">Acronym: ${esc(c.sigle)}</div>` : ""}
  ${(c.matching_etablissements || []).filter((e) => e.adresse && e.adresse !== c.siege?.adresse).slice(0, 2)
    .map((e) => `<div class="wf-co-meta">Establishment: ${esc(e.adresse)}${(e.enseignes || []).length ? " · " + e.enseignes.map(esc).join(", ") : ""}</div>`).join("")}</div>`;

const WF_BODY = {
  get_customer_file: (p, r) => { const c = r.customer || {};
    return `<div class="wf-kv"><span>Name in the CRM</span><b>${esc(c.crm_name)}</b>
        <span>SIREN as typed</span><b class="mono">${esc(c.crm_siren || "none")}</b>
        <span>Address</span><b>${esc([c.address, [c.postal_code, c.city].filter(Boolean).join(" ")].filter(Boolean).join(", ") || "—")}</b>
        <span>Identity</span><b>${esc(IDENT[c.identity_status] || c.identity_status || "—")}${c.verified_siren ? ` · ${esc(c.verified_siren)}` : ""}</b>
        <span>Payment terms</span><b>${c.payment_terms === "CASH" ? "Cash on delivery" : "30 days"}</b></div>
      ${(r.contracts || []).length ? `<p class="wf-h">Contracts</p><div class="wf-chips">${r.contracts.map((k) => `<span class="status gray">${esc(cap((k.kind || "").replace(/_/g, " ").toLowerCase()))}</span>
        ${k.retention_of_title ? '<span class="status amber">Retention of title</span>' : ""}${k.published_security ? '<span class="status red">Published security</span>' : ""}`).join("")}</div>` : ""}
      <p class="wf-h">Invoices</p>
      <table class="table wf-table"><thead><tr><th>Invoice</th><th>Invoiced</th><th>Due</th><th class="right">Unpaid</th></tr></thead><tbody>
        ${(r.invoices || []).map((i) => `<tr><td class="mono">${esc(i.number)}</td><td class="num">${short(i.invoice_date)}</td><td class="num">${short(i.due_date)}</td>
          <td class="right num">${eur(i.outstanding_cents)}</td></tr>`).join("")}</tbody></table>
      ${(r.documents || []).length ? `<p class="wf-h">Documents</p><div class="wf-chips">${r.documents.map((d) =>
        `<span class="wf-doc">${ico("doc")}#${d.id} ${esc(DOC_KIND[d.kind] || d.kind)}${d.doc_date ? " · " + short(d.doc_date) : ""}</span>`).join("")}</div>` : ""}`; },
  read_document: (p, r) => {
    const lines = (r.body || "").split("\n").map((l) => {
      const hit = /livr/i.test(l) && /\d{1,2}\/\d{1,2}\/\d{4}/.test(l) ? "hit" : /^Livré à\s*:/.test(l) ? "soft" : "";
      return `<div class="ln ${hit}">${esc(l) || "&nbsp;"}</div>`;
    }).join("");
    return `<div class="wf-paper"><div class="wf-paper-head"><span>${esc(DOC_KIND[r.kind] || r.kind || "document")} · #${esc(r.id)}</span>
      <span>${r.doc_date ? "dated " + fr(r.doc_date) : "undated"}${r.invoice_id ? ` · invoice #${esc(r.invoice_id)}` : ""}${r.added_by === "judge" ? " · added live" : ""}</span></div>
      <div class="wf-lines">${lines}</div></div>`; },
  search_company: (p, r, a, m) => { const x = r.results || [], chosen = chosenSiren(m);
    return `<div class="wf-queryline">${ico("search")}<span>“${esc(r.query)}”</span>${r.postal_code ? `<span class="muted">· postal code ${esc(r.postal_code)}</span>` : ""}</div>
      ${x.length ? x.map((c) => companyCard(c, chosen)).join("") : '<p class="muted">No company matches this search.</p>'}
      ${r.note ? `<p class="wf-note-line">${esc(r.note)}</p>` : ""}`; },
  get_company: (p, r, a, m) => r.company ? companyCard(r.company, chosenSiren(m)) : `<p class="muted">${esc(r.note || "No register record.")}</p>`,
  get_bodacc_history: (p, r, a, m) => { const anchor = anchorId(m), n = r.notices || [];
    return `<div class="wf-queryline">${ico("news")}<span>SIREN ${esc(r.siren)}</span><span class="muted">· ${n.length} notice${n.length === 1 ? "" : "s"}</span></div>
      ${n.length ? `<div class="timeline">${n.map((x) => `<div class="tl-item ${x.id === anchor ? "anchor" : ""}"><div class="tl-dot"></div><div>
        <div class="tl-title">${KIND[x.event_kind] || esc(x.event_kind)}${x.procedure ? " · " + (PROC[x.procedure] || esc(x.procedure)) : ""}
          ${x.id === anchor ? '<span class="status gray">Deadline anchor</span>' : ""}${x.event_kind === "CONVERSION" ? '<span class="status amber">Does not restart the deadline</span>' : ""}</div>
        <div class="tl-meta">Judgment ${fr(x.jugement_date)} · published ${fr(x.date_parution)}${x.tribunal ? " · " + esc(x.tribunal) : ""}</div>
        ${(x.officers || []).length ? `<div class="tl-meta">${x.officers.map((o) => esc(o.text || "")).join(" · ")}</div>` : ""}
        ${x.complement ? `<div class="wf-excerpt">${esc(x.complement)}</div>` : ""}
        <div class="tl-meta mono">${esc(x.id)}${x.url ? ` · <a target="_blank" rel="noopener" href="${esc(x.url)}">bodacc.fr</a>` : ""}</div></div></div>`).join("")}</div>`
        : '<p class="muted">No collective-procedure notice for this SIREN: no case, no alert.</p>'}`; },
  record_identity: (p, r) => `<div class="wf-decision">
      <div class="wf-dec agent"><p class="eyebrow">${who("AGENT")} Evidence</p><div class="wf-big">${esc(IDENT[p.status] || p.status)}</div>
        ${p.siren ? `<div class="mono">SIREN ${esc(p.siren)}</div>` : ""}<blockquote>${esc(p.evidence)}</blockquote></div>
      <div class="wf-dec-arrow">→</div>
      <div class="wf-dec"><p class="eyebrow">${who("RULE")} Exact SIREN rule</p>
        <div class="wf-big ${r.case_id ? "red" : "green"}">${r.case_id ? (r.case_created ? "Case opened" : "Case found") : "No case"}</div>
        <p class="muted">${esc(r.note || "Identity not verified: nothing is matched, no alert is raised.")}</p></div></div>`,
  compute_deadlines: (p, r) => `<div class="wf-dl"><div class="wf-dl-big num ${urg(r.days_left)}">${r.claim_deadline ? dday(r.days_left) : "Review"}</div>
      <div><div class="wf-dl-when">${r.claim_deadline ? `File the claim by <b>${fr(r.claim_deadline)}</b>` : "No opening judgment in the history"}</div>
        <div class="muted">${r.anchor_publication ? `Anchored on the opening published ${fr(r.anchor_publication)} · ${esc(r.anchor_notice_id || "")}` : "Never computed from a conversion."}</div></div></div>
    <div class="wf-kv"><span>Opening judgment</span><b>${fr(r.opening_judgment_date)}</b><span>Current procedure</span><b>${PROC[r.current_procedure] || "—"}</b>
      <span>Reclaim goods (revendication)</span><b>${fr(r.revendication_deadline)}</b><span>Relief from forclusion</span><b>${fr(r.relief_deadline)}</b></div>
    ${(r.notes || []).length ? `<div class="callout note"><span>${r.notes.map(esc).join("<br>")}</span></div>` : ""}
    <p class="wf-note-line">${who("RULE")} Computed by code, not by the model: two months from the BODACC publication of the opening judgment (R622-24 C. com., art. 641 and 642 CPC).</p>`,
  record_claim_classification: (p, r, a, m, w) => {
    const inv = w.kase?.invoices?.find((i) => i.id === p.invoice_id);
    const rule = inv?.history?.find((h) => h.decided_by === "RULE");
    const line = deliveryLine(docFromRun(m, p.evidence_document_id)?.body);
    const [tone, label] = CAT[r.category] || ["gray", r.category];
    return `<div class="wf-decision">
      <div class="wf-dec agent"><p class="eyebrow">${who("AGENT")} Evidence</p>
        <div class="wf-big">${p.fait_generateur_date ? fr(p.fait_generateur_date) : "Unknown date"}</div>
        <div class="muted">${esc(BASIS[p.basis] || p.basis || "")}${p.evidence_document_id ? ` · document #${esc(p.evidence_document_id)}` : " · no document"}</div>
        ${line ? `<div class="wf-evline">${ico("doc")}<mark>${esc(line)}</mark></div>` : ""}<blockquote>${esc(p.rationale)}</blockquote></div>
      <div class="wf-dec-arrow">→</div>
      <div class="wf-dec"><p class="eyebrow">${who("RULE")} Legal engine</p><div class="wf-big ${tone}">${esc(label)}</div>
        <p class="muted">${esc(r.reason || "")}</p>
        ${r.declare_delta_cents > 0 ? `<div class="wf-gain">Added to claim: +${eur(r.declare_delta_cents)}</div>`
          : r.declare_delta_cents < 0 ? `<div class="wf-loss">Removed from claim: −${eur(-r.declare_delta_cents)}</div>` : ""}
        <p class="muted">Case total to declare: <b>${eur(r.case_declare_cents)}</b></p></div></div>
    ${rule ? `<div class="wf-baseline">${who("RULE")}<span>Invoice-date rule (invoiced ${short(inv.invoice_date)}):</span>${cat(rule.category)}
      ${rule.category !== r.category ? "<b>The evidence changed the answer.</b>" : ""}</div>` : ""}`; },
  propose_actions: (p, r) => `<div>${(r.actions || []).map((x) => `<div class="wf-li"><span class="wf-app">${ico(x.kind === "CLAIM_DRAFT" ? "clipboard" : x.kind === "REVENDICATION_ALERT" ? "flag" : "done")}</span>
      <div><b>${esc(ACTION[x.kind] || x.kind)}</b><div class="muted">${x.kind === "CLAIM_DRAFT"
        ? `${esc(x.total)} · ${x.lines} invoice${x.lines === 1 ? "" : "s"} · to ${esc(p.officer_name || "the officer named in the notice")}${p.officer_role ? ` (${esc(p.officer_role)})` : ""}`
        : x.kind === "REVENDICATION_ALERT" ? `Goods under retention of title can be reclaimed until ${fr(x.deadline)}`
        : "Keep supplying under the contract; new deliveries are paid on delivery (L622-13)"}</div></div></div>`).join("") || '<p class="muted">No action prepared.</p>'}</div>
    ${(r.warnings || []).length ? `<div class="callout note"><span>${r.warnings.map(esc).join("<br>")}</span></div>` : ""}
    <p class="wf-note-line">${who("RULE")} Code assembles the amounts, the échu / à échoir split and the deadline from the recorded decisions. Drafts only: a human signs.</p>`,
  flag_lawyer_review: (p, r) => `<div class="wf-dec flag"><p class="eyebrow">${who("AGENT")} Sent to a lawyer</p><blockquote>${esc(p.reason)}</blockquote>
      ${(r.reasons || []).length > 1 ? `<p class="muted">${r.reasons.length} review items on this case</p>` : ""}</div>
    <p class="wf-note-line">Out of scope or uncertain: the agent escalates instead of guessing.</p>`,
  finish: (p, r, a, m, w) => `<div class="wf-report"><p class="eyebrow">${who("AGENT")} Final report</p>
      <div class="wf-big">${esc(RUN_END[p.status] || p.status)}</div><p class="sum">${esc(p.summary)}</p>
      ${w.run.case_id ? '<button class="button" data-wf="case">Open the case</button>' : ""}</div>`,
};

function sourceOf(a) {
  const r = a.res?.payload || {};
  return {
    get_customer_file: "Your ledger · Postgres: customers, contracts, invoices, documents",
    read_document: `Postgres: documents · ${r.added_by === "judge" ? "added live" : "fictional ledger"}`,
    search_company: `API Recherche d'entreprises · ${r.source || "register"}`,
    get_company: `API Recherche d'entreprises · ${r.source || "register"}`,
    get_bodacc_history: `BODACC · ${r.source || "notices"}`,
    record_identity: "Writes customers.verified_siren · the exact-SIREN rule then opens the case",
    compute_deadlines: "Legal engine (app/legal.py) · writes the deadlines to cases",
    record_claim_classification: "Legal engine (app/legal.py) · appends to invoice_classifications",
    propose_actions: "Code · writes to actions, for your sign-off",
    flag_lawyer_review: "Writes a LAWYER_REVIEW action · the case goes to review",
    finish: "Closes the run · sets the case status",
  }[a.tool] || "";
}

function wfBody(a, m, w) {
  if (!a.res) return `<div class="wf-empty"><span class="wf-spin"></span>${esc(TOOL[a.tool]?.app || a.tool)} is working…</div>`;
  if (a.res.kind === "ERROR") return `<div class="callout danger" style="margin-top:0"><span>${esc(a.res.payload?.error || "Tool error")}</span></div>
    <p class="wf-note-line">The error goes back to the agent, which decides what to do next.</p>`;
  const f = WF_BODY[a.tool];
  return f ? f(a.p, a.res.payload || {}, a, m, w) : `<pre class="wf-json">${esc(JSON.stringify(a.res.payload, null, 2))}</pre>`;
}

function wfRenderTurns(m, w) {
  const box = $("wf-turns");
  [...box.children].forEach((node) => { if (+node.id.slice(8) >= m.turns.length) node.remove(); });
  for (const t of m.turns) {
    const node = document.getElementById(`wf-turn-${t.k}`);
    if (node && node.dataset.sig === wfTurnSig(t, w)) continue;
    const html = wfTurnHtml(t, m, w);
    if (node) node.outerHTML = html; else box.insertAdjacentHTML("beforeend", html);
  }
  m.actions.forEach((a) => w.seen.add(a.id));
  box.querySelectorAll(".wf-act.sel").forEach((x) => x.classList.remove("sel"));
  box.querySelector(`.wf-act[data-i="${w.sel}"]`)?.classList.add("sel");
}

function wfRenderComputer(m, w) {
  const a = m.actions[w.sel], n = m.actions.length, live = wfLive(w);
  const sig = a ? `${a.id}.${a.res ? a.res.id : 0}.${w.kase ? 1 : 0}.${chosenSiren(m)}.${anchorId(m)}` : "none";
  if (w.compSig !== sig) {
    w.compSig = sig;
    const t = a ? TOOL[a.tool] || { app: a.tool, icon: "spark" } : null;
    $("wf-comp-head").innerHTML = a
      ? `<span class="wf-app">${ico(t.icon)}</span><div class="wf-comp-titles"><p class="eyebrow">FORCLOS is using · ${esc(t.app)}</p>
         <div class="wf-comp-title">${actTitle(a, m, w)}</div></div><span class="wf-comp-tag" id="wf-comp-tag"></span>`
      : `<span class="wf-app">${ico("spark")}</span><div class="wf-comp-titles"><p class="eyebrow">What the agent sees</p>
         <div class="wf-comp-title">Waiting for the agent's first move</div></div><span class="wf-comp-tag" id="wf-comp-tag"></span>`;
    $("wf-comp-body").innerHTML = a ? wfBody(a, m, w) : `<div class="wf-empty"><span class="wf-spin"></span>The agent is reading its task…</div>`;
    $("wf-comp-body").scrollTop = 0;
    $("wf-comp-src").innerHTML = a ? `${ico("db")}<span>${esc(sourceOf(a))}</span>` : "";
    w.tagHtml = null;
  }
  const tag = live && a && w.sel === n - 1 ? `<span class="live"></span>${w.replay ? "REPLAY" : "LIVE"}` : a ? new Date(a.at).toLocaleTimeString("en-GB") : "";
  if (tag !== w.tagHtml) { $("wf-comp-tag").innerHTML = tag; w.tagHtml = tag; }
  const range = $("wf-range");
  range.max = Math.max(0, n - 1); range.value = Math.max(0, w.sel); range.disabled = n < 2;
  $("wf-pos").textContent = n ? `${w.sel + 1} / ${n}` : "0 / 0";
  const lb = $("wf-livebtn");
  const lbHtml = w.replay ? "Stop replay" : liveRun(w.run) ? (w.follow ? '<span class="live"></span>Live' : "Jump to live") : `${ico("play")}Replay run`;
  if (lb.dataset.html !== lbHtml) { lb.innerHTML = lbHtml; lb.dataset.html = lbHtml; }
  lb.classList.toggle("primary", !(liveRun(w.run) && w.follow) || !!w.replay);
}

const wfEndHtml = (m, w) => {
  const r = w.run;
  if (r.stalled) return `${ico("alert")}<span>Interrupted: no activity for 2 minutes. Run it again.</span>`;
  if (r.status === "ERROR") return `${ico("alert")}<span>${esc(r.summary || "The run failed.")}</span>`;
  const dur = ts(r.last_activity || r.finished_at || r.started_at) - ts(r.started_at);
  return `${ico("done")}<span>Finished in ${secs(dur)} · ${m.actions.length} actions${r.input_tokens ? ` · ${(r.input_tokens + r.output_tokens).toLocaleString("en-GB")} tokens` : ""}</span>`;
};

function wfTick() {
  const w = S.wf; if (!w?.run || !w.model) return;
  const m = w.model, live = wfLive(w), now = wfNow(w);
  const el = $("wf-elapsed");
  if (el) el.textContent = secs((live ? now : ts(w.run.last_activity || w.run.finished_at || m.lastAt)) - ts(w.run.started_at));
  const last = m.actions[m.actions.length - 1];
  const state = !live ? `end.${w.run.status}.${w.run.stalled}` : last && !last.res ? `tool.${last.id}` : `think.${m.n}`;
  const box = $("wf-live"); if (!box) return;
  if (w.liveState !== state) {
    w.liveState = state;
    box.className = `wf-live ${live ? "on" : "end"}`;
    box.innerHTML = !live ? wfEndHtml(m, w) : state.startsWith("tool")
      ? `<span class="wf-spin"></span><span class="shimmer">${esc(TOOL[last.tool]?.app || last.tool)} working</span><span class="num" id="wf-live-t"></span>`
      : `${ico("spark")}<span class="shimmer">Thinking</span><span class="num" id="wf-live-t"></span>`;
  }
  const t = $("wf-live-t");
  if (t) t.textContent = secs(now - (state.startsWith("tool") ? last.at : m.lastAt));
}

function wfRender() {
  const w = S.wf; if (!w?.run) return;
  const m = wfModel(w); w.model = m;
  const n = m.actions.length;
  if (w.follow || w.sel >= n || w.sel < 0) w.sel = n - 1;
  const head = wfHeadHtml(m, w);
  if (head !== w.headHtml) {
    $("wf-head").innerHTML = head; w.headHtml = head;
    const chip = $("wf-head").querySelector('[data-key="declare"]'), v = chip?.querySelector(".v")?.textContent;
    if (chip && w.lastDeclare !== undefined && v !== w.lastDeclare) chip.classList.add("bump");
    w.lastDeclare = v;
  }
  const stages = wfStagesHtml(m, w);
  if (stages !== w.stagesHtml) { $("wf-stages").innerHTML = stages; w.stagesHtml = stages; }
  if (!$("wf-task").innerHTML) $("wf-task").innerHTML = wfTaskHtml(w.run);
  wfRenderTurns(m, w);
  wfRenderComputer(m, w);
  wfTick();
  const box = $("wf-stream");
  if (w.stick) box.scrollTop = box.scrollHeight;
  $("wf-jump").hidden = w.stick;
}

async function wfLoadCase(w) {
  const id = w.run?.case_id; if (!id) return;
  try { const c = await api(`/api/cases/${id}`); if (S.wf === w) { w.kase = c; w.compSig = null; wfRender(); } } catch { return; }
}

async function wfPoll(runId) {
  const w = S.wf; if (!w || w.runId !== runId) return;
  let r;
  try { r = await api(`/api/runs/${runId}/steps?after=${w.after}`); } catch (e) {
    if (S.wf !== w) return;
    if (!w.run) { $("wf-turns").innerHTML = `<p class="muted" style="margin-top:20px">Could not load this run: ${esc(e.message)}</p>`; return; }
    w.timer = setTimeout(() => wfPoll(runId), 1500); return;
  }
  if (S.wf !== w) return;
  const { steps, ...run } = r;
  w.offset = ts(run.server_now) - Date.now();
  w.run = run;
  if (steps.length) { w.steps.push(...steps); w.after = steps[steps.length - 1].id; }
  const live = liveRun(run);
  if (run.case_id && (w.kaseId !== run.case_id || (w.wasLive && !live))) { w.kaseId = run.case_id; wfLoadCase(w); }
  w.wasLive = live;
  if (!w.replay) wfRender();
  if (live) w.timer = setTimeout(() => wfPoll(runId), 800);
}

function wfSelect(i, scroll = false) {
  const w = S.wf; if (!w?.model) return;
  const n = w.model.actions.length; if (!n) return;
  w.sel = Math.max(0, Math.min(n - 1, i)); w.follow = false;
  wfRender();
  if (scroll) document.querySelector(`.wf-act[data-i="${w.sel}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function wfStartReplay() {
  const w = S.wf; if (!w?.steps.length) return;
  w.replay = { cut: 0, timer: null, base: { real: Date.now(), virt: ts(w.run.started_at) } };
  w.seen = new Set(); w.follow = true; w.stick = true; w.compSig = null; w.headHtml = null; w.lastDeclare = undefined;
  $("wf-turns").innerHTML = "";
  wfRender(); wfReplayNext();
}
function wfReplayNext() {
  const w = S.wf, rp = w?.replay; if (!rp) return;
  if (rp.cut >= w.steps.length) { w.replay = null; w.compSig = null; wfRender(); return; }
  const prev = rp.cut ? ts(w.steps[rp.cut - 1].created_at) : ts(w.run.started_at);
  const gap = Math.min(8000, Math.max(140, ts(w.steps[rp.cut].created_at) - prev));
  rp.timer = setTimeout(() => {
    if (S.wf !== w || w.replay !== rp) return;
    rp.cut += 1; rp.base = { real: Date.now(), virt: ts(w.steps[rp.cut - 1].created_at) };
    wfRender(); wfReplayNext();
  }, gap);
}
function wfStopReplay() {
  const w = S.wf; if (!w?.replay) return;
  clearTimeout(w.replay.timer); w.replay = null; w.compSig = null; w.headHtml = null;
  wfRender();
}

function wfClick(e) {
  const w = S.wf, el = e.target.closest("[data-wf]"); if (!w || !el) return;
  const k = el.dataset.wf;
  if (k === "close") closeWorkflow();
  else if (k === "case") { const id = w.run?.case_id; closeWorkflow(true); if (id) location.hash = `#/case/${id}`; }
  else if (k === "act" || k === "stage") { if (el.dataset.i !== "") wfSelect(+el.dataset.i, k === "stage"); }
  else if (k === "prev") wfSelect(w.sel - 1, true);
  else if (k === "next") wfSelect(w.sel + 1, true);
  else if (k === "jump") { w.stick = true; wfRender(); }
  else if (k === "live") {
    if (w.replay) wfStopReplay();
    else if (liveRun(w.run)) { w.follow = true; w.stick = true; wfRender(); }
    else wfStartReplay();
  }
}

function openWorkflow(runId, { routed = false } = {}) {
  if (!runId) return;
  closeWorkflow(true);
  const el = document.createElement("div");
  el.className = "wf-layer"; el.id = "wf"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Agent workflow");
  el.innerHTML = `
    <header class="wf-head" id="wf-head"><button class="button small soft" data-wf="close">${ico("back")}Back</button>
      <div class="wf-titles"><p class="eyebrow">Agent run</p><h2>Loading…</h2></div></header>
    <nav class="wf-stages" id="wf-stages"></nav>
    <div class="wf-body">
      <section class="wf-left">
        <div class="wf-scroll" id="wf-stream"><div id="wf-task"></div><div id="wf-turns"></div><div class="wf-live" id="wf-live"></div></div>
        <button class="wf-jump" data-wf="jump" id="wf-jump" hidden>↓ Latest step</button>
      </section>
      <section class="wf-right"><div class="wf-computer">
        <div class="wf-comp-head" id="wf-comp-head"></div>
        <div class="wf-comp-body" id="wf-comp-body"></div>
        <div class="wf-comp-src" id="wf-comp-src"></div>
        <div class="wf-comp-foot">
          <button class="wf-nav" data-wf="prev" title="Previous step (←)">${ico("prev")}</button>
          <input type="range" id="wf-range" min="0" max="0" value="0" aria-label="Step">
          <button class="wf-nav" data-wf="next" title="Next step (→)">${ico("next")}</button>
          <span class="wf-pos num" id="wf-pos"></span>
          <button class="button small" data-wf="live" id="wf-livebtn"></button>
        </div></div></section>
    </div>`;
  document.body.appendChild(el);
  document.body.classList.add("wf-open");
  S.wf = { runId, routed, origin: location.hash, run: null, model: null, steps: [], after: 0, sel: -1, follow: true, stick: true,
           seen: new Set(), kase: null, kaseId: null, offset: 0, replay: null, timer: null, wasLive: false };
  el.addEventListener("click", wfClick);
  $("wf-range").addEventListener("input", (e) => wfSelect(+e.target.value, true));
  $("wf-stream").addEventListener("scroll", () => {
    const w = S.wf, b = $("wf-stream"); if (!w) return;
    w.stick = b.scrollHeight - b.scrollTop - b.clientHeight < 60;
    $("wf-jump").hidden = w.stick;
  });
  S.wf.tick = setInterval(wfTick, 200);
  wfPoll(runId);
}

function closeWorkflow(silent = false) {
  const w = S.wf; if (!w) return;
  clearTimeout(w.timer); clearInterval(w.tick); if (w.replay) clearTimeout(w.replay.timer);
  S.wf = null; $("wf")?.remove(); document.body.classList.remove("wf-open");
  if (silent) return;
  if (w.routed) location.hash = "#/agent";
  else if (S.route.page === "case") renderCase().catch(() => {});
  else if (S.route.page === "customers") renderCustomers().catch(() => {});
  else if (S.route.page === "cases") renderCases().catch(() => {});
  else if (S.route.page === "home") renderHome().catch(() => {});
}

document.addEventListener("keydown", (e) => {
  const w = S.wf; if (!w) return;
  if (e.key === "Escape") { closeWorkflow(); return; }
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); wfSelect(w.sel - 1, true); }
  if (e.key === "ArrowRight") { e.preventDefault(); wfSelect(w.sel + 1, true); }
});

// ---------------------------------------------------------------- agent runs
async function renderRuns() {
  const list = await api("/api/runs?limit=40");
  if (!["agent", "run"].includes(S.route.page)) return;
  const live = list.filter(liveRun).length;
  const rows = list.map((r) => {
    const [tone, label] = runState(r), dur = liveRun(r) ? null : ts(r.last_activity || r.finished_at) - ts(r.started_at);
    const auto = /automatic sync|at import/i.test(r.trigger || "");
    return `<button class="run-row" data-run="${r.id}"><span class="run-ico">${ico(r.task === "RESOLVE_IDENTITY" ? "search" : "scale")}</span>
      <span class="run-main"><b>${r.task === "RESOLVE_IDENTITY" ? "Identity check" : "Investigation"} · ${esc(r.crm_name || "")}${auto ? '<span class="auto">started by itself</span>' : ""}</b>
        <span>${esc(liveRun(r) ? `Working: ${TOOL[r.last_tool]?.app || "thinking"}…` : r.summary || "—")}</span></span>
      <span class="run-meta"><span class="status ${tone}">${label}</span><span>${dur != null ? `${secs(dur)} · ` : ""}${ago(r.started_at)}</span></span></button>`;
  }).join("");
  $("view").innerHTML = `<section class="page" id="runs-page">
    <div class="page-head"><div><h1>Agent</h1>
      <p class="lead">${list.length ? `${list.length} investigation${list.length === 1 ? "" : "s"}${live ? `, ${live} running now` : ""}. Open one to watch it think, step by step.` : "No investigation yet."}</p></div></div>
    <div class="run-list">${rows || '<p class="empty">Open a case and let the agent investigate.</p>'}</div></section>`;
  document.querySelectorAll(".run-row[data-run]").forEach((b) => b.onclick = () => { location.hash = `#/run/${b.dataset.run}`; });
}

async function renderRunPage() {
  if (!$("runs-page")) await renderRuns();
  if (S.route.page === "run" && (!S.wf || S.wf.runId !== S.route.id)) openWorkflow(S.route.id, { routed: true });
}

// ---------------------------------------------------------------- customers
async function renderCustomers() {
  const d = await loadDash();
  if (S.route.page !== "customers") return;
  const caseFor = (cid) => d.cases.find((c) => c.customer.id === cid);
  const rows = d.customers.map((c) => {
    const k = caseFor(c.id), siren = c.verified_siren || c.crm_siren;
    const ident = c.identity_status === "VERIFIED" ? '<span class="status green">Company found</span>'
      : c.identity_status === "REVIEW" ? '<span class="status amber">To review</span>'
      : c.identity_status === "NOT_FOUND" ? '<span class="status amber">Not found</span>'
      : c.crm_siren ? '<span class="status gray">ID on file</span>' : '<span class="status red">No company ID</span>';
    return `<div class="cust-row"><span class="cust-name"><b>${esc(c.crm_name)}</b><span>${esc([c.postal_code, c.city].filter(Boolean).join(" "))}${siren ? ` · SIREN ${esc(siren)}` : ""}</span></span>
      ${ident}<span class="cust-amt num">${eur(c.outstanding_cents)}</span>
      <span class="cust-act">${k ? `<a class="button small" href="#/case/${k.id}">Open case</a>`
        : c.identity_status === "VERIFIED" ? '<span class="muted">No proceedings</span>'
        : c.crm_siren ? `<button class="button small soft" data-resolve="${c.id}">Double-check</button>`
        : `<button class="button small primary" data-resolve="${c.id}">Find it</button>`}</span></div>`;
  }).join("");
  $("view").innerHTML = `<section class="page">
    <a class="back" href="#/cases">${ico("back")}Cases</a>
    <div class="page-head"><div><h1>Customers</h1><p class="lead">As your sales team typed them. The agent finds the real company behind each one.</p></div>
      <div class="button-row"><a class="button" href="#/import">Import receivables</a><button class="button primary" id="btn-add">Add a customer</button></div></div>
    <div class="cust-list">${rows || '<p class="empty">No customer yet.</p>'}</div></section>`;
  $("btn-add").onclick = openModal;
  wireResolve(d);
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
    watchRun(r.run_id, { customerId: r.customer_id, origin: `Identity check: ${name}` });
    openWorkflow(r.run_id);
  } catch (e) { toast(e.message); }
};

// ---------------------------------------------------------------- feed
async function renderFeed() {
  await loadDash(); const f = await loadFeed();
  if (S.route.page !== "feed") return;
  $("view").innerHTML = `<section class="page">
    <div class="page-heading"><h1>BODACC feed</h1>
      <p>The latest insolvency notices published in France. Your customers are highlighted.</p>
      <div class="button-row"><button class="button primary" id="btn-ingest">Fetch the last 2 days</button>
        <span class="muted">${f.length} notices shown</span></div></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>Published</th><th>Company</th><th>Event</th><th>Court</th><th>Your customer</th></tr></thead>
      <tbody>${f.map((n) => {
        const cust = n.matched_customer_id ? S.dash.customers.find((c) => c.id === n.matched_customer_id) : null;
        return `<tr style="${cust ? "background:var(--accent-soft)" : ""}"><td class="num mono">${short(n.date_parution)}</td>
          <td><div class="cell-main">${esc(title(n.denomination || ""))}</div><div class="cell-sub">SIREN ${esc(n.siren || "—")} · ${esc(n.cp || "")} ${esc(n.ville || "")}</div></td>
          <td>${KIND[n.event_kind] || n.event_kind}<div class="cell-sub">${PROC[n.procedure] || ""}</div></td>
          <td class="muted" style="font-size:.8rem">${esc((n.tribunal || "").replace(/^Greffe du /, ""))}</td>
          <td>${cust ? `<span class="status red">${esc(cust.crm_name)}</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div></section>`;
  $("btn-ingest").onclick = async () => {
    const b = $("btn-ingest"); b.disabled = true; b.textContent = "Fetching…";
    try { const r = await post("/api/ingest", { days: 2 }); toast(`${r.fetched} notices fetched, ${r.inserted} new, ${r.new_cases} new case(s).`); }
    catch (e) { toast("BODACC unreachable: showing stored notices."); }
    renderFeed();
  };
}

// ---------------------------------------------------------------- proof
async function renderProof() {
  const rows = await api("/api/benchmark");
  if (S.route.page !== "proof") return;
  const get = (split, s) => rows.find((r) => r.split === split && r.system === s);
  const sys = ["NAIVE", "RULES", "FORCLOS"].map((s) => get("holdout", s)).filter(Boolean);
  if (sys.length < 3) { $("view").innerHTML = '<section class="page"><h1>Does it work?</h1><p class="lead">No test has been run yet.</p></section>'; return; }
  const [naive, rules, us] = sys.map((r) => r.metrics), dev = get("dev", "FORCLOS")?.metrics;
  const max = Math.max(1, naive.eur_lost_cents, rules.eur_lost_cents);
  const NAME = { NAIVE: ["A basic insolvency alert", "Matches names, counts 60 days, trusts invoice dates"],
                 RULES: ["Rules only", "Exact company ID and the correct legal deadline"],
                 FORCLOS: ["FORCLOS", "The same rules, plus the agent that investigates"] };
  const when = new Date(sys[2].run_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const row = (label, f) => `<tr><td>${label}</td><td>${f(naive)}</td><td>${f(rules)}</td><td class="us">${f(us)}</td></tr>`;
  $("view").innerHTML = `<section class="page">
    <div class="page-head"><div><h1>Does it work?</h1>
      <p class="lead">We gave ${us.n} real insolvent companies to three tools, with customer records as messy as real ones, and counted the claims each would have missed.</p></div></div>
    <div class="pbars">${sys.map((r) => { const m = r.metrics, [name, desc] = NAME[r.system]; return `<div class="pbar ${r.system === "FORCLOS" ? "us" : ""}">
      <span class="pbar-name"><b>${name}</b><span>${desc}</span></span>
      <span class="pbar-track"><span style="width:${Math.max(1.2, (m.eur_lost_cents / max) * 100)}%"></span></span>
      <span class="pbar-val"><b class="num">${eur(m.eur_lost_cents)}</b><span>of claims missed</span></span></div>`; }).join("")}</div>
    <p class="pnote">Out of ${eur(us.truth_declare_cents)} that should have been claimed on time.</p>
    <div class="ptable-wrap"><table class="ptable"><thead><tr><th></th><th>Basic alert</th><th>Rules only</th><th class="us">FORCLOS</th></tr></thead><tbody>
      ${row("Insolvent customers found", (m) => `${m.found} of ${m.affected}`)}
      ${row("Healthy customers wrongly flagged", (m) => `${m.false_alarms} of ${m.healthy}`)}
      ${row("Exact legal deadline", (m) => `${m.deadline_ok} of ${m.affected}`)}
      ${row("Time per company", (m) => m.median_seconds ? `${Math.round(m.median_seconds)} seconds` : "instant")}
    </tbody></table></div>
    <div class="phow">
      <div><h3>Real companies</h3><p>${us.n} companies with a real opening judgment in the BODACC, and their real record in the company register.</p></div>
      <div><h3>Messy records</h3><p>Shop names instead of legal names, typos, the ID of a closed company, healthy look-alikes, invoices dated after the judgment, a redressement turned into a liquidation.</p></div>
      <div><h3>Never seen before</h3><p>These ${us.n} cases were kept aside during development and run once, on ${when}.${dev ? ` On the ${dev.n} development cases: ${eur(dev.eur_lost_cents)} missed too.` : ""}</p></div>
    </div>
    <p class="small muted">A simulation: the companies are real, the customer errors are generated by us.${us.reviewed ? ` ${us.reviewed} cases were also flagged for a human check.` : ""} Recorded runs of benchmark/run.py.</p>
    <details class="every"><summary>See every case</summary>${benchCases(sys)}</details>
  </section>`;
}

const FAMILY = { EXACT_SIREN: "Right SIREN in the CRM", TRADE_NAME: "Trade name, no SIREN", ABBREV_TYPO: "Abbreviation or typo",
                 STALE_SIREN: "SIREN of a ceased company", HOMONYM_HEALTHY: "Healthy look-alike", LATE_INVOICE: "Invoice dated after the judgment",
                 CONVERSION: "RJ converted to LJ" };

function benchCell(d) {
  if (!d) return "—";
  if (!d.affected) return d.false_alarm ? '<span class="status red">False alarm</span>' : '<span class="status green">No alert</span>';
  if (d.lost_cents === 0) return `<span class="status green">Filed on time</span>${d.reviewed ? '<div class="cell-sub">escalated to review too</div>' : ""}`;
  const why = !d.found ? "customer not found" : (d.deadline && d.truth_deadline && d.deadline > d.truth_deadline) ? `deadline ${short(d.deadline)}, legal ${short(d.truth_deadline)}` : "invoice left out";
  return `<span class="status red">${eur(d.lost_cents)} missed</span><div class="cell-sub">${why}</div>`;
}

function benchCases(sys) {
  const by = Object.fromEntries(sys.map((r) => [r.system, Object.fromEntries((r.details || []).map((d) => [d.bench_case_id, d]))]));
  const ids = Object.keys(by.FORCLOS || by.RULES || {}).sort();
  if (!ids.length) return "";
  const any = (id) => (by.FORCLOS || by.RULES || by.NAIVE)[id];
  return `<div class="section-title"><h2>Every case</h2><span class="muted">${ids.length} cases · CRM name as the salesperson typed it</span></div>
    <div class="scroll-x"><table class="table"><thead><tr><th>Case</th><th>CRM error</th><th>Naive alert</th><th>Rules only</th><th>FORCLOS</th></tr></thead>
    <tbody>${ids.map((id) => `<tr><td><div class="cell-main">${esc(any(id).crm_name)}</div><div class="cell-sub mono">${esc(id)}</div></td>
      <td class="muted" style="font-size:.8rem">${FAMILY[any(id).family] || esc(any(id).family)}</td>
      <td>${benchCell(by.NAIVE?.[id])}</td><td>${benchCell(by.RULES?.[id])}</td><td>${benchCell(by.FORCLOS?.[id])}</td></tr>`).join("")}</tbody></table></div>`;
}

// ---------------------------------------------------------------- data layer
async function renderData() {
  const d = await api("/api/data");
  if (S.route.page !== "data") return;
  const n = (x) => Number(x || 0).toLocaleString("en-GB");
  const box = (eyebrow, title, lines) => `<div class="flow-box"><p class="eyebrow">${eyebrow}</p><h3>${title}</h3>
    <div class="flow-lines">${lines.map((l) => `<div>${l}</div>`).join("")}</div></div>`;
  $("view").innerHTML = `<section class="page">
    <div class="page-heading"><p class="eyebrow"><span class="dot"></span>${esc(d.database.provider)} · ${esc(d.database.engine.replace(/ \(.*\)/, ""))} · ${esc(d.database.size)}</p>
      <h1>Data</h1>
      <p>Everything the agent knows lives in one Postgres database: public notices, the company register, your ledger and the cases it builds up over time.</p></div>
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
        <td class="right num">${n(r.new_cases)}</td><td class="right num">${n(r.investigations)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

// ---------------------------------------------------------------- import
const SAMPLE_CSV = `customer;siren;postal_code;city;invoice_number;invoice_date;due_date;amount;paid
Maison Vivier;;69500;Bron;FA-2026-1201;28/08/2026;27/09/2026;3120,40;0
Maison Vivier;;69500;Bron;FA-2026-1240;04/09/2026;04/10/2026;1845,00;0
Chimere;;42000;Saint-Etienne;FA-2026-1188;15/09/2026;15/10/2026;2210,00;0
Brasserie Georges;;69002;Lyon;FA-2026-1207;02/09/2026;02/10/2026;4980,00;4980,00`;

async function renderImport() {
  $("view").innerHTML = `<section class="page">
    <a class="back" href="#/cases">${ico("back")}Cases</a>
    <div class="page-heading"><h1>Import your receivables</h1>
      <p>Export your aged receivables (balance âgée clients) as CSV. FORCLOS checks every customer today and keeps watching every day after.</p></div>
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
    </div></section>`;
  $("btn-sample").onclick = () => { $("csv").value = SAMPLE_CSV; };
  $("csv-file").onchange = async (e) => { const f = e.target.files[0]; if (f) $("csv").value = await f.text(); };
  $("btn-import").onclick = async () => {
    const b = $("btn-import"); b.disabled = true; b.textContent = "Importing…";
    try {
      const r = await post("/api/import", { csv: $("csv").value });
      $("import-result").innerHTML = `<div class="callout note" style="background:var(--green-soft);color:var(--ink)">
        <span><b>${r.customers_created} customers, ${r.invoices_created} invoices imported.</b>
        ${r.cases_opened} case${r.cases_opened === 1 ? "" : "s"} opened by exact SIREN · ${r.identity_checks_queued} identity check${r.identity_checks_queued === 1 ? "" : "s"} queued for the agent.</span>
        <a class="button small primary" href="#/agent">Watch the agent</a></div>
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
  if (location.hash === "#/cases") render(); else location.hash = "#/cases";
};
setInterval(() => {
  if (document.hidden || S.wf) return;
  if (S.route.page === "agent") renderRuns().catch(() => {});
  if (S.trail.status === "RUNNING") return;
  if (S.route.page === "cases") renderCases().catch(() => {});
  if (S.route.page === "customers") renderCustomers().catch(() => {});
}, 10000);
render();
