// Stadtteilbeirat Büchenbach — Infoportal (Frontend)
// Portal-Startseite mit Themen-Kacheln + Volltextsuche über die Protokolle.
// Daten: graph.db (DuckDB-Wasm, FTS/BM25), Inhalts-Sektionen aus content/*.json,
// Original-PDFs direkt aus dem öffentlichen GitHub-Repo (jsDelivr).
// Bewusst ohne KI im Browser — nur SQL + FTS. Das Passwort-Gate ist eine
// Nutzungshürde, kein Datenschutz (die Dokumente sind amtlich öffentlich).

import * as duckdb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.33.1-dev57.0/+esm";

const APP_VERSION = "v1 · 2026-07-21";
const REPO = "erlangen-kommunal/SBR-Buechenbach";

const $ = (id) => document.getElementById(id);
const view = () => $("view");
const status = (m) => { $("statusbar").textContent = m; };
const bootMsg = (m) => { $("boot-msg").textContent = m; };
const esc = (s) => String(s).replace(/'/g, "''");
const escHtml = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const themenText = (s) => String(s ?? "").split("|").map((t) => t.trim()).filter(Boolean);
const shortLabel = (s, max = 80) => (s && s.length > max ? s.slice(0, max - 1).trimEnd() + "…" : s ?? "");

const CAT_BADGE = { Einladung: "badge-ei", Niederschrift: "badge-ni" };
const CAT_SHORT = { Einladung: "EIN", Niederschrift: "NIED", Anhang: "ANH" };

// ── Zugangs-Gate (PBKDF2-Hash-Vergleich; fehlt auth.json → Dev-Modus ohne Gate) ─

async function pbkdf2Hex(password, saltHex, iterations) {
  const salt = Uint8Array.from(saltHex.match(/.{2}/g).map((b) => parseInt(b, 16)));
  const material = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations, hash: "SHA-256" }, material, 256);
  return [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function checkAuth() {
  let auth;
  try {
    const r = await fetch("auth.json");
    if (!r.ok) return;
    auth = await r.json();
  } catch { return; }
  if (sessionStorage.getItem("sbr_auth") === auth.hash) return;

  $("boot").hidden = true;
  $("gate").hidden = false;
  $("gate-pw").focus();
  await new Promise((resolve) => {
    $("gate-form").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const hash = await pbkdf2Hex($("gate-pw").value, auth.salt, auth.iterations);
      if (hash === auth.hash) {
        sessionStorage.setItem("sbr_auth", hash);
        $("gate").hidden = true;
        resolve();
      } else {
        $("gate-error").hidden = false;
        $("gate-pw").select();
      }
    });
  });
  $("boot").hidden = false;
}

// ── DuckDB-Wasm ──────────────────────────────────────────────────────────────

let conn;

async function initDb() {
  bootMsg("Lade Datenbank …");
  const r = await fetch("graph.db");
  if (!r.ok) throw new Error("graph.db nicht gefunden.");
  const bytes = new Uint8Array(await r.arrayBuffer());

  bootMsg("Starte DuckDB-Wasm …");
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(new Blob(
    [`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const db = new duckdb.AsyncDuckDB(
    new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING), new Worker(workerUrl));
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  await db.registerFileBuffer("graph.db", bytes);
  await db.open({ path: "graph.db", query: { castBigIntToDouble: true } });
  conn = await db.connect();
  await conn.query("LOAD fts");
}

async function q(sql) {
  const t = await conn.query(sql);
  return t.toArray().map((r) => r.toJSON());
}

// ── content/*.json laden (mit Cache) ─────────────────────────────────────────

const contentCache = {};
async function loadContent(key) {
  if (contentCache[key]) return contentCache[key];
  const r = await fetch(`content/${key}.json`);
  if (!r.ok) throw new Error(`content/${key}.json nicht gefunden.`);
  return (contentCache[key] = await r.json());
}

// ── Suchbegriff-Hervorhebung ─────────────────────────────────────────────────

let lastTerms = [];
function setTerms(query) {
  lastTerms = query.split(/\s+/).map((w) => w.replace(/[^\p{L}\p{N}\/.\-]/gu, ""))
                   .filter((w) => w.length >= 3).slice(0, 8);
}
function highlight(escapedHtml) {
  if (!lastTerms.length) return escapedHtml;
  const re = new RegExp(`(${lastTerms.map(escRe).join("|")})`, "giu");
  return escapedHtml.replace(re, "<mark>$1</mark>");
}

// ── Router ───────────────────────────────────────────────────────────────────

function go(path) { location.hash = "#" + path; }

const ROUTES = {
  "": renderStart,
  "protokolle": renderProtokolle,
  "recht": () => renderRegistry("recht", "Satzung & Recht", "⚖️"),
  "statistik": () => renderRegistry("statistik", "Statistik", "📊"),
  "fachbeiraete": () => renderCards("fachbeiraete", "Andere Fachbeiräte & Ausschüsse", "👥"),
  "aemter": () => renderAemter(),
  "links": () => renderCards("links", "Nützliche Links", "🔗"),
  "karte": renderKarte,
};

async function route() {
  const raw = location.hash.slice(1).replace(/^\//, "");
  const parts = raw.split("/");
  const head = parts[0] || "";
  view().scrollTop = 0;
  window.scrollTo(0, 0);
  try {
    if (head === "suche") return await renderSuche(decodeURIComponent(parts[1] || ""));
    if (head === "doc") return await renderDoc(decodeURIComponent(parts[1] || ""));
    if (head === "plan") return await renderPlan(decodeURIComponent(parts[1] || ""));
    if (head === "planfile") return await renderPlanFile(decodeURIComponent(parts[1] || ""));
    const handler = ROUTES[head];
    if (handler) return await handler();
    return await renderStart();
  } catch (err) {
    console.error(err);
    view().innerHTML = `<div class="wrap"><a class="crumb" href="#/">‹ Startseite</a>
      <p class="hint">Fehler beim Laden: ${escHtml(err.message)}</p></div>`;
  }
}

const crumb = (label = "Startseite") => `<a class="crumb" href="#/">‹ ${escHtml(label)}</a>`;

// ── Startseite (Portal) ──────────────────────────────────────────────────────

async function renderStart() {
  const tiles = [
    ["#/protokolle", "📄", "Protokolle", "Alle Sitzungen seit 2020 — durchsuchbar mit Volltext und Zusammenfassungen."],
    ["#/recht", "⚖️", "Satzung & Recht", "Rechtsgrundlage der Stadtteilbeiräte und weiteres Stadtrecht."],
    ["#/statistik", "📊", "Statistik", "Bevölkerung, Sozialstruktur und Prognosen für Erlangen und Büchenbach."],
    ["#/fachbeiraete", "👥", "Fachbeiräte", "Andere Beiräte und Ausschüsse — inkl. UVPA-Infoseite."],
    ["#/aemter", "🏢", "Ämter", "Welches Amt der Stadt Erlangen ist wofür zuständig?"],
    ["#/links", "🔗", "Links", "Ausgewählte Seiten rund um Büchenbach — ohne Veranstaltungen."],
    ["#/karte", "🗺️", "Karte", "Büchenbach auf amtlicher Karte und im BayernAtlas."],
  ];
  view().innerHTML = `
    <section class="hero">
      <h1>Infoportal Stadtteilbeirat Büchenbach</h1>
      <p>Alles an einem Ort: die Sitzungsprotokolle seit 2020, die Satzung, verwandte
      Gremien, statistische Grundlagen, Zuständigkeiten der Ämter, nützliche Links und
      Karten — damit die Arbeit im Stadtteilbeirat leichter fällt.</p>
    </section>
    <nav class="tiles">
      ${tiles.map(([href, icon, t, d]) => `
        <a class="tile" href="${href}">
          <span class="icon">${icon}</span>
          <span><span class="t-title">${t}</span><span class="t-desc">${escHtml(d)}</span></span>
        </a>`).join("")}
    </nav>`;
  const [m] = await q(`SELECT (SELECT count(*) FROM documents)::INT AS d,
                              (SELECT count(DISTINCT date) FROM documents)::INT AS s`);
  status(`Bereit — ${m.s} Sitzungen, ${m.d} Dokumente. Wählen Sie einen Bereich oder suchen Sie oben.`);
}

// ── Protokolle (Sitzungen, gruppiert nach Jahr) ──────────────────────────────

let allDocs = null;
async function renderProtokolle() {
  status("Lade Protokolle …");
  if (!allDocs) {
    allDocs = await q(
      `SELECT id, date::VARCHAR AS date, category, title, pages,
              (text IS NOT NULL) AS has_text, summary, themen
       FROM documents ORDER BY date DESC,
            CASE category WHEN 'Einladung' THEN 0 WHEN 'Niederschrift' THEN 1 ELSE 2 END, title`);
  }
  const years = [...new Set(allDocs.map((d) => d.date.slice(0, 4)))].sort().reverse();
  const themen = [...new Set(allDocs.flatMap((d) => themenText(d.themen)))].sort();

  view().innerHTML = `<div class="wrap">
    ${crumb()}
    <h2 class="section-title">📄 Protokolle</h2>
    <p class="section-intro">Sitzungen des Stadtteilbeirats Büchenbach seit 2020. Jede Sitzung
      bündelt Einladung, Niederschrift und Anhänge. Zum Lesen ein Dokument anklicken — der
      Volltext erscheint sofort, das Original-PDF ist verlinkt.</p>
    <div class="map-actions">
      <label>Jahr <select id="f-year"><option value="">alle</option>
        ${years.map((y) => `<option value="${y}">${y}</option>`).join("")}</select></label>
      ${themen.length ? `<label>Thema <select id="f-thema"><option value="">alle</option>
        ${themen.map((t) => `<option value="${escHtml(t)}">${escHtml(t)}</option>`).join("")}</select></label>` : ""}
    </div>
    <div id="sessions"></div>
  </div>`;

  const draw = () => {
    const fy = $("f-year").value, ft = $("f-thema") ? $("f-thema").value : "";
    let docs = allDocs;
    if (fy) docs = docs.filter((d) => d.date.startsWith(fy));
    // Nach Sitzungsdatum gruppieren
    const byDate = {};
    for (const d of docs) (byDate[d.date] ??= []).push(d);
    let dates = Object.keys(byDate).sort().reverse();
    if (ft) dates = dates.filter((dt) => byDate[dt].some((d) => themenText(d.themen).includes(ft)));

    if (!dates.length) { $("sessions").innerHTML = `<p class="hint">Keine Sitzungen für diese Auswahl.</p>`; return; }
    let html = "", curYear = "";
    for (const dt of dates) {
      const y = dt.slice(0, 4);
      if (y !== curYear) { curYear = y; html += `<div class="year-head">${y}</div>`; }
      const docs = byDate[dt];
      const ni = docs.find((d) => d.category === "Niederschrift");
      const sumSrc = ni && ni.summary ? ni : docs.find((d) => d.summary);
      const th = [...new Set(docs.flatMap((d) => themenText(d.themen)))];
      html += `<div class="session">
        <div class="s-date">${fmtDate(dt)}</div>
        <div class="s-meta">${docs.length} Dokument${docs.length === 1 ? "" : "e"}</div>
        ${sumSrc && sumSrc.summary ? `<div class="s-summary">${escHtml(sumSrc.summary)}</div>` : ""}
        ${th.length ? `<div class="s-themen">${th.map((t) => `<span class="chip-thema">${escHtml(t)}</span>`).join("")}</div>` : ""}
        <ul class="s-docs">
          ${docs.map((d) => `<li>
            <span class="badge ${CAT_BADGE[d.category] || ""}">${CAT_SHORT[d.category] || "DOK"}</span>
            <a class="doc-open" href="#/doc/${encodeURIComponent(d.id)}">${escHtml(d.title)}</a>
            ${d.pages ? `<span class="d-pages">${d.pages} S.</span>` : ""}
          </li>`).join("")}
        </ul>
      </div>`;
    }
    $("sessions").innerHTML = html;
  };
  $("f-year").addEventListener("change", draw);
  $("f-thema")?.addEventListener("change", draw);
  draw();
  status(`${allDocs.length} Dokumente in ${new Set(allDocs.map((d) => d.date)).size} Sitzungen.`);
}

function fmtDate(iso) {
  const [y, m, d] = iso.split("-");
  const mon = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
               "September", "Oktober", "November", "Dezember"][Number(m) - 1];
  return `${Number(d)}. ${mon} ${y}`;
}

// ── Suche (FTS über Protokolle + Register) ───────────────────────────────────

async function renderSuche(query) {
  $("search-input").value = query;
  setTerms(query);
  view().innerHTML = `<div class="wrap">${crumb()}
    <h2 class="section-title">🔎 Suche</h2>
    <div id="search-results"></div></div>`;
  const box = $("search-results");
  if (!query || query.trim().length < 2) {
    box.innerHTML = `<p class="hint">Bitte einen Suchbegriff mit mindestens 2 Zeichen eingeben.</p>`;
    status("Suche: Begriff eingeben.");
    return;
  }
  status(`Suche „${query}“ …`);
  const qy = esc(query);

  const docRows = await q(
    `SELECT d.id, 'doc' AS kind, d.title, d.category, d.date::VARCHAR AS date, d.summary, s.score
     FROM (SELECT id, fts_main_documents.match_bm25(id, '${qy}') AS score FROM documents) s
     JOIN documents d ON d.id = s.id
     WHERE s.score IS NOT NULL ORDER BY s.score DESC LIMIT 40`);

  // Snippets für die Treffer
  if (docRows.length && lastTerms.length) {
    const ids = docRows.map((r) => `'${esc(r.id)}'`).join(",");
    const w = esc(lastTerms[0].toLowerCase());
    const snips = await q(
      `SELECT id, substr(text, greatest(position('${w}' IN lower(text)) - 90, 1), 240) AS snip
       FROM documents WHERE id IN (${ids}) AND text IS NOT NULL`);
    const byId = Object.fromEntries(snips.map((s) => [s.id, s.snip]));
    for (const r of docRows) r.snippet = byId[r.id];
  }

  const planRows = await q(
    `SELECT id, 'planfile' AS kind, title, plan_title, pkind, score FROM (
       SELECT pf.rowid::VARCHAR AS id, pf.titel AS title, p.title AS plan_title, p.kind AS pkind,
              fts_main_plan_files.match_bm25(pf.rowid, '${qy}') AS score
       FROM plan_files pf JOIN plans p ON p.id = pf.plan_id
     ) WHERE score IS NOT NULL ORDER BY score DESC LIMIT 12`);

  const rows = [...docRows, ...planRows].sort((a, b) => b.score - a.score);
  if (!rows.length) {
    box.innerHTML = `<p class="hint">Keine Treffer für „${escHtml(query)}“. Tipp: einzelne
      Stichwörter statt ganzer Sätze, z. B. „Spielplatz“ oder „Stromnetz“.</p>`;
    status(`Keine Treffer für „${query}“.`);
    return;
  }
  box.innerHTML = `<ol class="results">${rows.map((r) => {
    if (r.kind === "planfile") return `<li data-go="/planfile/${encodeURIComponent(r.id)}">
      <div class="r-title"><span class="badge badge-plan">${r.pkind === "recht" ? "RECHT" : "STATISTIK"}</span>${escHtml(r.title)}</div>
      <div class="r-meta">${escHtml(r.plan_title)} · <strong>Score ${r.score.toFixed(2)}</strong></div></li>`;
    return `<li data-go="/doc/${encodeURIComponent(r.id)}">
      <div class="r-title">${escHtml(r.title)}</div>
      <div class="r-meta">${escHtml(r.category)} · ${fmtDate(r.date)} · <strong>Score ${r.score.toFixed(2)}</strong></div>
      ${r.snippet ? `<div class="r-snippet">… ${highlight(escHtml(r.snippet))} …</div>`
        : r.summary ? `<div class="r-snippet">${escHtml(shortLabel(r.summary, 200))}</div>` : ""}
    </li>`;
  }).join("")}</ol>`;
  for (const li of box.querySelectorAll("li[data-go]"))
    li.addEventListener("click", () => go(li.dataset.go));
  status(`${rows.length} Treffer für „${query}“.`);
}

// ── Dokument-Reader (Sitzungsdokument) ───────────────────────────────────────

async function renderDoc(id) {
  const [d] = await q(
    `SELECT id, date::VARCHAR AS date, category, title, path, url, pages, text, summary, themen
     FROM documents WHERE id = '${esc(id)}'`);
  if (!d) { view().innerHTML = `<div class="wrap">${crumb()}<p class="hint">Dokument nicht gefunden.</p></div>`; return; }
  const th = themenText(d.themen);
  view().innerHTML = `<div class="wrap">
    <a class="crumb" href="#/protokolle">‹ Protokolle</a>
    <div class="doc-head">
      <h2>${escHtml(d.title)}</h2>
      <p class="meta">${escHtml(d.category)} · ${fmtDate(d.date)}${d.pages ? ` · ${d.pages} Seiten` : ""}</p>
      ${d.summary ? `<div class="doc-summary">${escHtml(d.summary)}</div>` : ""}
      ${th.length ? `<p class="meta">Themen: ${th.map(escHtml).join(", ")}</p>` : ""}
      <div class="doc-actions">
        <button id="btn-text" class="active" type="button">Text</button>
        <button id="btn-pdf" type="button">PDF</button>
        <a href="${escHtml(d.url)}" target="_blank" rel="noopener">⬇ Original im Ratsinfosystem</a>
      </div>
    </div>
    <div id="doc-notice" class="notice" hidden></div>
    <div id="doc-body"></div>
  </div>`;
  renderDocText(d);
  $("btn-pdf").addEventListener("click", () => showPdf(d, d.url));
  $("btn-text").addEventListener("click", () => {
    renderDocText(d); $("btn-text").classList.add("active"); $("btn-pdf").classList.remove("active");
  });
  document.querySelector("#doc-body .doc-page mark")?.scrollIntoView({ block: "center" });
  status(`${d.category} · ${fmtDate(d.date)}`);
}

function renderDocText(d) {
  notice("");
  if (d.text) {
    const pages = d.text.split("\f");
    $("doc-body").innerHTML = pages.map((p, i) => `<div class="doc-page">
      ${pages.length > 1 ? `<p class="doc-page-nr">Seite ${i + 1} / ${pages.length}</p>` : ""}${highlight(escHtml(p.trim()))}
    </div>`).join("");
  } else {
    $("doc-body").innerHTML = `<p class="hint">Für dieses Dokument liegt kein extrahierter Text vor
      (vermutlich gescannt). Über den PDF-Button oder den RIS-Link lässt sich das Original öffnen.</p>`;
  }
}

// ── Register (Recht / Statistik) ─────────────────────────────────────────────

async function renderRegistry(kind, title, icon) {
  const rows = await q(
    `SELECT id, title, beschreibung, themen, erstellt, quelle_url,
            (SELECT count(*) FROM plan_files pf WHERE pf.plan_id = plans.id)::INT AS n
     FROM plans WHERE kind = '${esc(kind)}' ORDER BY title`);
  const intro = kind === "recht"
    ? "Die maßgebliche Satzung für die Arbeit der Stadtteilbeiräte sowie weiteres Erlanger Stadtrecht."
    : "Ausgewählte statistische Berichte der Stadt Erlangen mit Bezug zu Büchenbach und zur kleinräumigen Entwicklung.";
  view().innerHTML = `<div class="wrap">${crumb()}
    <h2 class="section-title">${icon} ${escHtml(title)}</h2>
    <p class="section-intro">${intro}</p>
    <ul class="reg-list">
      ${rows.map((r) => `<li data-go="/plan/${encodeURIComponent(r.id)}">
        <div class="r-title"><span class="badge badge-plan">${kind === "recht" ? "RECHT" : "STATISTIK"}</span>${escHtml(r.title)}</div>
        <div class="r-desc">${escHtml(r.beschreibung)}</div>
        <div class="r-desc" style="color:var(--muted)">${r.n} Dokument${r.n === 1 ? "" : "e"}${r.erstellt ? " · " + escHtml(r.erstellt) : ""}</div>
      </li>`).join("")}
    </ul></div>`;
  for (const li of view().querySelectorAll("li[data-go]"))
    li.addEventListener("click", () => go(li.dataset.go));
  status(`${rows.length} Einträge.`);
}

async function renderPlan(planId) {
  const [p] = await q(
    `SELECT id, kind, title, beschreibung, quelle_url, themen FROM plans WHERE id = '${esc(planId)}'`);
  if (!p) { view().innerHTML = `<div class="wrap">${crumb()}<p class="hint">Eintrag nicht gefunden.</p></div>`; return; }
  const files = await q(
    `SELECT rowid::VARCHAR AS id, titel, path, quelle_url, pages, (text IS NOT NULL) AS has_text
     FROM plan_files WHERE plan_id = '${esc(planId)}' ORDER BY titel`);
  const back = p.kind === "recht" ? "#/recht" : "#/statistik";
  view().innerHTML = `<div class="wrap">
    <a class="crumb" href="${back}">‹ ${p.kind === "recht" ? "Satzung & Recht" : "Statistik"}</a>
    <div class="doc-head">
      <h2><span class="badge badge-plan">${p.kind === "recht" ? "RECHT" : "STATISTIK"}</span>${escHtml(p.title)}</h2>
      ${p.beschreibung ? `<p class="meta">${escHtml(p.beschreibung)}</p>` : ""}
      ${p.themen ? `<p class="meta">Themen: ${themenText(p.themen).map(escHtml).join(", ")}</p>` : ""}
      ${p.quelle_url ? `<div class="doc-actions"><a href="${escHtml(p.quelle_url)}" target="_blank" rel="noopener">🔗 Quelle bei der Stadt Erlangen</a></div>` : ""}
    </div>
    ${files.length ? `<ul class="plan-files">${files.map((f) => `<li>
      ${f.has_text || f.path ? `<a href="#/planfile/${encodeURIComponent(f.id)}">${escHtml(f.titel)}</a>`
        : `<span>${escHtml(f.titel)}</span>`}
      ${f.pages ? `<span class="d-pages"> · ${f.pages} S.</span>` : ""}
      ${f.quelle_url ? ` · <a href="${escHtml(f.quelle_url)}" target="_blank" rel="noopener">Original öffnen</a>` : ""}
    </li>`).join("")}</ul>` : `<p class="hint">Keine hinterlegten Dateien — siehe Quelle oben.</p>`}
  </div>`;
  status(escHtml(p.title));
}

async function renderPlanFile(rowid) {
  const [f] = await q(
    `SELECT pf.titel, pf.path, pf.quelle_url, pf.pages, pf.text, p.id AS plan_id, p.kind, p.title AS plan_title
     FROM plan_files pf JOIN plans p ON p.id = pf.plan_id WHERE pf.rowid = ${Number(rowid)}`);
  if (!f) { view().innerHTML = `<div class="wrap">${crumb()}<p class="hint">Datei nicht gefunden.</p></div>`; return; }
  view().innerHTML = `<div class="wrap">
    <a class="crumb" href="#/plan/${encodeURIComponent(f.plan_id)}">‹ ${escHtml(shortLabel(f.plan_title, 40))}</a>
    <div class="doc-head">
      <h2><span class="badge badge-plan">${f.kind === "recht" ? "RECHT" : "STATISTIK"}</span>${escHtml(f.titel)}</h2>
      <p class="meta">${escHtml(f.plan_title)}${f.pages ? ` · ${f.pages} Seiten` : ""}</p>
      <div class="doc-actions">
        <button id="btn-text" class="active" type="button">Text</button>
        ${f.path ? `<button id="btn-pdf" type="button">PDF</button>` : ""}
        ${f.quelle_url ? `<a href="${escHtml(f.quelle_url)}" target="_blank" rel="noopener">⬇ Original öffnen</a>` : ""}
      </div>
    </div>
    <div id="doc-notice" class="notice" hidden></div>
    <div id="doc-body"></div>
  </div>`;
  renderDocText(f);
  if (f.path) $("btn-pdf").addEventListener("click", () => showPdf(f, f.quelle_url));
  $("btn-text").addEventListener("click", () => {
    renderDocText(f); $("btn-text").classList.add("active"); $("btn-pdf")?.classList.remove("active");
  });
  status(escHtml(f.titel));
}

// ── PDF-Anzeige (jsDelivr aus öffentlichem Repo) ─────────────────────────────

const PDF_SOURCES = [
  (p) => `https://cdn.jsdelivr.net/gh/${REPO}@main/${p}`,
  (p) => `https://raw.githubusercontent.com/${REPO}/main/${p}`,
];
const PDF_SIZE_WARN = 12 * 1024 * 1024;
let pdfBlobUrl = null;

function notice(msg) { const el = $("doc-notice"); if (!el) return; el.innerHTML = msg; el.hidden = !msg; }

async function headSize(path) {
  const p = encodeURI(path);
  for (const src of PDF_SOURCES) {
    try { const r = await fetch(src(p), { method: "HEAD" });
      if (r.ok) { const l = r.headers.get("content-length"); return l ? Number(l) : null; } } catch {}
  }
  return null;
}
async function fetchPdf(path) {
  const p = encodeURI(path);
  for (const src of PDF_SOURCES) {
    try { const r = await fetch(src(p)); if (r.ok) return new Uint8Array(await r.arrayBuffer()); } catch {}
  }
  return null;
}
async function showPdf(d, sourceUrl) {
  if (!d.path) { notice("Dieses Dokument ist nur extern verfügbar — bitte „Original öffnen“ nutzen."); return; }
  status("Prüfe Dateigröße …");
  const size = await headSize(d.path);
  if (size != null && size > PDF_SIZE_WARN) {
    notice(`Dieses PDF ist mit ${(size / 1048576).toFixed(1)} MB sehr groß und wird hier nicht automatisch geladen. `
      + (sourceUrl ? `Bitte das <a href="${escHtml(sourceUrl)}" target="_blank" rel="noopener">Original öffnen</a>.` : ""));
    status("PDF zu groß für die Inline-Anzeige.");
    return;
  }
  status("Lade PDF …");
  const bytes = await fetchPdf(d.path);
  if (!bytes) {
    notice("Dieses PDF ließ sich nicht laden — bitte das Original über den Link öffnen.");
    status("PDF nicht verfügbar."); return;
  }
  if (pdfBlobUrl) URL.revokeObjectURL(pdfBlobUrl);
  pdfBlobUrl = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
  $("doc-body").innerHTML = `<iframe class="pdf-frame" src="${pdfBlobUrl}" title="PDF-Ansicht"></iframe>`;
  $("btn-pdf").classList.add("active"); $("btn-text").classList.remove("active");
  status(`PDF angezeigt (${(bytes.length / 1048576).toFixed(1)} MB).`);
}

// ── Karten-Sektionen: Fachbeiräte / Ämter / Links ────────────────────────────

async function renderCards(key, title, icon) {
  const data = await loadContent(key);
  view().innerHTML = `<div class="wrap">${crumb()}
    <h2 class="section-title">${icon} ${escHtml(title)}</h2>
    ${data.intro ? `<p class="section-intro">${escHtml(data.intro)}</p>` : ""}
    <div class="cards">
      ${data.eintraege.map((e) => `<a class="card" href="${escHtml(e.url)}" target="_blank" rel="noopener">
        ${e.kategorie ? `<span class="c-tag">${escHtml(e.kategorie)}</span>` : ""}
        <div class="c-title">${escHtml(e.name)} <span class="ext">↗</span></div>
        <div class="c-desc">${escHtml(e.beschreibung || "")}</div>
      </a>`).join("")}
    </div></div>`;
  status(`${data.eintraege.length} Einträge.`);
}

async function renderAemter() {
  const data = await loadContent("aemter");
  view().innerHTML = `<div class="wrap">${crumb()}
    <h2 class="section-title">🏢 Ämter & Zuständigkeiten</h2>
    ${data.intro ? `<p class="section-intro">${escHtml(data.intro)}</p>` : ""}
    ${data.aemter_uebersicht_url ? `<div class="map-actions">
      <a class="btn-primary" href="${escHtml(data.aemter_uebersicht_url)}" target="_blank" rel="noopener">Ämter-Suche & Öffnungszeiten ↗</a></div>` : ""}
    <div class="cards">
      ${data.eintraege.map((e) => `<a class="card" href="${escHtml(e.url)}" target="_blank" rel="noopener">
        <div class="c-title">${escHtml(e.name)} <span class="ext">↗</span></div>
        <div class="c-zust">${escHtml(e.zustaendig || "")}</div>
      </a>`).join("")}
    </div></div>`;
  status(`${data.eintraege.length} Ämter.`);
}

// ── Karte (Leaflet + amtliche Kacheln, BayernAtlas-Deeplink) ─────────────────

let leafletLoading = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (leafletLoading) return leafletLoading;
  leafletLoading = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js";
    s.onload = resolve; s.onerror = () => reject(new Error("Leaflet konnte nicht geladen werden."));
    document.head.appendChild(s);
  });
  return leafletLoading;
}

async function renderKarte() {
  const cfg = await loadContent("karte");
  view().innerHTML = `<div class="wrap">${crumb()}
    <h2 class="section-title">🗺️ Karte</h2>
    ${cfg.intro ? `<p class="section-intro">${escHtml(cfg.intro)}</p>` : ""}
    <div class="map-actions">
      <a class="btn-primary" href="${escHtml(cfg.bayernatlas_url)}" target="_blank" rel="noopener">${escHtml(cfg.bayernatlas_label || "Im BayernAtlas öffnen")} ↗</a>
    </div>
    <div id="map"></div></div>`;
  status("Lade Karte …");
  try {
    await loadLeaflet();
  } catch (e) {
    $("map").innerHTML = `<p class="hint" style="padding:1rem">${escHtml(e.message)} Bitte den BayernAtlas-Link oben nutzen.</p>`;
    return;
  }
  const L = window.L;
  const map = L.map("map").setView(cfg.center, cfg.zoom);
  const layers = {};
  let base = null;
  for (const l of cfg.layers) {
    const t = L.tileLayer(l.url, { attribution: l.attribution, maxZoom: l.maxZoom || 19 });
    layers[l.name] = t;
    if (l.default || !base) base = t;
  }
  base.addTo(map);
  if (Object.keys(layers).length > 1) L.control.layers(layers).addTo(map);
  for (const m of cfg.marker || []) {
    L.marker([m.lat, m.lon]).addTo(map)
      .bindPopup(`<strong>${escHtml(m.titel)}</strong>${m.beschreibung ? "<br>" + escHtml(m.beschreibung) : ""}`);
  }
  setTimeout(() => map.invalidateSize(), 100);
  status("Karte geladen. Für amtliche Fachdaten den BayernAtlas-Button nutzen.");
}

// ── Boot ─────────────────────────────────────────────────────────────────────

$("version").textContent = APP_VERSION;
$("search-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const query = $("search-input").value.trim();
  if (query) go(`/suche/${encodeURIComponent(query)}`);
});
window.addEventListener("hashchange", route);

try {
  await checkAuth();
  await initDb();
  $("boot").hidden = true;
  await route();
} catch (err) {
  bootMsg(`Fehler: ${err.message}`);
  console.error(err);
}
