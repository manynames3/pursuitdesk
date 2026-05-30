export function clampScore(value) {
  if (Number.isNaN(Number(value))) return 0;
  return Math.max(0, Math.min(100, Math.round(Number(value))));
}

export function scoreBand(value) {
  const score = clampScore(value);
  if (score >= 72) return "strong";
  if (score >= 48) return "moderate";
  return "weak";
}

export function titleCase(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\b[a-z]/g, (char) => char.toUpperCase());
}

export function normalizePhrase(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function keywordTokens(keyword) {
  const stopWords = new Set(["and", "or", "the", "a", "an", "of", "for", "in", "near", "services", "service"]);
  return normalizePhrase(keyword)
    .split(/\s+/)
    .map((token) => token.trim())
    .filter((token) => token.length > 2 && !stopWords.has(token));
}

export function scoreUrlContext(url, keyword, city) {
  const parsed = parseUrl(url);
  if (!parsed) return 0;

  const keywordParts = keywordTokens(keyword);
  const cityParts = keywordTokens(city);
  const target = normalizePhrase(`${parsed.hostname} ${parsed.pathname.replace(/\//g, " ")}`);
  let score = 24;

  if (parsed.protocol === "https:") score += 5;
  if (parsed.pathname && parsed.pathname !== "/") score += 8;
  if (keywordParts.some((token) => target.includes(token))) score += 15;
  if (cityParts.some((token) => target.includes(token))) score += 12;
  if (/locations?|areas?|services?|reviews?|projects?|about|faq|blog/.test(target)) score += 8;
  if (parsed.hostname.split(".")[0].length <= 18) score += 4;
  if ((target.match(/-/g) || []).length >= 2) score += 3;

  return clampScore(score);
}

export function scoreCompleteness(input) {
  const fields = [
    input.websiteUrl,
    input.businessName,
    input.targetCity,
    input.targetState,
    input.mainKeyword,
    input.mapsUrl,
  ];
  const base = fields.reduce((sum, field) => sum + (String(field || "").trim() ? 12 : 0), 0);
  const competitorBoost = Math.min(18, (input.competitors || []).filter((item) => item.websiteUrl || item.mapsUrl).length * 6);
  const noteBoost = String(input.notes || "").trim().length >= 40 ? 10 : String(input.notes || "").trim() ? 5 : 0;
  return clampScore(base + competitorBoost + noteBoost);
}

export function phrasePresenceScore(text, phrases) {
  const normalized = normalizePhrase(text);
  return phrases.reduce((sum, phrase) => sum + (normalized.includes(normalizePhrase(phrase)) ? 1 : 0), 0);
}

export function averageScores(values) {
  const usable = values.map(Number).filter((value) => !Number.isNaN(value));
  if (!usable.length) return 0;
  return clampScore(usable.reduce((sum, value) => sum + value, 0) / usable.length);
}

export function scoreSummary(score) {
  const band = scoreBand(score);
  if (band === "strong") return "Strong estimated foundation";
  if (band === "moderate") return "Moderate estimated foundation";
  return "Weak estimated foundation";
}

export function scoreDeltaLabel(userScore, competitorScore) {
  const delta = clampScore(competitorScore) - clampScore(userScore);
  if (delta >= 14) return "Material competitor edge";
  if (delta >= 6) return "Moderate competitor edge";
  if (delta <= -6) return "User appears stronger";
  return "Near parity";
}

export function parseUrl(url) {
  const value = String(url || "").trim();
  if (!value) return null;
  try {
    return new URL(value.includes("://") ? value : `https://${value}`);
  } catch (error) {
    return null;
  }
}
