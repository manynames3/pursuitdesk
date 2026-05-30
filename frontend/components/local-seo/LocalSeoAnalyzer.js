import {
  analyzeLocalSeo,
  localSeoReportToCsv,
  localSeoReportToMarkdown,
} from "../../lib/localSeo/analyzeLocalSeo.js";

export function initializeLocalSeoAnalyzer(root = document.querySelector("#local-seo-analyzer")) {
  if (!root) return;

  const form = root.querySelector("#local-seo-form");
  const results = root.querySelector("#local-seo-results");
  const status = root.querySelector("#local-seo-status");
  let currentReport = null;

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    currentReport = analyzeLocalSeo(readLocalSeoForm(form));
    renderReport(results, currentReport);
    setStatus(status, "Estimated authority gap report generated.", "success");
    results?.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-local-seo-export]");
    if (!button || !currentReport) return;
    try {
      await handleExport(button.dataset.localSeoExport, currentReport, status);
    } catch {
      setStatus(status, "Export failed. Please try another export option.", "error");
    }
  });
}

function readLocalSeoForm(form) {
  const value = (name) => String(form.elements.namedItem(name)?.value || "").trim();
  return {
    websiteUrl: value("websiteUrl"),
    businessName: value("businessName"),
    targetCity: value("targetCity"),
    targetState: value("targetState"),
    mainKeyword: value("mainKeyword"),
    mapsUrl: value("mapsUrl"),
    notes: value("notes"),
    competitors: [1, 2, 3].map((index) => ({
      websiteUrl: value(`competitor${index}Url`),
      mapsUrl: value(`competitor${index}MapsUrl`),
    })),
  };
}

function renderReport(container, report) {
  if (!container) return;
  const totalScore = report.scores[report.scores.length - 1] || { band: "weak", value: 0 };
  container.hidden = false;
  container.innerHTML = [
    `<div class="local-seo-report-header">`,
    `<div>`,
    `<p class="eyebrow">Local SEO Authority Gap Report</p>`,
    `<h3>${escapeHtml(report.input.businessName || "Business")} in ${escapeHtml(report.input.targetCity || "Target City")}</h3>`,
    `<p>${escapeHtml(report.summary)}</p>`,
    `</div>`,
    `<div class="local-seo-summary-card ${bandClass(totalScore.band)}">`,
    `<span>Total opportunity score</span>`,
    `<strong>${totalScore.value || 0}/100</strong>`,
    `<small>${escapeHtml(report.mode)}</small>`,
    `</div>`,
    `</div>`,
    `<div class="local-seo-export-bar" aria-label="Local SEO export options">`,
    `<button type="button" class="secondary compact-button" data-local-seo-export="copy">Copy report</button>`,
    `<button type="button" class="secondary compact-button" data-local-seo-export="json">Download JSON</button>`,
    `<button type="button" class="secondary compact-button" data-local-seo-export="csv">Download CSV</button>`,
    `<button type="button" class="secondary compact-button" data-local-seo-export="print">Print report</button>`,
    `</div>`,
    renderScoreCards(report),
    renderCompetitorTable(report),
    renderTopicGaps(report),
    renderEntitySignals(report),
    renderInternalLinks(report),
    renderAiReadiness(report),
    renderRoadmap(report),
    renderAssumptions(report),
  ].join("");
}

function renderScoreCards(report) {
  return [
    `<section class="local-seo-section" aria-label="Overall scorecards">`,
    `<div class="local-seo-section-title"><h3>Overall scorecards</h3><span>0-100 estimated strength</span></div>`,
    `<div class="local-seo-score-grid">`,
    ...report.scores.map((score) => [
      `<article class="local-seo-score-card ${bandClass(score.band)}">`,
      `<div><span>${escapeHtml(score.label)}</span><strong>${score.value}</strong></div>`,
      `<div class="local-seo-progress" style="--score-width: ${score.value}%"><span></span></div>`,
      `<p>${escapeHtml(score.summary)}</p>`,
      `</article>`,
    ].join("")),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderCompetitorTable(report) {
  return [
    `<section class="local-seo-section" aria-label="Competitor comparison">`,
    `<div class="local-seo-section-title"><h3>Competitor comparison</h3><span>${report.competitors.length - 1} competitor URLs provided</span></div>`,
    `<div class="local-seo-table-wrap">`,
    `<table class="local-seo-competitor-table">`,
    `<thead><tr>`,
    ...["Website", "Estimated topical coverage", "Service page depth", "City/location relevance", "Trust signals", "Internal linking", "Schema readiness", "Content freshness", "Overall strength"].map((heading) => `<th>${heading}</th>`),
    `</tr></thead>`,
    `<tbody>`,
    ...report.competitors.map((item) => [
      `<tr class="${item.isUser ? "is-user" : ""}">`,
      `<td><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.website)}</span><small>${escapeHtml(item.note)}</small></td>`,
      tableScore(item.topicalCoverage),
      tableScore(item.servicePageDepth),
      tableScore(item.cityRelevance),
      tableScore(item.trustSignals),
      tableScore(item.internalLinking),
      tableScore(item.schemaReadiness),
      tableScore(item.contentFreshness),
      tableScore(item.overallStrength),
      `</tr>`,
    ].join("")),
    `</tbody>`,
    `</table>`,
    `</div>`,
    `</section>`,
  ].join("");
}

function renderTopicGaps(report) {
  return [
    `<section class="local-seo-section" aria-label="Topic gap analysis">`,
    `<div class="local-seo-section-title"><h3>Topic gap analysis</h3><span>Keyword and city-specific build list</span></div>`,
    `<div class="local-seo-topic-grid">`,
    ...report.topicGaps.map((gap) => [
      `<article class="local-seo-topic-card">`,
      `<div><strong>${escapeHtml(gap.topic)}</strong><span>${escapeHtml(gap.type)}</span></div>`,
      `<p>${escapeHtml(gap.why)}</p>`,
      `<footer><span>${escapeHtml(gap.suggestedPageType)}</span><strong>${gap.priority}/100</strong></footer>`,
      `</article>`,
    ].join("")),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderEntitySignals(report) {
  return [
    `<section class="local-seo-section" aria-label="Entity signal analysis">`,
    `<div class="local-seo-section-title"><h3>Entity signal analysis</h3><span>Consistency, proof, and schema checks</span></div>`,
    `<div class="local-seo-check-grid">`,
    ...report.entitySignals.map(renderSignal),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderInternalLinks(report) {
  return [
    `<section class="local-seo-section" aria-label="Internal linking problems">`,
    `<div class="local-seo-section-title"><h3>Internal linking plan</h3><span>Recommended authority paths</span></div>`,
    `<div class="local-seo-link-plan">`,
    ...report.internalLinks.map((link) => [
      `<article>`,
      `<div><strong>${escapeHtml(link.from)}</strong><span>to</span><strong>${escapeHtml(link.to)}</strong></div>`,
      `<p><b>Anchor:</b> ${escapeHtml(link.anchor)}</p>`,
      `<p>${escapeHtml(link.reason)}</p>`,
      `</article>`,
    ].join("")),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderAiReadiness(report) {
  return [
    `<section class="local-seo-section" aria-label="AI search readiness">`,
    `<div class="local-seo-section-title"><h3>AI search readiness</h3><span>Entity clarity for answer systems</span></div>`,
    `<div class="local-seo-check-grid">`,
    ...report.aiSearchReadiness.map(renderSignal),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderRoadmap(report) {
  return [
    `<section class="local-seo-section" aria-label="Priority roadmap">`,
    `<div class="local-seo-section-title"><h3>Priority roadmap</h3><span>Sequenced action plan</span></div>`,
    `<div class="local-seo-roadmap">`,
    roadmapGroup("Fix this week", report.roadmap.thisWeek),
    roadmapGroup("Build this month", report.roadmap.thisMonth),
    roadmapGroup("Build next quarter", report.roadmap.nextQuarter),
    `</div>`,
    `</section>`,
  ].join("");
}

function renderAssumptions(report) {
  return [
    `<section class="local-seo-section local-seo-assumptions" aria-label="Assumptions and future integrations">`,
    `<div>`,
    `<h3>Assumptions</h3>`,
    `<ul>${report.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`,
    `</div>`,
    `<div>`,
    `<h3>Future API connections</h3>`,
    `<ul>${report.todos.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`,
    `</div>`,
    `</section>`,
  ].join("");
}

function renderSignal(signal) {
  return [
    `<article class="local-seo-signal ${signal.status}">`,
    `<div><span>${statusLabel(signal.status)}</span><strong>${escapeHtml(signal.label)}</strong></div>`,
    `<p>${escapeHtml(signal.evidence)}</p>`,
    `<small>${escapeHtml(signal.recommendation)}</small>`,
    `</article>`,
  ].join("");
}

function roadmapGroup(title, tasks) {
  return [
    `<div class="local-seo-roadmap-group">`,
    `<h4>${escapeHtml(title)}</h4>`,
    ...tasks.map((task) => [
      `<article>`,
      `<div><strong>${escapeHtml(task.task)}</strong><span>${task.priority}/100</span></div>`,
      `<p>${escapeHtml(task.why)}</p>`,
      `<footer><span>Impact: ${escapeHtml(task.impact)}</span><span>Difficulty: ${escapeHtml(task.difficulty)}</span></footer>`,
      `</article>`,
    ].join("")),
    `</div>`,
  ].join("");
}

function tableScore(value) {
  return `<td><span class="local-seo-table-score ${bandClass(valueBand(value))}">${value}</span></td>`;
}

function valueBand(value) {
  if (value >= 72) return "strong";
  if (value >= 48) return "moderate";
  return "weak";
}

async function handleExport(action, report, status) {
  const filename = safeFilename(`local-seo-gap-report-${report.input.businessName || report.input.targetCity || "business"}`);
  if (action === "copy") {
    await navigator.clipboard.writeText(localSeoReportToMarkdown(report));
    setStatus(status, "Report copied to clipboard.", "success");
    return;
  }
  if (action === "json") {
    downloadBlob(new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" }), `${filename}.json`);
    setStatus(status, "JSON report downloaded.", "success");
    return;
  }
  if (action === "csv") {
    downloadBlob(new Blob([localSeoReportToCsv(report)], { type: "text/csv;charset=utf-8" }), `${filename}.csv`);
    setStatus(status, "CSV report downloaded.", "success");
    return;
  }
  if (action === "print") {
    window.print();
  }
}

function setStatus(element, message, state = "") {
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("is-success", state === "success");
  element.classList.toggle("is-error", state === "error");
}

function bandClass(band) {
  return `is-${band || "weak"}`;
}

function statusLabel(status) {
  if (status === "strong") return "Strong";
  if (status === "needs-work") return "Needs work";
  return "Missing";
}

function safeFilename(value) {
  return String(value || "local-seo-report")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 90) || "local-seo-report";
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    const escapes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return escapes[char];
  });
}
