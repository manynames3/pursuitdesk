const apiBaseUrl = window.CAPTUREOS_API_BASE_URL || "";
const fallbackOpportunities = [
  {
    opportunity_id: "SAM-2026-USAF-ZT-003",
    notice_id: "SAM-2026-USAF-ZT-003",
    title: "USAF Zero Trust Cloud Modernization",
    naics_code: "541512",
    psc_code: "DA01",
    funding_agency_name: "Department of the Air Force",
    estimated_value_min: 65000000,
    estimated_value_max: 140000000,
    response_deadline: "2026-08-05T15:30:00Z",
    dashboard_relevance_score: 0.89,
  },
  {
    opportunity_id: "SAM-2026-C5ISR-AI-001",
    notice_id: "SAM-2026-C5ISR-AI-001",
    title: "Army C5ISR AI Mission Data Fabric",
    naics_code: "541715",
    psc_code: "AC12",
    funding_agency_name: "Department of the Army",
    estimated_value_min: 45000000,
    estimated_value_max: 95000000,
    response_deadline: "2026-07-10T17:00:00Z",
    dashboard_relevance_score: 0.84,
  },
];

const fallbackAnalysis = {
  opportunity: fallbackOpportunities[0],
  competing_primes: [
    { rank: 1, legal_name: "General Dynamics Information Technology, Inc.", similar_wins: 8, avg_match_score: 0.86, matched_obligation: 118000000 },
    { rank: 2, legal_name: "Accenture Federal Services LLC", similar_wins: 6, avg_match_score: 0.81, matched_obligation: 97000000 },
    { rank: 3, legal_name: "CACI, Inc. - Federal", similar_wins: 4, avg_match_score: 0.76, matched_obligation: 68000000 },
  ],
  target_teaming_subs: [
    { legal_name: "Raft LLC", associated_prime_count: 2, total_engagements: 7, total_subaward_value: 18400000 },
    { legal_name: "RIVA Solutions, Inc.", associated_prime_count: 2, total_engagements: 6, total_subaward_value: 15100000 },
    { legal_name: "Octo Metric LLC", associated_prime_count: 1, total_engagements: 5, total_subaward_value: 12800000 },
    { legal_name: "BlueHalo, LLC", associated_prime_count: 1, total_engagements: 3, total_subaward_value: 9600000 },
  ],
  calc_plus_benchmarks: [
    { labor_category: "Cloud Architect", education_level: "Bachelor's", min_years_experience: 8, site: "CONUS", ceiling_hourly_rate: 221.4, percentile_75_hourly_rate: 192.13 },
    { labor_category: "Cyber Security Engineer", education_level: "Bachelor's", min_years_experience: 7, site: "CONUS", ceiling_hourly_rate: 212.49, percentile_75_hourly_rate: 183.17 },
    { labor_category: "DevSecOps Engineer", education_level: "Bachelor's", min_years_experience: 6, site: "CONUS", ceiling_hourly_rate: 188.4, percentile_75_hourly_rate: 163.2 },
    { labor_category: "Program Manager", education_level: "Bachelor's", min_years_experience: 10, site: "CONUS", ceiling_hourly_rate: 182.5, percentile_75_hourly_rate: 158.25 },
  ],
  competitive_baseline: {
    estimated_p_win: 0.41,
    confidence: "medium",
    historical_match_count: 42,
    total_matched_obligation: 363000000,
  },
};

const els = {
  apiStatus: document.querySelector("#api-status"),
  refresh: document.querySelector("#refresh"),
  opportunities: document.querySelector("#opportunities"),
  opportunityCount: document.querySelector("#opportunity-count"),
  analysisTitle: document.querySelector("#analysis-title"),
  pwin: document.querySelector("#pwin"),
  confidence: document.querySelector("#confidence"),
  matchCount: document.querySelector("#match-count"),
  matchedObligation: document.querySelector("#matched-obligation"),
  primes: document.querySelector("#primes"),
  subs: document.querySelector("#subs"),
  rates: document.querySelector("#rates"),
};

els.refresh.addEventListener("click", loadOpportunities);
loadOpportunities();

async function loadOpportunities() {
  const params = new URLSearchParams({
    min_value: valueOf("#min-value"),
    max_value: valueOf("#max-value"),
    limit: "25",
  });

  splitCodes(valueOf("#naics")).forEach((code) => params.append("naics_codes", code));
  splitCodes(valueOf("#psc")).forEach((code) => params.append("psc_codes", code));

  let data;
  try {
    data = await fetchJson(`${apiBaseUrl}/api/v1/opportunities/active?${params.toString()}`);
    els.apiStatus.textContent = "Live API";
  } catch (error) {
    data = { items: fallbackOpportunities };
    els.apiStatus.textContent = "Local demo data";
  }

  renderOpportunities(data.items || []);
  const first = (data.items || [])[0];
  if (first) {
    await loadAnalysis(first.opportunity_id || first.notice_id);
  }
}

async function loadAnalysis(opportunityId) {
  setActiveOpportunity(opportunityId);
  let data;
  try {
    data = await fetchJson(`${apiBaseUrl}/api/v1/capture-analysis/${encodeURIComponent(opportunityId)}`);
    els.apiStatus.textContent = "Live API";
  } catch (error) {
    data = {
      ...fallbackAnalysis,
      opportunity: fallbackOpportunities.find((item) => item.opportunity_id === opportunityId) || fallbackAnalysis.opportunity,
    };
    els.apiStatus.textContent = "Local demo data";
  }
  renderAnalysis(data);
}

function renderOpportunities(items) {
  els.opportunityCount.textContent = String(items.length);
  els.opportunities.innerHTML = items.length
    ? items
        .map(
          (item) => `
            <button class="opp" type="button" data-id="${escapeHtml(item.opportunity_id || item.notice_id)}">
              <strong>${escapeHtml(item.title)}</strong>
              <span class="opp-meta">
                <span>${escapeHtml(item.funding_agency_name || "Agency pending")}</span>
                <span>${escapeHtml(item.naics_code || "--")}/${escapeHtml(item.psc_code || "--")}</span>
                <span>${currencyRange(item.estimated_value_min, item.estimated_value_max)}</span>
              </span>
            </button>
          `,
        )
        .join("")
    : `<div class="empty">No active opportunities matched these filters.</div>`;

  els.opportunities.querySelectorAll(".opp").forEach((button) => {
    button.addEventListener("click", () => loadAnalysis(button.dataset.id));
  });
}

function renderAnalysis(data) {
  const baseline = data.competitive_baseline || {};
  const opportunity = data.opportunity || {};
  els.analysisTitle.textContent = opportunity.title || "Capture analysis";
  els.pwin.textContent = baseline.estimated_p_win == null ? "--" : `${Math.round(Number(baseline.estimated_p_win) * 100)}%`;
  els.confidence.textContent = baseline.confidence || "--";
  els.matchCount.textContent = baseline.historical_match_count ?? "--";
  els.matchedObligation.textContent = money(baseline.total_matched_obligation);

  els.primes.innerHTML = renderRows(data.competing_primes || [], (prime) => `
    <div class="row-title">
      <strong>${escapeHtml(prime.legal_name)}</strong>
      <span class="score">${percent(prime.avg_match_score)}</span>
    </div>
    <div class="row-meta">
      <span>${prime.similar_wins || 0} similar wins</span>
      <span>${money(prime.matched_obligation)}</span>
    </div>
  `);

  els.subs.innerHTML = renderRows(data.target_teaming_subs || [], (sub) => `
    <div class="row-title">
      <strong>${escapeHtml(sub.legal_name)}</strong>
      <span class="score">${sub.total_engagements || 0}x</span>
    </div>
    <div class="row-meta">
      <span>${sub.associated_prime_count || 0} prime links</span>
      <span>${money(sub.total_subaward_value)}</span>
    </div>
  `);

  renderRates(data.calc_plus_benchmarks || []);
}

function renderRows(items, template) {
  return items.length
    ? items.slice(0, 5).map((item) => `<div class="row">${template(item)}</div>`).join("")
    : `<div class="empty">No historical match data available.</div>`;
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
          </tr>
        </thead>
        <tbody>
          ${rows
            .map(
              (rate) => `
                <tr>
                  <td>${escapeHtml(rate.labor_category)}</td>
                  <td>${escapeHtml(rate.education_level || "--")}</td>
                  <td>${rate.min_years_experience ?? "--"}</td>
                  <td>${escapeHtml(rate.site || "--")}</td>
                  <td>${money(rate.ceiling_hourly_rate)}/hr</td>
                  <td>${money(rate.percentile_75_hourly_rate)}/hr</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>`
    : `<div class="empty">No CALC+ labor benchmarks found.</div>`;
}

function setActiveOpportunity(opportunityId) {
  els.opportunities.querySelectorAll(".opp").forEach((button) => {
    button.classList.toggle("active", button.dataset.id === opportunityId);
  });
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

function splitCodes(value) {
  return value
    .split(",")
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
}

function valueOf(selector) {
  return document.querySelector(selector).value.trim();
}

function currencyRange(min, max) {
  if (min && max) {
    return `${money(min)} - ${money(max)}`;
  }
  return money(max || min);
}

function money(value) {
  if (value == null || value === "") {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: Number(value) >= 1000000 ? "compact" : "standard",
    maximumFractionDigits: Number(value) >= 1000000 ? 1 : 0,
  }).format(Number(value));
}

function percent(value) {
  if (value == null) {
    return "--";
  }
  return `${Math.round(Number(value) * 100)}%`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    const escapes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return escapes[char];
  });
}
