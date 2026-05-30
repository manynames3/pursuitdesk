import { clampScore, titleCase } from "./scoring.js";

export function generateRoadmap(input, scores, topicGaps) {
  const scoreMap = Object.fromEntries((scores || []).map((score) => [score.key, score.value]));
  const keyword = titleCase(input.mainKeyword || "Primary Service");
  const city = titleCase(input.targetCity || "Target City");
  const state = String(input.targetState || "").trim().toUpperCase();
  const localLabel = [city, state].filter(Boolean).join(", ");
  const topGap = topicGaps[0]?.topic || `${keyword} in ${localLabel}`;
  const serviceGap = 100 - Number(scoreMap.serviceCoverage || 50);
  const trustGap = 100 - Number(scoreMap.trustSignals || 50);
  const localGap = 100 - Number(scoreMap.localRelevance || 50);
  const linkingGap = 100 - Number(scoreMap.internalLinking || 50);

  return {
    thisWeek: [
      task(`Audit the ${keyword} page and homepage messaging`, `The site needs a clear people-first statement of who the business helps, where it works, and what ${keyword.toLowerCase()} outcomes it delivers.`, "High", "Low", 82 + serviceGap * 0.12),
      task(`Create a ${city} authority outline`, `Competitor visibility usually comes from matching service intent to local relevance, not from a single generic page.`, "High", "Low", 80 + localGap * 0.14),
      task("Map internal links to priority money pages", "Google and AI systems need a clear path from the homepage to service, city, FAQ, project, and proof pages.", "Medium", "Low", 74 + linkingGap * 0.18),
      task("Validate GBP, NAP, reviews, and core citations", "Local rankings depend on relevance, distance, and prominence, and entity consistency supports prominence signals.", "High", "Medium", 78 + trustGap * 0.14),
    ],
    thisMonth: [
      task(`Build dedicated "${topGap}" content`, "This closes the strongest exact-intent content gap surfaced by the placeholder benchmark.", "High", "Medium", topicGaps[0]?.priority || 90),
      task(`Publish ${keyword} FAQs for ${city}`, "FAQ coverage helps users make decisions and gives search systems clear answer-ready context.", "Medium", "Low", 82 + serviceGap * 0.1),
      task(`Publish ${keyword} cost guidance`, "Cost content is one of the clearest AI-search readiness gaps for service businesses.", "High", "Medium", 80 + serviceGap * 0.12),
      task("Add LocalBusiness and Breadcrumb schema", "Structured data helps Google understand the business entity, service area, and site hierarchy.", "Medium", "Medium", 79),
      task(`Add ${city} project examples and testimonials`, "Project proof connects trust signals, local relevance, and service depth in one asset type.", "High", "Medium", 81 + trustGap * 0.12),
    ],
    nextQuarter: [
      task(`Build a ${city} service-area content hub`, "A hub can organize city, neighborhood, service, FAQ, project, and cost content without creating thin doorway pages.", "High", "High", 84 + localGap * 0.1),
      task("Create a review and citation improvement program", "Prominence depends on real-world credibility signals, review velocity, and consistency across the local ecosystem.", "High", "Medium", 83 + trustGap * 0.1),
      task("Connect live crawl, GBP, SERP, and performance data", "The deterministic engine is ready for API adapters; live evidence will replace placeholder scoring.", "High", "High", 76),
      task("Refresh priority pages on a quarterly cadence", "Fresh project, FAQ, review, and cost content makes the site easier to trust and easier to parse.", "Medium", "Medium", 72),
    ],
  };
}

function task(taskName, why, impact, difficulty, priority) {
  return {
    task: taskName,
    why,
    impact,
    difficulty,
    priority: clampScore(priority),
  };
}
