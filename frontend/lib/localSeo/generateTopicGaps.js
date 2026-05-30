import { clampScore, normalizePhrase, titleCase } from "./scoring.js";

export function generateTopicGaps(input, scores) {
  const keyword = cleanKeyword(input.mainKeyword) || "primary service";
  const keywordTitle = titleCase(keyword);
  const city = titleCase(input.targetCity || "Target City");
  const state = String(input.targetState || "").trim().toUpperCase();
  const location = [city, state].filter(Boolean).join(", ");
  const scoreMap = Object.fromEntries((scores || []).map((score) => [score.key, score.value]));
  const serviceCoverage = Number(scoreMap.serviceCoverage || 45);
  const localRelevance = Number(scoreMap.localRelevance || 45);
  const trustSignals = Number(scoreMap.trustSignals || 45);

  const modifiers = [
    {
      topic: `${keywordTitle} in ${location}`,
      type: "Core local service page",
      why: `Build exact service plus city relevance for ${keywordTitle} searches in ${city}.`,
      suggestedPageType: "Money page",
      priority: priorityFrom(serviceCoverage, 94),
    },
    {
      topic: `Emergency ${keyword}`,
      type: "High-intent service depth",
      why: `Emergency intent often signals urgent local demand and can support stronger topical coverage.`,
      suggestedPageType: "Service-depth page",
      priority: priorityFrom(serviceCoverage, 91),
    },
    {
      topic: `${keywordTitle} cost guide for ${city}`,
      type: "Decision support content",
      why: `Cost guidance helps people compare options and gives AI/search systems clearer answer-ready context.`,
      suggestedPageType: "Cost guide",
      priority: priorityFrom(serviceCoverage, 88),
    },
    {
      topic: `${keywordTitle} process and timeline`,
      type: "Trust-building content",
      why: `A clear service process explains what happens before, during, and after the job.`,
      suggestedPageType: "Process page",
      priority: priorityFrom(trustSignals, 84),
    },
    {
      topic: `${keywordTitle} FAQs`,
      type: "Question coverage",
      why: `FAQ coverage supports helpful content, featured answers, and entity clarity.`,
      suggestedPageType: "FAQ page",
      priority: priorityFrom(serviceCoverage, 86),
    },
    {
      topic: `${city} neighborhood and service-area pages`,
      type: "Local relevance expansion",
      why: `Service-area pages can connect the business to nearby neighborhoods without doorway-page duplication.`,
      suggestedPageType: "Location hub",
      priority: priorityFrom(localRelevance, 83),
    },
    {
      topic: `Before and after ${keyword} projects in ${city}`,
      type: "Proof content",
      why: `Project examples turn claims into evidence and strengthen local prominence signals.`,
      suggestedPageType: "Project gallery",
      priority: priorityFrom(trustSignals, 82),
    },
    {
      topic: `${keywordTitle} reviews and testimonials`,
      type: "Prominence proof",
      why: `Review/testimonial content helps validate service quality and supports GBP alignment.`,
      suggestedPageType: "Proof page",
      priority: priorityFrom(trustSignals, 80),
    },
    {
      topic: `${keywordTitle} financing and payment options`,
      type: "Conversion support",
      why: `Financing or payment clarity can remove friction for high-cost local services.`,
      suggestedPageType: "Support page",
      priority: priorityFrom(serviceCoverage, 74),
    },
    {
      topic: `${keywordTitle} for commercial customers in ${city}`,
      type: "Audience-specific service depth",
      why: `Commercial intent may require different proof, service language, and internal links than residential intent.`,
      suggestedPageType: "Segment page",
      priority: priorityFrom(serviceCoverage, 78),
    },
  ];

  return dedupeTopics(modifiers, keyword, city).sort((a, b) => b.priority - a.priority);
}

function cleanKeyword(value) {
  const normalized = normalizePhrase(value);
  return normalized || "";
}

function priorityFrom(score, ceiling) {
  const gap = Math.max(0, 100 - Number(score || 0));
  return clampScore(Math.min(ceiling, 58 + gap * 0.45));
}

function dedupeTopics(items, keyword, city) {
  const seen = new Set();
  return items.filter((item) => {
    const key = normalizePhrase(`${item.topic} ${keyword} ${city}`);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
