const apiBaseUrl = window.CAPTUREOS_API_BASE_URL || "";
const opportunityPageSize = 25;

const fallbackOpportunities = [
  {
    opportunity_id: "6d3cabc7-5170-4378-8c7e-46af9c216663",
    notice_id: "affa8684215e4acda30c8179fe9125c1",
    title: "Interferometric Displacement Measuring System",
    naics_code: "334516",
    psc_code: "6650",
    funding_agency_name: "ENERGY, DEPARTMENT OF",
    estimated_value_min: null,
    estimated_value_max: null,
    response_deadline: "2026-05-22T22:00:00Z",
    dashboard_relevance_score: 0.42,
    ui_link: "https://sam.gov/opp/affa8684215e4acda30c8179fe9125c1/view",
    posted_at: "2026-05-16T00:00:00Z",
  },
  {
    opportunity_id: "9fdba1d65c4542fc852a10dc470df999",
    notice_id: "9fdba1d65c4542fc852a10dc470df999",
    title: "Facility Investment Services - Arizona and New Mexico",
    naics_code: "561210",
    psc_code: "M1JZ",
    funding_agency_name: "DEPT OF DEFENSE",
    estimated_value_min: null,
    estimated_value_max: null,
    response_deadline: "2026-05-26T15:00:00Z",
    dashboard_relevance_score: 0.38,
    ui_link: "https://sam.gov/opp/9fdba1d65c4542fc852a10dc470df999/view",
    posted_at: "2026-05-12T00:00:00Z",
  },
];

const fallbackTeams = [
  {
    tenant_slug: "demo-growth",
    tenant_name: "Apex Analytica Federal Growth Team",
    company_name: "Apex Analytica Federal Growth Team",
    user_email: "capture.lead@example.com",
    contract_vehicles: ["GSA MAS IT", "OASIS+"],
    clearance_levels: ["Secret"],
    set_aside_eligibilities: ["Small Business"],
    target_naics_codes: ["541512", "541511", "541715"],
    target_psc_codes: ["DA01", "DA10", "AC12", "R425"],
  },
  {
    tenant_slug: "metal-fabrication-shop",
    tenant_name: "Keystone Metal Fabrication Shop",
    company_name: "Keystone Metal Fabrication Shop",
    user_email: "owner@keystonemetal.example",
    contract_vehicles: ["DIBBS", "SAM.gov Open Market", "GSA MAS Industrial Products"],
    clearance_levels: ["Facility access eligible"],
    set_aside_eligibilities: ["Small Business"],
    target_naics_codes: ["332312", "332313", "332322", "332710", "332999", "336413"],
    target_psc_codes: ["1560", "1730", "5340", "5450", "9520", "9530", "9540"],
  },
];

const fallbackAnalysis = {
  opportunity: fallbackOpportunities[0],
  customer_profile: {
    company_name: "Apex Analytica Federal Growth Team",
    contract_vehicles: ["GSA MAS IT", "OASIS+"],
    clearance_levels: ["Secret"],
    set_aside_eligibilities: ["Small Business"],
  },
  customer_score: {
    company_adjusted_p_win: 0.18,
    market_baseline_p_win: 0.16,
    delta_vs_market: 0.02,
    profile_fit_score: 0.45,
    factors: [
      { label: "NAICS fit", score: 0.45, evidence: "Live SAM.gov record available; customer fit pending enrichment" },
      { label: "Agency relationship", score: 0.25, evidence: "No customer import matched in offline fallback mode" },
      { label: "Contract vehicle posture", score: 0.35, evidence: "Vehicle requirements pending document extraction" },
    ],
  },
  workflow: { status: "tracking", go_no_go: "undecided", priority: "medium", stage: "Qualification", owner_name: "Capture Lead" },
  notes: [{ body: "Live SAM.gov fallback snapshot loaded. Full analysis requires the API to be reachable.", author_name: "Capture Lead", created_at: "2026-05-22T12:00:00Z" }],
  competing_primes: [],
  target_teaming_subs: [],
  calc_plus_benchmarks: [
    { labor_rate_id: "demo-rate-1", labor_category: "Cloud Architect", education_level: "Bachelor's", min_years_experience: 8, site: "CONUS", ceiling_hourly_rate: 221.4, percentile_75_hourly_rate: 192.13, benchmark_match_score: 1 },
    { labor_rate_id: "demo-rate-2", labor_category: "Cyber Security Engineer", education_level: "Bachelor's", min_years_experience: 7, site: "CONUS", ceiling_hourly_rate: 212.49, percentile_75_hourly_rate: 183.17, benchmark_match_score: 0.9 },
  ],
  competitive_baseline: {
    estimated_p_win: 0.18,
    confidence: "low",
    historical_match_count: 0,
    total_matched_obligation: 0,
  },
  market_baseline: { estimated_p_win: 0.16 },
  evidence: {
    coverage: { opportunity: 1, award: 0, subaward: 0, labor_rate: 2 },
    items: [
      { evidence_type: "opportunity", source_system: "SAM.gov", source_title: "Interferometric Displacement Measuring System", source_url: "https://sam.gov/opp/affa8684215e4acda30c8179fe9125c1/view", explanation: "Live SAM.gov opportunity snapshot used when the API is temporarily unreachable.", confidence: 1 },
    ],
    score_factors: [],
  },
  data_freshness: [
    { source_system: "SAM.gov", dataset_name: "Opportunities", source_mode: "live_api", freshness_state: "fresh", last_successful_sync_at: "2026-05-22T12:00:00Z", record_count: 981 },
    { source_system: "FSRS", dataset_name: "Subaward Reporting", source_mode: "live_api", freshness_state: "fresh", last_successful_sync_at: "2026-05-24T06:44:00Z", record_count: 488 },
    { source_system: "GSA CALC+", dataset_name: "Labor Rate Benchmarks", source_mode: "live_api", freshness_state: "fresh", last_successful_sync_at: "2026-05-24T06:44:00Z", record_count: 646 },
    { source_system: "USAspending", dataset_name: "Contract Awards", source_mode: "live_api", freshness_state: "fresh", last_successful_sync_at: "2026-05-24T06:44:00Z", record_count: 925 },
  ],
  past_performance: [
    { contract_number: "RAF-FA8773-24-F-0112", title: "Zero Trust Platform Engineering", role: "subcontractor", agency_name: "Department of the Air Force", obligated_amount: 18400000 },
    { contract_number: "RAF-W56KGY-25-F-0041", title: "Mission Data Fabric DevSecOps", role: "subcontractor", agency_name: "Department of the Army", obligated_amount: 22900000 },
  ],
  billing: { subscription_status: "trialing", current_period_ends_at: "2026-06-21T12:00:00Z" },
  compliance_controls: [
    { control_key: "auth.jwt", control_family: "Access Control", control_name: "JWT issuer, audience, and JWKS validation", implementation_status: "implemented" },
    { control_key: "audit.workflow", control_family: "Audit", control_name: "Workflow mutation audit trail", implementation_status: "implemented" },
  ],
  security_context: { tenant_name: "Apex Analytica Federal Growth Team", role: "capture_manager", auth_mode: "demo_header_context" },
};

let currentOpportunityId = null;
let currentAnalysis = null;
let loadedOpportunities = [];
let totalOpportunities = 0;
let customerTeams = [...fallbackTeams];
let selectedTenantSlug = localStorage.getItem("captureosTenantSlug") || "demo-growth";
let consultantWorkspace = null;

const els = {
  apiStatus: document.querySelector("#api-status"),
  securityStatus: document.querySelector("#security-status"),
  teamSelect: document.querySelector("#team-select"),
  refresh: document.querySelector("#refresh"),
  trackGo: document.querySelector("#track-go"),
  trackNoGo: document.querySelector("#track-no-go"),
  exportBrief: document.querySelector("#export-brief"),
  exportClientReport: document.querySelector("#export-client-report"),
  demoFlowStart: document.querySelector("#demo-flow-start"),
  positioningHeadline: document.querySelector("#positioning-headline"),
  positioningPromise: document.querySelector("#positioning-promise"),
  demoFlow: document.querySelector("#demo-flow"),
  clientIntake: document.querySelector("#client-intake"),
  intakeCompany: document.querySelector("#intake-company"),
  intakeEmail: document.querySelector("#intake-email"),
  intakeUei: document.querySelector("#intake-uei"),
  intakeCage: document.querySelector("#intake-cage"),
  intakeNaics: document.querySelector("#intake-naics"),
  intakeSetAsides: document.querySelector("#intake-set-asides"),
  portfolioClientCount: document.querySelector("#portfolio-client-count"),
  portfolioPrimeReady: document.querySelector("#portfolio-prime-ready"),
  portfolioPipeline: document.querySelector("#portfolio-pipeline"),
  portfolioReadiness: document.querySelector("#portfolio-readiness"),
  clientCards: document.querySelector("#client-cards"),
  readinessScore: document.querySelector("#readiness-score"),
  readinessLabel: document.querySelector("#readiness-label"),
  readinessGaps: document.querySelector("#readiness-gaps"),
  recommendedOpps: document.querySelector("#recommended-opps"),
  consultantDeliverables: document.querySelector("#consultant-deliverables"),
  clientPortal: document.querySelector("#client-portal"),
  reminderForm: document.querySelector("#reminder-form"),
  reminderTitle: document.querySelector("#reminder-title"),
  reminderDue: document.querySelector("#reminder-due"),
  recompeteSignals: document.querySelector("#recompete-signals"),
  whiteLabelForm: document.querySelector("#white-label-form"),
  brandName: document.querySelector("#brand-name"),
  brandColor: document.querySelector("#brand-color"),
  brandEmail: document.querySelector("#brand-email"),
  trustPosture: document.querySelector("#trust-posture"),
  monitoringAlerts: document.querySelector("#monitoring-alerts"),
  demoDataAudit: document.querySelector("#demo-data-audit"),
  opportunities: document.querySelector("#opportunities"),
  opportunityCount: document.querySelector("#opportunity-count"),
  opportunityRange: document.querySelector("#opportunity-range"),
  loadMore: document.querySelector("#load-more"),
  analysisTitle: document.querySelector("#analysis-title"),
  analysisSubhead: document.querySelector("#analysis-subhead"),
  pwin: document.querySelector("#pwin"),
  marketPwin: document.querySelector("#market-pwin"),
  pwinDelta: document.querySelector("#pwin-delta"),
  profileFit: document.querySelector("#profile-fit"),
  recommendedAction: document.querySelector("#recommended-action"),
  recommendedRationale: document.querySelector("#recommended-rationale"),
  captureTasks: document.querySelector("#capture-tasks"),
  opportunityDeliverables: document.querySelector("#opportunity-deliverables"),
  confidence: document.querySelector("#confidence"),
  matchCount: document.querySelector("#match-count"),
  matchedObligation: document.querySelector("#matched-obligation"),
  customerName: document.querySelector("#customer-name"),
  customerVehicles: document.querySelector("#customer-vehicles"),
  customerClearance: document.querySelector("#customer-clearance"),
  fitFactors: document.querySelector("#fit-factors"),
  workflow: document.querySelector("#workflow"),
  freshness: document.querySelector("#freshness"),
  pastPerformance: document.querySelector("#past-performance"),
  billing: document.querySelector("#billing"),
  compliance: document.querySelector("#compliance"),
  primes: document.querySelector("#primes"),
  subs: document.querySelector("#subs"),
  rates: document.querySelector("#rates"),
  evidence: document.querySelector("#evidence"),
  notes: document.querySelector("#notes"),
};

els.teamSelect.addEventListener("change", async () => {
  selectedTenantSlug = els.teamSelect.value;
  localStorage.setItem("captureosTenantSlug", selectedTenantSlug);
  currentOpportunityId = null;
  currentAnalysis = null;
  await loadConsultantWorkspace();
  await loadOpportunities({ append: false });
});
els.refresh.addEventListener("click", () => loadOpportunities({ append: false }));
els.loadMore.addEventListener("click", () => loadOpportunities({ append: true }));
els.trackGo.addEventListener("click", () => updateWorkflow("go"));
els.trackNoGo.addEventListener("click", () => updateWorkflow("no_go"));
els.exportBrief.addEventListener("click", exportBrief);
els.exportClientReport.addEventListener("click", exportClientReport);
els.demoFlowStart.addEventListener("click", () => els.intakeCompany.focus());
els.clientIntake.addEventListener("submit", submitClientIntake);
els.reminderForm.addEventListener("submit", submitReminder);
els.whiteLabelForm.addEventListener("submit", submitWhiteLabel);

initialize();

async function initialize() {
  await loadCustomerTeams();
  await loadConsultantWorkspace();
  await loadOpportunities({ append: false });
}

async function loadCustomerTeams() {
  try {
    const data = await fetchJson(`${apiBaseUrl}/api/v1/customer-teams`);
    customerTeams = data.items?.length ? data.items.map(normalizeTeam) : [...fallbackTeams];
  } catch (error) {
    customerTeams = [...fallbackTeams];
  }
  if (!customerTeams.some((team) => team.tenant_slug === selectedTenantSlug)) {
    selectedTenantSlug = customerTeams[0]?.tenant_slug || "demo-growth";
    localStorage.setItem("captureosTenantSlug", selectedTenantSlug);
  }
  renderTeamSelect();
}

function renderTeamSelect() {
  els.teamSelect.innerHTML = customerTeams.map((team) => (
    `<option value="${escapeHtml(team.tenant_slug)}">${escapeHtml(team.tenant_name || team.company_name)}</option>`
  )).join("");
  els.teamSelect.value = selectedTenantSlug;
}

async function loadConsultantWorkspace() {
  try {
    consultantWorkspace = await fetchJson(`${apiBaseUrl}/api/v1/consultant/workspace`);
    setApiStatus("Live API");
  } catch (error) {
    consultantWorkspace = buildFallbackWorkspace();
    setApiStatus("Local demo data");
  }
  renderConsultantWorkspace(consultantWorkspace);
}

async function loadOpportunities({ append = false } = {}) {
  const offset = append ? loadedOpportunities.length : 0;
  const params = buildOpportunityParams(offset);

  els.loadMore.disabled = true;

  let data;
  try {
    data = await fetchJson(`${apiBaseUrl}/api/v1/opportunities/active?${params.toString()}`);
    setApiStatus("Live API");
  } catch (error) {
    if (append) {
      setApiStatus("Local demo data");
      renderOpportunities(loadedOpportunities, totalOpportunities);
      return;
    }
    data = { items: fallbackOpportunities, pagination: { total: fallbackOpportunities.length } };
    setApiStatus("Local demo data");
  }

  const incoming = data.items || [];
  loadedOpportunities = append ? [...loadedOpportunities, ...incoming] : incoming;
  totalOpportunities = Number(data.pagination?.total ?? loadedOpportunities.length);
  renderOpportunities(loadedOpportunities, totalOpportunities);
  const first = append ? null : loadedOpportunities[0];
  if (first) {
    await loadAnalysis(first.opportunity_id || first.notice_id);
  }
}

function buildOpportunityParams(offset) {
  const params = new URLSearchParams({
    limit: String(opportunityPageSize),
    offset: String(offset),
  });

  const search = valueOf("#search");
  const minValue = valueOf("#min-value");
  const maxValue = valueOf("#max-value");
  if (search) params.set("q", search);
  if (minValue) params.set("min_value", minValue);
  if (maxValue) params.set("max_value", maxValue);
  splitCodes(valueOf("#naics")).forEach((code) => params.append("naics_codes", code));
  splitCodes(valueOf("#psc")).forEach((code) => params.append("psc_codes", code));
  return params;
}

async function loadAnalysis(opportunityId) {
  currentOpportunityId = opportunityId;
  setActiveOpportunity(opportunityId);
  const selectedOpportunity = findLoadedOpportunity(opportunityId);
  let data;
  try {
    data = await fetchJson(`${apiBaseUrl}/api/v1/capture-analysis/${encodeURIComponent(opportunityId)}`);
    setApiStatus("Live API");
  } catch (error) {
    const fallback = buildFallbackAnalysis(selectedOpportunity, opportunityId);
    data = {
      ...fallback,
      opportunity: selectedOpportunity || fallbackOpportunities.find((item) => item.opportunity_id === opportunityId) || fallback.opportunity,
      competing_primes: selectedOpportunity ? [] : fallback.competing_primes,
      target_teaming_subs: selectedOpportunity ? [] : fallback.target_teaming_subs,
      competitive_baseline: selectedOpportunity
        ? {
            estimated_p_win: selectedTenantSlug === "metal-fabrication-shop" ? 0.22 : 0.18,
            confidence: "low",
            historical_match_count: 0,
            total_matched_obligation: 0,
          }
        : fallback.competitive_baseline,
      evidence: selectedOpportunity
        ? {
            coverage: { opportunity: 1 },
            items: [{
              evidence_type: "opportunity",
              source_system: "SAM.gov",
              source_title: selectedOpportunity.title,
              source_url: selectedOpportunity.ui_link,
              source_record_date: selectedOpportunity.posted_at,
              naics_code: selectedOpportunity.naics_code,
              psc_code: selectedOpportunity.psc_code,
              explanation: "Live SAM.gov opportunity selected; full capture analysis is pending enrichment.",
            }],
            score_factors: [],
          }
        : fallback.evidence,
    };
    setApiStatus("Local demo data");
  }
  currentAnalysis = data;
  renderAnalysis(data);
}

function findLoadedOpportunity(opportunityId) {
  return loadedOpportunities.find((item) => (
    item.opportunity_id === opportunityId
    || item.notice_id === opportunityId
  ));
}

async function updateWorkflow(goNoGo) {
  if (!currentOpportunityId) return;
  const payload = {
    go_no_go: goNoGo,
    status: goNoGo === "go" ? "qualifying" : "no_bid",
    priority: goNoGo === "go" ? "high" : "low",
    stage: goNoGo === "go" ? "Gate 2: Teaming" : "Closed: No-bid",
    decision_rationale: goNoGo === "go" ? "Marked go from executive dashboard." : "Marked no-go from executive dashboard.",
  };
  try {
    const result = await fetchJson(`${apiBaseUrl}/api/v1/opportunities/${encodeURIComponent(currentOpportunityId)}/track`, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify(payload),
    });
    if (currentAnalysis) {
      currentAnalysis.workflow = result.workflow;
      renderWorkflow(result.workflow);
    }
    setApiStatus("Live API");
  } catch (error) {
    if (currentAnalysis) {
      currentAnalysis.workflow = { ...(currentAnalysis.workflow || {}), ...payload };
      renderWorkflow(currentAnalysis.workflow);
    }
    setApiStatus("Local demo data");
  }
}

async function exportBrief() {
  if (!currentOpportunityId) return;
  const fallback = () => downloadText(renderLocalBrief(currentAnalysis || buildFallbackAnalysis()), `capture-brief-${currentOpportunityId}.md`);
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/capture-analysis/${encodeURIComponent(currentOpportunityId)}/brief.md`, {
      headers: requestHeaders({ accept: "text/markdown" }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    downloadText(await response.text(), `capture-brief-${currentOpportunityId}.md`);
  } catch (error) {
    fallback();
  }
}

async function exportClientReport() {
  const team = selectedTeam();
  const fallback = () => downloadText(renderLocalClientReport(consultantWorkspace || buildFallbackWorkspace()), `govcon-client-report-${team.tenant_slug}.md`);
  try {
    const response = await fetch(`${apiBaseUrl}/api/v1/consultant/client-report.md`, {
      headers: requestHeaders({ accept: "text/markdown" }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    downloadText(await response.text(), `govcon-client-report-${team.tenant_slug}.md`);
  } catch (error) {
    fallback();
  }
}

async function submitClientIntake(event) {
  event.preventDefault();
  const payload = {
    company_name: els.intakeCompany.value.trim(),
    primary_contact_email: els.intakeEmail.value.trim(),
    canonical_uei: els.intakeUei.value.trim().toUpperCase() || null,
    cage_code: els.intakeCage.value.trim().toUpperCase() || null,
    target_naics_codes: splitCodes(els.intakeNaics.value),
    set_aside_eligibilities: splitCodes(els.intakeSetAsides.value),
    socioeconomic_tags: splitCodes(els.intakeSetAsides.value),
    target_psc_codes: [],
    contract_vehicles: ["SAM.gov Open Market"],
    consultant_notes: "Created from public demo intake wizard.",
  };
  if (!payload.company_name || !payload.primary_contact_email) return;
  try {
    const result = await fetchJson(`${apiBaseUrl}/api/v1/consultant/clients/intake`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (result.client?.tenant_slug) {
      selectedTenantSlug = result.client.tenant_slug;
      localStorage.setItem("captureosTenantSlug", selectedTenantSlug);
    }
    consultantWorkspace = result.workspace || consultantWorkspace;
    await loadCustomerTeams();
    renderConsultantWorkspace(consultantWorkspace);
    await loadOpportunities({ append: false });
    els.clientIntake.reset();
    setApiStatus("Live API");
  } catch (error) {
    const created = addFallbackClient(payload);
    selectedTenantSlug = created.tenant_slug;
    localStorage.setItem("captureosTenantSlug", selectedTenantSlug);
    renderTeamSelect();
    consultantWorkspace = buildFallbackWorkspace();
    renderConsultantWorkspace(consultantWorkspace);
    setApiStatus("Local demo data");
  }
}

async function submitReminder(event) {
  event.preventDefault();
  const title = els.reminderTitle.value.trim();
  const due = els.reminderDue.value;
  if (!title || !due) return;
  try {
    await fetchJson(`${apiBaseUrl}/api/v1/consultant/reminders`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title,
        due_at: `${due}T17:00:00Z`,
        reminder_type: "client_follow_up",
        client_visible: true,
      }),
    });
    await loadConsultantWorkspace();
    els.reminderForm.reset();
    setApiStatus("Live API");
  } catch (error) {
    const active = consultantWorkspace?.active_client;
    if (active) {
      active.reminders = [
        ...(active.reminders || []),
        { title, due_at: `${due}T17:00:00Z`, reminder_type: "client_follow_up", client_visible: true },
      ];
      renderConsultantWorkspace(consultantWorkspace);
    }
    setApiStatus("Local demo data");
  }
}

async function submitWhiteLabel(event) {
  event.preventDefault();
  const payload = {
    organization_name: els.brandName.value.trim() || "GovCon Advisory Practice",
    primary_color: els.brandColor.value.trim() || "#0f766e",
    support_email: els.brandEmail.value.trim() || selectedTeam().user_email,
    report_footer: "Prepared by your GovCon advisor. Decision support only; not legal or procurement advice.",
  };
  try {
    const result = await fetchJson(`${apiBaseUrl}/api/v1/consultant/settings/white-label`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    consultantWorkspace.white_label = result.settings;
    renderConsultantWorkspace(consultantWorkspace);
    setApiStatus("Live API");
  } catch (error) {
    consultantWorkspace.white_label = payload;
    renderConsultantWorkspace(consultantWorkspace);
    setApiStatus("Local demo data");
  }
}

function renderOpportunities(items, total = items.length) {
  els.opportunityCount.textContent = numberFormat(total);
  els.opportunityRange.textContent = `Showing ${numberFormat(items.length)} of ${numberFormat(total)}`;
  els.loadMore.hidden = items.length >= total || total === 0;
  els.loadMore.disabled = items.length >= total || total === 0;
  els.opportunities.innerHTML = items.length
    ? items.map((item) => opportunityButton(item)).join("")
    : `<div class="empty">No active opportunities matched these filters.</div>`;

  els.opportunities.querySelectorAll(".opp").forEach((button) => {
    button.addEventListener("click", () => loadAnalysis(button.dataset.id));
  });
}

function renderConsultantWorkspace(workspace) {
  const portfolio = workspace.portfolio || {};
  const active = workspace.active_client || {};
  const readiness = active.readiness || {};
  const portal = active.client_portal || {};
  const clients = workspace.clients || [];
  const positioning = workspace.positioning || {};
  const whiteLabel = workspace.white_label || {};
  const disclaimer = workspace.legal_disclaimer || {};

  els.positioningHeadline.textContent = positioning.headline || "GovCon consulting delivery platform for small-business advisors";
  els.positioningPromise.textContent = positioning.promise || "Add a client, get readiness, get top pursuits, export a client report.";
  renderDemoFlow(workspace.demo_flow || []);
  els.brandName.value = whiteLabel.organization_name || "";
  els.brandColor.value = whiteLabel.primary_color || "#0f766e";
  els.brandEmail.value = whiteLabel.support_email || "";

  els.portfolioClientCount.textContent = numberFormat(portfolio.client_count);
  els.portfolioPrimeReady.textContent = numberFormat(portfolio.prime_ready_clients);
  els.portfolioPipeline.textContent = numberFormat(portfolio.tracked_pipeline_items);
  els.portfolioReadiness.textContent = percent(portfolio.average_readiness_score);

  els.clientCards.innerHTML = clients.length
    ? clients.map((client) => {
        const clientReadiness = client.readiness || {};
        const activeClass = client.tenant_slug === selectedTenantSlug ? " active-client" : "";
        return `
          <button class="client-row${activeClass}" type="button" data-tenant="${escapeHtml(client.tenant_slug)}">
            <strong>${escapeHtml(client.company_name || client.tenant_name)}</strong>
            <span>${escapeHtml(clientReadiness.label || "Readiness pending")} · ${percent(clientReadiness.score)}</span>
          </button>
        `;
      }).join("")
    : `<div class="empty">No client profiles available.</div>`;
  els.clientCards.querySelectorAll(".client-row").forEach((button) => {
    button.addEventListener("click", async () => {
      selectedTenantSlug = button.dataset.tenant;
      localStorage.setItem("captureosTenantSlug", selectedTenantSlug);
      els.teamSelect.value = selectedTenantSlug;
      await loadConsultantWorkspace();
      await loadOpportunities({ append: false });
    });
  });

  els.readinessScore.textContent = percent(readiness.score);
  els.readinessLabel.textContent = readiness.label || "Client readiness pending";
  els.readinessGaps.innerHTML = (readiness.gaps || []).length
    ? readiness.gaps.map((gap) => `
        <div class="row compact">
          <div class="row-title">
            <strong>${escapeHtml(gap.label)}</strong>
            <span class="badge">gap</span>
          </div>
          <div class="row-meta">${escapeHtml(gap.evidence || "")}</div>
        </div>
      `).join("")
    : `<div class="row compact"><strong>Ready for active pursuit management.</strong><div class="row-meta">No major readiness gaps found.</div></div>`;

  els.recommendedOpps.innerHTML = (active.recommended_opportunities || []).length
    ? active.recommended_opportunities.slice(0, 5).map((opp) => {
        const action = opp.recommended_action || {};
        return `
          <div class="row compact">
            <div class="row-title">
              <strong>${escapeHtml(opp.title)}</strong>
              <span class="badge ${escapeHtml(action.action || "watch")}">${escapeHtml(action.action || "watch")}</span>
            </div>
            <div class="row-meta">
              <span>${escapeHtml(opp.funding_agency_name || "--")}</span>
              <span>${escapeHtml(opp.naics_code || "--")}/${escapeHtml(opp.psc_code || "--")}</span>
              <span>${percent(opp.dashboard_relevance_score)} fit</span>
            </div>
            <div class="row-note">${escapeHtml(action.rationale || "")}</div>
          </div>
        `;
      }).join("")
    : `<div class="empty">No recommended pursuits matched this client profile yet.</div>`;

  renderSimpleRows(els.consultantDeliverables, workspace.deliverables || [], (item) => `
    <div class="row-title">
      <strong>${escapeHtml(item.name)}</strong>
      <span class="badge">${escapeHtml(item.status)}</span>
    </div>
    <div class="row-meta">${escapeHtml(item.description || "")}</div>
  `);

  const requests = portal.open_requests || [];
  const reminders = active.reminders || [];
  els.clientPortal.innerHTML = `
    <div class="row compact">
      <div class="row-title">
        <strong>${escapeHtml(portal.client_name || active.company_name || "--")}</strong>
        <span class="badge">${escapeHtml(portal.status || "pending")}</span>
      </div>
      <div class="row-meta">${escapeHtml((portal.visible_widgets || []).join(", ") || "Client portal widgets pending")}</div>
    </div>
    ${requests.length ? requests.map((request) => `<div class="row compact">${escapeHtml(request)}</div>`).join("") : `<div class="empty">No open client requests.</div>`}
    ${reminders.length ? reminders.slice(0, 4).map((reminder) => `
      <div class="row compact">
        <div class="row-title">
          <strong>${escapeHtml(reminder.title)}</strong>
          <span class="badge">${formatDate(reminder.due_at)}</span>
        </div>
        <div class="row-meta">${escapeHtml(reminder.reminder_type || "reminder")}</div>
      </div>
    `).join("") : ""}
  `;

  renderSimpleRows(els.recompeteSignals, active.recompete_signals || [], (item) => `
    <div class="row-title">
      <strong>${escapeHtml(item.title || item.award_number || "Award signal")}</strong>
      <span class="badge ${escapeHtml(item.signal_type || "watch")}">${escapeHtml(item.signal_type || "signal")}</span>
    </div>
    <div class="row-meta">
      <span>${escapeHtml(item.incumbent_name || "Incumbent pending")}</span>
      <span>${escapeHtml(item.funding_agency_name || "--")}</span>
      <span>PoP end ${formatDate(item.period_of_performance_end)}</span>
      <span>${money(item.award_value)}</span>
    </div>
  `);

  const trust = workspace.trust_posture || {};
  els.trustPosture.innerHTML = `
    <div class="row compact">
      <div class="row-title">
        <strong>${escapeHtml(trust.auth_mode || "auth pending")}</strong>
        <span class="badge">${escapeHtml(trust.billing_status || "billing")}</span>
      </div>
      <div class="row-meta">
        <span>${numberFormat(trust.live_source_count)} live sources</span>
        <span>${numberFormat(trust.mock_source_count)} demo sources</span>
      </div>
      <div class="row-note">${escapeHtml(trust.disclaimer || "")}</div>
      ${(disclaimer.limits || []).length ? `<div class="row-meta">${disclaimer.limits.slice(0, 2).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
    </div>
  `;
  renderMonitoringAlerts(workspace.ingest_alerts || {});
  renderDemoDataAudit(workspace.business_data_audit || {});
}

function renderDemoFlow(steps) {
  els.demoFlow.innerHTML = steps.length
    ? steps.map((step, index) => `
        <div class="flow-step">
          <span class="badge ${escapeHtml(step.status || "open")}">${escapeHtml(step.status || "open")}</span>
          <strong>${index + 1}. ${escapeHtml(step.step)}</strong>
          <small>${escapeHtml(step.description || "")}</small>
        </div>
      `).join("")
    : "";
}

function renderMonitoringAlerts(alerts) {
  const items = alerts.items || [];
  const liveItems = items.filter((item) => item.source_mode === "live_api" && item.severity !== "info");
  els.monitoringAlerts.innerHTML = `
    <div class="row compact">
      <div class="row-title">
        <strong>${escapeHtml(alerts.summary || "Ingest health pending")}</strong>
        <span class="badge ${escapeHtml(alerts.status || "unknown")}">${escapeHtml(alerts.status || "unknown")}</span>
      </div>
      <div class="row-meta">
        <span>${numberFormat(alerts.live_alert_count || 0)} live alerts</span>
        <span>${numberFormat(alerts.demo_source_count || 0)} demo sources</span>
      </div>
    </div>
    ${
      liveItems.length
        ? liveItems.slice(0, 4).map((item) => `
            <div class="row compact">
              <div class="row-title">
                <strong>${escapeHtml(item.source_system)} · ${escapeHtml(item.dataset_name)}</strong>
                <span class="badge ${escapeHtml(item.severity || "warning")}">${escapeHtml(item.freshness_state || item.sync_status || "alert")}</span>
              </div>
              <div class="row-meta">
                <span>${escapeHtml(item.sync_status || "--")}</span>
                <span>${numberFormat(item.record_count || 0)} rows</span>
              </div>
            </div>
          `).join("")
        : `<div class="row compact"><strong>No live ingest failures detected.</strong><div class="row-meta">SAM.gov, USAspending, FSRS, and GSA CALC+ freshness are monitored through source watermarks.</div></div>`
    }
  `;
}

function renderDemoDataAudit(audit) {
  const items = audit.items || [];
  els.demoDataAudit.innerHTML = items.length
    ? items.slice(0, 5).map((item) => `
        <div class="row compact">
          <div class="row-title">
            <strong>${escapeHtml(item.label)}</strong>
            <span class="badge ${escapeHtml(item.status || "needs_review")}">${escapeHtml((item.status || "needs_review").replace("_", " "))}</span>
          </div>
          <div class="row-meta">
            <span>${numberFormat(item.demo_count || 0)} demo</span>
            <span>${numberFormat(item.production_count || 0)} production/imported</span>
            <span>${numberFormat(item.record_count || 0)} total</span>
          </div>
          <div class="row-note">${escapeHtml(item.recommendation || "")}</div>
        </div>
      `).join("")
    : `<div class="empty">No business data audit records available.</div>`;
}

function opportunityButton(item) {
  return `
    <button class="opp" type="button" data-id="${escapeHtml(item.opportunity_id || item.notice_id)}">
      <strong>${escapeHtml(item.title)}</strong>
      <span class="opp-meta">
        <span>${escapeHtml(item.funding_agency_name || "Agency pending")}</span>
        <span>${escapeHtml(item.naics_code || "--")}/${escapeHtml(item.psc_code || "--")}</span>
        <span>${currencyRange(item.estimated_value_min, item.estimated_value_max)}</span>
      </span>
      <span class="opp-meta">
        <span>Due ${formatDate(item.response_deadline)}</span>
        <span>${percent(item.dashboard_relevance_score)} relevance</span>
      </span>
    </button>
  `;
}

function renderAnalysis(data) {
  const baseline = data.competitive_baseline || {};
  const opportunity = data.opportunity || {};
  const customer = data.customer_profile || {};
  const customerScore = data.customer_score || {};
  const market = data.market_baseline || {};

  els.analysisTitle.textContent = opportunity.title || "Capture analysis";
  els.analysisSubhead.textContent = [
    opportunity.funding_agency_name,
    `${opportunity.naics_code || "--"}/${opportunity.psc_code || "--"}`,
    evidenceCoverage(data.evidence),
  ]
    .filter(Boolean)
    .join(" · ");
  els.pwin.textContent = percent(baseline.estimated_p_win);
  els.marketPwin.textContent = percent(market.estimated_p_win);
  els.pwinDelta.textContent = signedPercent(customerScore.delta_vs_market);
  els.profileFit.textContent = percent(customerScore.profile_fit_score);
  els.confidence.textContent = baseline.confidence || "--";
  els.matchCount.textContent = baseline.historical_match_count ?? "--";
  els.matchedObligation.textContent = money(baseline.total_matched_obligation);
  renderRecommendedAction(data.recommended_action || {});
  renderMiniList(els.captureTasks, data.capture_tasks || [], (item) => `${item.task} · ${item.owner || "Owner pending"}`);
  renderMiniList(els.opportunityDeliverables, data.deliverables || [], (item) => `${item.name} · ${item.status}`);

  els.customerName.textContent = customer.company_name || "--";
  els.customerVehicles.textContent = shortList(customer.contract_vehicles);
  els.customerClearance.textContent = shortList([...(customer.clearance_levels || []), ...(customer.set_aside_eligibilities || [])]);

  renderSecurity(data.security_context || {});
  renderFitFactors(customerScore.factors || []);
  renderWorkflow(data.workflow || {});
  renderFreshness(data.data_freshness || []);
  renderPastPerformance(data.past_performance || []);
  renderBilling(data.billing || {});
  renderCompliance(data.compliance_controls || []);
  renderPrimes(data.competing_primes || []);
  renderSubs(data.target_teaming_subs || []);
  renderRates(data.calc_plus_benchmarks || []);
  renderEvidence(data.evidence || {});
  renderNotes(data.notes || []);
}

function renderRecommendedAction(action) {
  els.recommendedAction.textContent = action.action ? titleCase(action.action) : "--";
  els.recommendedRationale.textContent = action.rationale || "Bid/no-bid guidance pending.";
  els.recommendedAction.className = "";
  if (action.action) {
    els.recommendedAction.classList.add(`action-${action.action}`);
  }
}

function renderMiniList(element, items, template) {
  element.innerHTML = items.length
    ? items.slice(0, 4).map((item) => `<span>${escapeHtml(template(item))}</span>`).join("")
    : `<span>Pending</span>`;
}

function renderSecurity(context) {
  const parts = [context.tenant_name, context.role, context.auth_mode].filter(Boolean);
  els.securityStatus.textContent = parts.length ? parts.join(" · ") : "Tenant context pending";
}

function renderFitFactors(items) {
  els.fitFactors.innerHTML = items.length
    ? items.map((factor) => `
        <div class="row factor">
          <div class="row-title">
            <strong>${escapeHtml(factor.label)}</strong>
            <span class="score">${percent(factor.score)}</span>
          </div>
          <meter min="0" max="100" value="${clampPercent(factor.score)}">${percent(factor.score)}</meter>
          <div class="row-meta">${escapeHtml(factor.evidence || "")}</div>
        </div>
      `).join("")
    : `<div class="empty">No customer profile factors available.</div>`;
}

function renderWorkflow(workflow) {
  els.workflow.innerHTML = `
    <div class="row">
      <div class="row-title">
        <strong>${escapeHtml(titleCase(workflow.status || "untracked"))}</strong>
        <span class="score">${escapeHtml((workflow.go_no_go || "undecided").replace("_", "-"))}</span>
      </div>
      <div class="row-meta">
        <span>${escapeHtml(workflow.stage || "Qualification")}</span>
        <span>${escapeHtml(workflow.priority || "medium")} priority</span>
        <span>${escapeHtml(workflow.owner_name || "Unassigned")}</span>
      </div>
      <div class="row-note">${escapeHtml(workflow.decision_rationale || workflow.notes || "")}</div>
    </div>
  `;
}

function renderFreshness(rows) {
  els.freshness.innerHTML = rows.length
    ? rows.slice(0, 5).map((row) => `
        <div class="row compact">
          <div class="row-title">
            <strong>${escapeHtml(row.source_system)}</strong>
            <span class="badge ${escapeHtml(row.freshness_state || "unknown")}">${escapeHtml(row.freshness_state || row.sync_status || "unknown")}</span>
          </div>
          <div class="row-meta">
            <span>${escapeHtml(row.dataset_name)}</span>
            <span>${escapeHtml(row.source_mode)}</span>
            <span>${Number(row.record_count || 0).toLocaleString()} rows</span>
          </div>
        </div>
      `).join("")
    : `<div class="empty">No source freshness records available.</div>`;
}

function renderPastPerformance(rows) {
  els.pastPerformance.innerHTML = rows.length
    ? rows.slice(0, 4).map((row) => `
        <div class="row compact">
          <div class="row-title">
            <strong>${escapeHtml(row.title)}</strong>
            <span class="badge">${escapeHtml(row.role || "history")}</span>
          </div>
          <div class="row-meta">
            <span>${escapeHtml(row.agency_name || "--")}</span>
            <span>${escapeHtml(row.naics_code || "--")}/${escapeHtml(row.psc_code || "--")}</span>
            <span>${money(row.obligated_amount)}</span>
          </div>
        </div>
      `).join("")
    : `<div class="empty">No customer past performance imported.</div>`;
}

function renderBilling(billing) {
  els.billing.innerHTML = `
    <div class="row compact">
      <div class="row-title">
        <strong>${escapeHtml(titleCase(billing.subscription_status || "not configured"))}</strong>
        <span class="badge">${escapeHtml(billing.billing_provider || "billing")}</span>
      </div>
      <div class="row-meta">
        <span>${escapeHtml(billing.price_id || "Price pending")}</span>
        <span>Period end ${formatDate(billing.current_period_ends_at)}</span>
      </div>
    </div>
  `;
}

function renderCompliance(rows) {
  els.compliance.innerHTML = rows.length
    ? rows.slice(0, 4).map((row) => `
        <div class="row compact">
          <div class="row-title">
            <strong>${escapeHtml(row.control_name)}</strong>
            <span class="badge ${escapeHtml(row.implementation_status)}">${escapeHtml(row.implementation_status)}</span>
          </div>
          <div class="row-meta">
            <span>${escapeHtml(row.control_family)}</span>
            <span>${escapeHtml(row.control_key)}</span>
          </div>
        </div>
      `).join("")
    : `<div class="empty">No compliance controls recorded.</div>`;
}

function renderPrimes(items) {
  els.primes.innerHTML = renderRows(items, (prime) => `
    <div class="row-title">
      <strong>${escapeHtml(prime.legal_name)}</strong>
      <span class="score">${percent(prime.avg_match_score)}</span>
    </div>
    <div class="row-meta">
      <span>${prime.similar_wins || 0} similar wins</span>
      <span>${money(prime.matched_obligation)}</span>
      <span>${escapeHtml(prime.canonical_uei || "UEI pending")}</span>
    </div>
    ${renderAwardChips(prime.representative_awards || [])}
  `);
}

function renderSubs(items) {
  els.subs.innerHTML = renderRows(items, (sub) => `
    <div class="row-title">
      <strong>${escapeHtml(sub.legal_name)}</strong>
      <span class="score">${sub.total_engagements || 0}x</span>
    </div>
    <div class="row-meta">
      <span>${sub.associated_prime_count || 0} prime links</span>
      <span>${money(sub.total_subaward_value)}</span>
      <span>${escapeHtml(sub.canonical_uei || "UEI pending")}</span>
    </div>
  `);
}

function renderAwardChips(awards) {
  return awards.length
    ? `<div class="chips">${awards.slice(0, 2).map((award) => `<span>${escapeHtml(award.piid || award.award_number)} · ${money(award.award_value)}</span>`).join("")}</div>`
    : "";
}

function renderRows(items, template) {
  return items.length
    ? items.slice(0, 5).map((item) => `<div class="row">${template(item)}</div>`).join("")
    : `<div class="empty">No historical match data available.</div>`;
}

function renderSimpleRows(element, items, template) {
  element.innerHTML = items.length
    ? items.slice(0, 6).map((item) => `<div class="row compact">${template(item)}</div>`).join("")
    : `<div class="empty">No records available.</div>`;
}

function renderRates(rows) {
  els.rates.innerHTML = rows.length
    ? `<table>
        <thead>
          <tr>
            <th>Labor category</th>
            <th>Education</th>
            <th>Years</th>
            <th>Site</th>
            <th>Ceiling</th>
            <th>75th percentile</th>
            <th>Match</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((rate) => `
            <tr>
              <td>${escapeHtml(rate.labor_category)}</td>
              <td>${escapeHtml(rate.education_level || "--")}</td>
              <td>${rate.min_years_experience ?? "--"}</td>
              <td>${escapeHtml(rate.site || "--")}</td>
              <td>${money(rate.ceiling_hourly_rate)}/hr</td>
              <td>${money(rate.percentile_75_hourly_rate)}/hr</td>
              <td>${percent(rate.benchmark_match_score)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`
    : `<div class="empty">No CALC+ labor benchmarks found.</div>`;
}

function renderEvidence(evidence) {
  const items = evidence.items || [];
  els.evidence.innerHTML = items.length
    ? items.slice(0, 14).map((item) => `
        <article class="evidence-card">
          <div class="row-title">
            <strong>${escapeHtml(item.source_title)}</strong>
            <span class="badge">${escapeHtml(item.evidence_type)}</span>
          </div>
          <div class="row-meta">
            <span>${escapeHtml(item.source_system)}</span>
            <span>${escapeHtml(item.source_record_id || "record")}</span>
            <span>${formatDate(item.source_record_date)}</span>
            <span>${money(item.source_amount)}</span>
            <span>${escapeHtml(item.naics_code || "--")}/${escapeHtml(item.psc_code || "--")}</span>
          </div>
          <p>${escapeHtml(item.explanation || "")}</p>
          ${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
        </article>
      `).join("")
    : `<div class="empty">No source-backed evidence records available.</div>`;
}

function renderNotes(notes) {
  els.notes.innerHTML = notes.length
    ? notes.map((note) => `
        <div class="row">
          <div class="row-title">
            <strong>${escapeHtml(note.author_name || "Capture team")}</strong>
            <span class="badge">${escapeHtml(note.note_type || "note")}</span>
          </div>
          <div class="row-note">${escapeHtml(note.body)}</div>
          <div class="row-meta">${formatDate(note.created_at)}</div>
        </div>
      `).join("")
    : `<div class="empty">No capture notes recorded.</div>`;
}

function setActiveOpportunity(opportunityId) {
  els.opportunities.querySelectorAll(".opp").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === opportunityId);
  });
}

function setApiStatus(text) {
  els.apiStatus.textContent = text;
  els.apiStatus.classList.toggle("live", text === "Live API");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { ...options, headers: requestHeaders({ accept: "application/json", ...(options.headers || {}) }) });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function requestHeaders(headers = {}) {
  const team = selectedTeam();
  return {
    "x-captureos-tenant": selectedTenantSlug,
    "x-captureos-user": team.user_email || "capture.lead@example.com",
    ...headers,
  };
}

function selectedTeam() {
  return customerTeams.find((team) => team.tenant_slug === selectedTenantSlug) || customerTeams[0] || fallbackTeams[0];
}

function normalizeTeam(team) {
  const fallback = fallbackTeams.find((item) => item.tenant_slug === team.tenant_slug) || {};
  return {
    ...fallback,
    ...team,
    company_name: team.company_name || team.tenant_name || fallback.company_name,
    tenant_name: team.tenant_name || team.company_name || fallback.tenant_name,
  };
}

function buildFallbackAnalysis(opportunity = null) {
  const team = selectedTeam();
  const isMetalShop = team.tenant_slug === "metal-fabrication-shop";
  const factors = isMetalShop
    ? [
        { label: "NAICS fit", score: 0.72, evidence: `Profile targets ${shortList(team.target_naics_codes)}` },
        { label: "PSC fit", score: 0.68, evidence: `Profile targets ${shortList(team.target_psc_codes)}` },
        { label: "Agency relationship", score: 0.64, evidence: "DLA, Navy, Army, and Air Force fabrication history" },
        { label: "Deal size fit", score: 0.84, evidence: "Profile max single award $8M" },
      ]
    : fallbackAnalysis.customer_score.factors;
  return {
    ...fallbackAnalysis,
    opportunity: opportunity || fallbackAnalysis.opportunity,
    customer_profile: {
      ...fallbackAnalysis.customer_profile,
      ...team,
    },
    customer_score: {
      ...fallbackAnalysis.customer_score,
      company_adjusted_p_win: isMetalShop ? 0.22 : fallbackAnalysis.customer_score.company_adjusted_p_win,
      delta_vs_market: isMetalShop ? 0.06 : fallbackAnalysis.customer_score.delta_vs_market,
      profile_fit_score: isMetalShop ? 0.72 : fallbackAnalysis.customer_score.profile_fit_score,
      factors,
    },
    competitive_baseline: {
      ...fallbackAnalysis.competitive_baseline,
      estimated_p_win: isMetalShop ? 0.22 : fallbackAnalysis.competitive_baseline.estimated_p_win,
    },
    recommended_action: {
      action: isMetalShop ? "team" : "watch",
      priority: "medium",
      rationale: isMetalShop ? "Manufacturing fit is credible; validate drawings, quantities, and prime/sub path." : "Some fit exists; monitor source details and client capacity before proposal effort.",
      p_win: isMetalShop ? 0.22 : 0.18,
      profile_fit: isMetalShop ? 0.72 : 0.45,
      risks: [],
    },
    capture_tasks: [
      { task: "Confirm solicitation requirements and amendments", owner: "Consultant", status: "open" },
      { task: "Validate client eligibility, capacity, and past performance fit", owner: "Consultant", status: "open" },
      { task: isMetalShop ? "Identify likely prime or direct award path" : "Monitor source updates and deadline movement", owner: "Capture lead", status: "open" },
    ],
    deliverables: [
      { name: "Capture brief", status: "available" },
      { name: "Bid/no-bid memo", status: "ready_to_generate" },
      { name: "Compliance checklist", status: "draft" },
    ],
    past_performance: isMetalShop
      ? [
          { contract_number: "KEY-NAVSEA-23-014", title: "Shipboard Stainless Guard Assemblies", role: "prime", agency_name: "Department of the Navy", obligated_amount: 1260000 },
          { contract_number: "KEY-DLA-24-001", title: "CNC Machined Aluminum Bracket Kits", role: "prime", agency_name: "Defense Logistics Agency", obligated_amount: 740000 },
        ]
      : fallbackAnalysis.past_performance,
    security_context: {
      tenant_name: team.tenant_name || team.company_name,
      role: "capture_manager",
      auth_mode: "demo_header_context",
    },
  };
}

function buildFallbackWorkspace() {
  const metalPastPerformance = [
    { contract_number: "KEY-NAVSEA-23-014", title: "Shipboard Stainless Guard Assemblies", role: "prime", agency_name: "Department of the Navy", obligated_amount: 1260000 },
    { contract_number: "KEY-DLA-24-001", title: "CNC Machined Aluminum Bracket Kits", role: "prime", agency_name: "Defense Logistics Agency", obligated_amount: 740000 },
  ];
  const clients = customerTeams.map((team) => {
    const isMetalShop = team.tenant_slug === "metal-fabrication-shop";
    const readiness = {
      score: isMetalShop ? 0.66 : 0.74,
      label: isMetalShop ? "Subcontracting first" : "Prime-ready",
      stage: isMetalShop ? "subcontracting_first" : "prime_ready",
      gaps: isMetalShop
        ? [
            { label: "SAM identity", evidence: "UEI/CAGE is not linked in local fallback mode." },
            { label: "Pricing posture", evidence: "Fabrication rate cards need import." },
          ]
        : [{ label: "Risk rules", evidence: "Bid/no-bid preferences should be tightened." }],
      next_steps: isMetalShop
        ? ["Close readiness gap: SAM identity", "Package fabrication past performance", "Build teaming target list"]
        : ["Shortlist high-fit opportunities weekly", "Prepare bid/no-bid memos for top pursuits"],
    };
    return {
      tenant_slug: team.tenant_slug,
      tenant_name: team.tenant_name,
      company_name: team.company_name,
      profile: team,
      readiness,
      pipeline: { by_status: [{ status: "tracking", count: isMetalShop ? 2 : 4 }], high_priority: isMetalShop ? 1 : 2 },
      billing: { subscription_status: "trialing" },
      past_performance: isMetalShop ? metalPastPerformance : fallbackAnalysis.past_performance,
      recommended_opportunities: fallbackOpportunities.map((opp) => ({
        ...opp,
        dashboard_relevance_score: isMetalShop ? 0.68 : opp.dashboard_relevance_score,
        recommended_action: {
          action: isMetalShop ? "team" : "watch",
          rationale: isMetalShop ? "Fabrication codes and PSCs indicate a possible subcontracting path." : "Monitor until enriched source details improve fit confidence.",
        },
      })),
      recompete_signals: [
        {
          title: isMetalShop ? "Aircraft Fairing Fabrication Support" : "Zero Trust Platform Engineering",
          incumbent_name: isMetalShop ? "Regional Aerospace Prime" : "General Dynamics Information Technology, Inc.",
          funding_agency_name: isMetalShop ? "Department of the Navy" : "Department of the Air Force",
          period_of_performance_end: "2026-11-30",
          award_value: isMetalShop ? 2400000 : 118000000,
          signal_type: "watch_recompete",
        },
      ],
      reminders: [
        { title: "Send monthly pursuit report", due_at: "2026-06-01T17:00:00Z", reminder_type: "client_follow_up" },
      ],
      client_portal: {
        client_name: team.company_name,
        status: readiness.label,
        visible_widgets: ["readiness", "recommended_opportunities", "document_requests", "weekly_pipeline"],
        open_requests: readiness.next_steps,
      },
    };
  });
  const active = clients.find((client) => client.tenant_slug === selectedTenantSlug) || clients[0];
  return {
    positioning: {
      headline: "GovCon consulting delivery platform for small-business advisors",
      promise: "Add a client, get readiness, get top pursuits, export a client report.",
    },
    portfolio: {
      client_count: clients.length,
      prime_ready_clients: clients.filter((client) => client.readiness.stage === "prime_ready").length,
      tracked_pipeline_items: clients.reduce((sum, client) => sum + client.pipeline.by_status.reduce((count, item) => count + item.count, 0), 0),
      average_readiness_score: clients.reduce((sum, client) => sum + client.readiness.score, 0) / Math.max(1, clients.length),
    },
    active_client: active,
    clients,
    demo_flow: [
      { step: "Add client", status: "complete", description: "Run the intake wizard for a small business." },
      { step: "Get readiness", status: "complete", description: "Show readiness score, evidence, and gaps." },
      { step: "Get top pursuits", status: "complete", description: "Prioritize pursue/team/watch/skip opportunities." },
      { step: "Export client report", status: "available", description: "Create a branded report for the client." },
    ],
    white_label: {
      organization_name: "GovCon Advisory Practice",
      primary_color: "#0f766e",
      support_email: selectedTeam().user_email,
    },
    deliverables: [
      { name: "Client readiness report", status: "available", description: "Readiness score, gaps, and next actions." },
      { name: "Weekly pursuit shortlist", status: "available", description: "Top recommended opportunities with action guidance." },
      { name: "Bid/no-bid memo", status: "available per opportunity", description: "Opportunity fit, risks, and source-backed decision." },
      { name: "Client portal view", status: "available", description: "Client-facing requests, pipeline, and readiness status." },
    ],
    trust_posture: {
      auth_mode: "demo_header_context",
      billing_status: "implementation_ready",
      live_source_count: 4,
      mock_source_count: 1,
      disclaimer: "Decision support only. GovCon CaptureOS does not provide legal advice, procurement advice, bid/no-bid directives, or a guarantee of award.",
    },
    legal_disclaimer: {
      title: "Procurement Decision Support Notice",
      summary: "Decision support only. Consultants remain responsible for validating source records, client eligibility, pricing assumptions, conflicts, and proposal compliance.",
      limits: [
        "Validate every source link and solicitation requirement before advising a client.",
        "Treat P-win, readiness, pricing, incumbent, and teaming signals as advisory analysis.",
      ],
    },
    ingest_alerts: {
      status: "ok",
      summary: "All live ingests are fresh and within SLA.",
      live_alert_count: 0,
      demo_source_count: 1,
      items: [],
    },
    business_data_audit: {
      status: "needs_review",
      summary: "Seeded/demo business records remain and are labeled for advisor review before paid onboarding.",
      items: [
        { label: "Client profiles", status: "needs_review", record_count: clients.length, demo_count: clients.length, production_count: 0, recommendation: "Confirm profiles with each client before paid onboarding." },
        { label: "Past performance", status: "needs_review", record_count: 2, demo_count: 2, production_count: 0, recommendation: "Replace seeded past performance with signed client imports." },
        { label: "Workflow examples", status: "needs_review", record_count: 2, demo_count: 2, production_count: 0, recommendation: "Recreate real pipeline decisions during onboarding." },
      ],
    },
  };
}

function addFallbackClient(payload) {
  const tenantSlug = slugify(payload.company_name);
  const client = {
    tenant_slug: tenantSlug,
    tenant_name: payload.company_name,
    company_name: payload.company_name,
    user_email: payload.primary_contact_email,
    target_naics_codes: payload.target_naics_codes,
    target_psc_codes: payload.target_psc_codes,
    contract_vehicles: payload.contract_vehicles,
    set_aside_eligibilities: payload.set_aside_eligibilities,
    clearance_levels: [],
  };
  customerTeams = [client, ...customerTeams.filter((team) => team.tenant_slug !== tenantSlug)];
  return client;
}

function slugify(value) {
  const slug = String(value).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 58);
  return slug.length >= 3 ? slug : `${slug || "client"}-client`;
}

function splitCodes(value) {
  return value.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean);
}

function valueOf(selector) {
  return document.querySelector(selector).value.trim();
}

function currencyRange(min, max) {
  if (min && max) return `${money(min)} - ${money(max)}`;
  return money(max || min);
}

function numberFormat(value) {
  return new Intl.NumberFormat("en-US").format(Number(value || 0));
}

function money(value) {
  if (value == null || value === "") return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: Math.abs(Number(value)) >= 1000000 ? "compact" : "standard",
    maximumFractionDigits: Math.abs(Number(value)) >= 1000000 ? 1 : 0,
  }).format(Number(value));
}

function percent(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return `${Math.round(Number(value) * 100)}%`;
}

function signedPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  const sign = Number(value) > 0 ? "+" : "";
  return `${sign}${Math.round(Number(value) * 100)} pts`;
}

function clampPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return 0;
  return Math.max(0, Math.min(100, Math.round(Number(value) * 100)));
}

function formatDate(value) {
  if (!value) return "--";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function shortList(values) {
  const list = (values || []).filter(Boolean);
  return list.length ? list.slice(0, 3).join(", ") : "--";
}

function evidenceCoverage(evidence) {
  const coverage = evidence?.coverage || {};
  const total = Object.values(coverage).reduce((sum, count) => sum + Number(count || 0), 0);
  return total ? `${total} source records` : "source records pending";
}

function titleCase(value) {
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function renderLocalBrief(data) {
  const opportunity = data.opportunity || {};
  const baseline = data.competitive_baseline || {};
  return [
    `# Capture Brief: ${opportunity.title || "Opportunity"}`,
    "",
    `- Notice: ${opportunity.notice_id || "--"}`,
    `- Agency: ${opportunity.funding_agency_name || "--"}`,
    `- P-win: ${baseline.estimated_p_win || "--"}`,
    "",
    "## Competing primes",
    ...(data.competing_primes || []).slice(0, 3).map((prime) => `- ${prime.legal_name}`),
    "",
  ].join("\n");
}

function renderLocalClientReport(workspace) {
  const client = workspace.active_client || {};
  const readiness = client.readiness || {};
  const profile = client.profile || {};
  const disclaimer = workspace.legal_disclaimer || {};
  const audit = workspace.business_data_audit || {};
  const lines = [
    `# GovCon Client Report: ${client.company_name || client.tenant_name || "Client"}`,
    "",
    "## Decision Support Notice",
    disclaimer.summary || "Decision support only. Validate source records, eligibility, pricing, and proposal compliance before advising a client.",
    "",
    "## Readiness",
    `- Score: ${percent(readiness.score)}`,
    `- Status: ${readiness.label || "--"}`,
    `- Target NAICS: ${shortList(profile.target_naics_codes)}`,
    `- Target PSC: ${shortList(profile.target_psc_codes)}`,
    "",
    "## Gaps",
    ...(readiness.gaps || []).map((gap) => `- ${gap.label}: ${gap.evidence}`),
    "",
    "## Recommended opportunities",
    ...(client.recommended_opportunities || []).slice(0, 5).map((opp) => `- ${opp.title}: ${(opp.recommended_action || {}).action || "watch"}${opp.ui_link ? ` - ${opp.ui_link}` : ""}`),
    "",
    "## Source Drilldowns",
    ...(workspace.data_freshness || fallbackAnalysis.data_freshness || []).map((row) => `- ${row.source_system} / ${row.dataset_name}: ${row.source_mode} / ${row.freshness_state || row.sync_status} / ${row.record_count || 0} rows${row.source_url ? ` - ${row.source_url}` : ""}`),
    "",
    "## Demo Data Audit",
    ...((audit.items || []).map((item) => `- ${item.label}: ${item.status} (${item.demo_count || 0} demo of ${item.record_count || 0} records). ${item.recommendation || ""}`)),
    "",
  ];
  return lines.join("\n");
}

function downloadText(text, filename) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
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
