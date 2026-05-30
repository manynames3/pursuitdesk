import { generateAiSearchReadiness, generateEntitySignals } from "./generateEntitySignals.js";
import { generateRoadmap } from "./generateRoadmap.js";
import { generateTopicGaps } from "./generateTopicGaps.js";
import { LOCAL_SEO_ANALYSIS_MODE } from "./types.js";
import {
  averageScores,
  clampScore,
  keywordTokens,
  normalizePhrase,
  parseUrl,
  scoreBand,
  scoreCompleteness,
  scoreDeltaLabel,
  scoreSummary,
  scoreUrlContext,
  titleCase,
} from "./scoring.js";

export function analyzeLocalSeo(rawInput) {
  const input = normalizeInput(rawInput);
  const competitorCount = input.competitors.length;
  const completeness = scoreCompleteness(input);
  const userUrlContext = scoreUrlContext(input.websiteUrl, input.mainKeyword, input.targetCity);
  const noteSignals = noteSignalScore(input.notes);
  const competitorPressure = competitorCount ? 7 + competitorCount * 2 : 0;
  const keywordDepth = Math.min(18, keywordTokens(input.mainKeyword).length * 6);

  // TODO: Replace deterministic placeholder scoring with adapters for Google
  // Search Console, Google Business Profile, SERP APIs, PageSpeed Insights,
  // Firecrawl/Crawl4AI, Ahrefs/Semrush/DataForSEO, Places, reviews, citations,
  // and a schema parser. The report contract below is intentionally stable.
  const scores = [
    seoScore("topicalAuthority", "Topical Authority Score", 34 + completeness * 0.18 + userUrlContext * 0.23 + keywordDepth + noteSignals.content - competitorPressure),
    seoScore("localRelevance", "Local Relevance Score", 36 + completeness * 0.2 + userUrlContext * 0.2 + (input.targetCity ? 10 : 0) + (input.targetState ? 6 : 0) + (input.mapsUrl ? 6 : 0) - competitorPressure * 0.45),
    seoScore("serviceCoverage", "Service Coverage Score", 32 + completeness * 0.14 + keywordDepth + noteSignals.service + userUrlContext * 0.18 - competitorPressure),
    seoScore("trustSignals", "Trust Signal Score", 35 + completeness * 0.12 + noteSignals.trust + (input.businessName ? 8 : 0) + (input.mapsUrl ? 8 : 0) - competitorPressure * 0.65),
    seoScore("internalLinking", "Internal Linking Score", 34 + userUrlContext * 0.18 + noteSignals.linking + (input.websiteUrl ? 7 : 0) - competitorPressure),
    seoScore("gbpReadiness", "GBP / Maps Readiness Score", 30 + (input.mapsUrl ? 28 : 0) + (input.businessName ? 10 : 0) + (input.targetCity ? 8 : 0) + (input.targetState ? 6 : 0) + noteSignals.trust * 0.2 - competitorPressure * 0.45),
    seoScore("aiSearchReadiness", "AI Search Readiness Score", 36 + completeness * 0.16 + noteSignals.ai + keywordDepth * 0.55 + userUrlContext * 0.12 - competitorPressure * 0.8),
  ];

  const totalReadiness = averageScores(scores.map((score) => score.value));
  scores.push(seoScore("totalOpportunity", "Total Local SEO Opportunity Score", totalReadiness));

  const competitorAnalyses = buildCompetitorAnalyses(input, scores);
  const topicGaps = generateTopicGaps(input, scores);
  const entitySignals = generateEntitySignals(input);
  const aiSearchReadiness = generateAiSearchReadiness(input);
  const internalLinks = generateInternalLinks(input);
  const roadmap = generateRoadmap(input, scores, topicGaps);

  return {
    id: `local-seo-${Date.now()}`,
    createdAt: new Date().toISOString(),
    mode: LOCAL_SEO_ANALYSIS_MODE,
    input,
    scores,
    competitors: competitorAnalyses,
    topicGaps,
    entitySignals,
    internalLinks,
    aiSearchReadiness,
    roadmap,
    summary: buildSummary(input, scores, competitorAnalyses, topicGaps),
    assumptions: [
      "Scores are deterministic estimates based on entered fields and URL/context signals.",
      "No paid APIs, search scraping, GBP scraping, or live site crawling are called in this version.",
      "Competitor rows are a benchmark model only when competitor URLs are provided.",
    ],
    todos: [
      "Connect Google Search Console API.",
      "Connect Google Business Profile API.",
      "Connect SERP API and Places API.",
      "Connect PageSpeed Insights API.",
      "Connect Firecrawl, Crawl4AI, or an internal site crawler.",
      "Connect Ahrefs, Semrush, or DataForSEO for backlink and keyword evidence.",
      "Connect review and citation data sources.",
    ],
  };
}

export function normalizeInput(rawInput) {
  const competitors = [0, 1, 2].map((index) => ({
    websiteUrl: normalizeUrl(rawInput?.competitors?.[index]?.websiteUrl || rawInput?.[`competitor${index + 1}Url`] || ""),
    mapsUrl: normalizeUrl(rawInput?.competitors?.[index]?.mapsUrl || rawInput?.[`competitor${index + 1}MapsUrl`] || ""),
  })).filter((item) => item.websiteUrl || item.mapsUrl);

  return {
    websiteUrl: normalizeUrl(rawInput?.websiteUrl || ""),
    businessName: cleanText(rawInput?.businessName || ""),
    targetCity: cleanText(rawInput?.targetCity || ""),
    targetState: cleanText(rawInput?.targetState || "").toUpperCase(),
    mainKeyword: cleanText(rawInput?.mainKeyword || ""),
    mapsUrl: normalizeUrl(rawInput?.mapsUrl || ""),
    notes: cleanText(rawInput?.notes || ""),
    competitors,
  };
}

export function localSeoReportToMarkdown(report) {
  const input = report.input;
  const lines = [
    `# Local SEO Authority Gap Report: ${input.businessName || "Business"}`,
    "",
    `Mode: ${report.mode}`,
    `Website: ${input.websiteUrl || "Not provided"}`,
    `Market: ${[input.targetCity, input.targetState].filter(Boolean).join(", ") || "Not provided"}`,
    `Main service: ${input.mainKeyword || "Not provided"}`,
    "",
    "## Summary",
    report.summary,
    "",
    "## Scorecards",
    ...report.scores.map((score) => `- ${score.label}: ${score.value}/100 (${score.band}) - ${score.summary}`),
    "",
    "## Competitor Comparison",
    ...report.competitors.map((item) => `- ${item.label}: ${item.overallStrength}/100 overall - ${item.note}`),
    "",
    "## Topic Gaps",
    ...report.topicGaps.map((gap) => `- ${gap.topic}: ${gap.why} Priority ${gap.priority}/100.`),
    "",
    "## Entity Signals",
    ...report.entitySignals.map((signal) => `- ${signal.label}: ${signal.status}. ${signal.recommendation}`),
    "",
    "## Internal Linking Plan",
    ...report.internalLinks.map((link) => `- ${link.from} -> ${link.to}: "${link.anchor}" - ${link.reason}`),
    "",
    "## AI Search Readiness",
    ...report.aiSearchReadiness.map((signal) => `- ${signal.label}: ${signal.status}. ${signal.recommendation}`),
    "",
    "## Priority Roadmap",
    ...roadmapMarkdown("Fix this week", report.roadmap.thisWeek),
    ...roadmapMarkdown("Build this month", report.roadmap.thisMonth),
    ...roadmapMarkdown("Build next quarter", report.roadmap.nextQuarter),
    "",
    "## Assumptions",
    ...report.assumptions.map((item) => `- ${item}`),
    "",
    "## Future API TODOs",
    ...report.todos.map((item) => `- ${item}`),
  ];
  return lines.join("\n");
}

export function localSeoReportToCsv(report) {
  const rows = [
    ["section", "item", "value", "status", "detail"],
    ...report.scores.map((score) => ["score", score.label, `${score.value}/100`, score.band, score.summary]),
    ...report.competitors.map((item) => ["competitor", item.label, `${item.overallStrength}/100`, scoreDeltaLabel(report.competitors[0]?.overallStrength || 0, item.overallStrength), item.website]),
    ...report.topicGaps.map((gap) => ["topic_gap", gap.topic, `${gap.priority}/100`, gap.type, gap.why]),
    ...report.entitySignals.map((signal) => ["entity_signal", signal.label, signal.status, signal.evidence, signal.recommendation]),
    ...report.internalLinks.map((link) => ["internal_link", `${link.from} -> ${link.to}`, link.anchor, "", link.reason]),
    ...report.roadmap.thisWeek.map((item) => ["roadmap_this_week", item.task, `${item.priority}/100`, item.impact, item.why]),
    ...report.roadmap.thisMonth.map((item) => ["roadmap_this_month", item.task, `${item.priority}/100`, item.impact, item.why]),
    ...report.roadmap.nextQuarter.map((item) => ["roadmap_next_quarter", item.task, `${item.priority}/100`, item.impact, item.why]),
  ];
  return rows.map((row) => row.map(csvCell).join(",")).join("\n");
}

function seoScore(key, label, value) {
  const scoreValue = clampScore(value);
  return {
    key,
    label,
    value: scoreValue,
    band: scoreBand(scoreValue),
    summary: scoreSummary(scoreValue),
  };
}

function buildCompetitorAnalyses(input, scores) {
  const scoreMap = Object.fromEntries(scores.map((score) => [score.key, score.value]));
  const user = {
    label: input.businessName || "Your website",
    website: input.websiteUrl || "Not provided",
    isUser: true,
    topicalCoverage: clampScore(scoreMap.topicalAuthority),
    servicePageDepth: clampScore(scoreMap.serviceCoverage),
    cityRelevance: clampScore(scoreMap.localRelevance),
    trustSignals: clampScore(scoreMap.trustSignals),
    internalLinking: clampScore(scoreMap.internalLinking),
    schemaReadiness: clampScore((scoreMap.gbpReadiness + scoreMap.aiSearchReadiness) / 2),
    contentFreshness: clampScore(42 + noteSignalScore(input.notes).content * 0.55),
    overallStrength: clampScore(scoreMap.totalOpportunity),
    note: "Your current estimated baseline from entered fields.",
  };

  const competitors = input.competitors.map((competitor, index) => {
    const label = `Competitor ${index + 1}`;
    const urlContext = scoreUrlContext(competitor.websiteUrl, input.mainKeyword, input.targetCity);
    const boost = 6 + index * 4 + (competitor.mapsUrl ? 4 : 0);
    const coverage = competitorMetric(user.topicalCoverage, urlContext, boost + 4);
    const serviceDepth = competitorMetric(user.servicePageDepth, urlContext, boost + 7);
    const localRelevance = competitorMetric(user.cityRelevance, urlContext, boost + 5);
    const trust = competitorMetric(user.trustSignals, urlContext, boost + (competitor.mapsUrl ? 8 : 3));
    const linking = competitorMetric(user.internalLinking, urlContext, boost + 6);
    const schema = competitorMetric(user.schemaReadiness, urlContext, boost + (competitor.mapsUrl ? 6 : 2));
    const freshness = competitorMetric(user.contentFreshness, urlContext, boost + 4);
    const overall = averageScores([coverage, serviceDepth, localRelevance, trust, linking, schema, freshness]);
    return {
      label,
      website: competitor.websiteUrl || competitor.mapsUrl || "Provided competitor",
      isUser: false,
      topicalCoverage: coverage,
      servicePageDepth: serviceDepth,
      cityRelevance: localRelevance,
      trustSignals: trust,
      internalLinking: linking,
      schemaReadiness: schema,
      contentFreshness: freshness,
      overallStrength: overall,
      note: scoreDeltaLabel(user.overallStrength, overall),
    };
  });

  return [user, ...competitors];
}

function competitorMetric(userValue, urlContext, boost) {
  const estimated = 44 + urlContext * 0.42 + boost;
  return clampScore(Math.max(userValue + boost, estimated));
}

function generateInternalLinks(input) {
  const keyword = titleCase(input.mainKeyword || "Primary Service");
  const city = titleCase(input.targetCity || "Target City");
  return [
    link("Homepage", `${keyword} page`, `${keyword} in ${city}`, "Send homepage authority to the main service page with clear service and city relevance."),
    link(`${keyword} page`, `${city} location page`, `${keyword} in ${city}`, "Connect service intent to the target market instead of leaving the city signal isolated."),
    link(`${city} location page`, "Supporting service pages", `${keyword} services near ${city}`, "Build a crawl path from city context into service-depth pages."),
    link("Blog and cost guides", "Money pages", `${keyword} estimate`, "Use informational pages to support conversion pages without trapping authority in the blog."),
    link("Project pages", `${keyword} and ${city} pages`, `${keyword} project in ${city}`, "Tie proof content back to the commercial service and local pages."),
    link("FAQ pages", "Main service pages", `${keyword} answers`, "Turn customer questions into internal support for the highest-value pages."),
  ];
}

function link(from, to, anchor, reason) {
  return { from, to, anchor, reason };
}

function buildSummary(input, scores, competitors, topicGaps) {
  const total = scores.find((score) => score.key === "totalOpportunity")?.value || 0;
  const strongestCompetitor = competitors.filter((item) => !item.isUser).sort((a, b) => b.overallStrength - a.overallStrength)[0];
  const market = [titleCase(input.targetCity), input.targetState].filter(Boolean).join(", ");
  const competitorSentence = strongestCompetitor
    ? `The strongest entered competitor benchmarks at ${strongestCompetitor.overallStrength}/100, which creates a practical authority gap around service depth, entity proof, and internal linking.`
    : "Add competitor URLs to benchmark likely authority gaps against specific local rivals.";
  return `Here is where competitors have stronger local authority, and here is the highest-leverage build plan to close the gap. The current estimated readiness for ${input.businessName || "the business"} in ${market || "the target market"} is ${total}/100. ${competitorSentence} The top content build is "${topicGaps[0]?.topic || "a dedicated local service page"}."`;
}

function noteSignalScore(notes) {
  const normalized = normalizePhrase(notes);
  return {
    content: phraseCount(normalized, ["blog", "guide", "faq", "content", "page", "project"]) * 5,
    service: phraseCount(normalized, ["service", "emergency", "commercial", "residential", "repair", "installation"]) * 4,
    trust: phraseCount(normalized, ["review", "testimonial", "license", "certified", "insured", "project", "case study"]) * 5,
    linking: phraseCount(normalized, ["link", "navigation", "breadcrumb", "hub", "silo"]) * 5,
    ai: phraseCount(normalized, ["schema", "faq", "author", "pricing", "process", "updated", "review"]) * 4,
  };
}

function phraseCount(text, phrases) {
  return phrases.reduce((sum, phrase) => sum + (text.includes(phrase) ? 1 : 0), 0);
}

function normalizeUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const parsed = parseUrl(text);
  return parsed ? parsed.href : text;
}

function cleanText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function roadmapMarkdown(title, tasks) {
  return [
    "",
    `### ${title}`,
    ...tasks.map((item) => `- ${item.task}: ${item.why} Impact: ${item.impact}. Difficulty: ${item.difficulty}. Priority: ${item.priority}/100.`),
  ];
}

function csvCell(value) {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}
