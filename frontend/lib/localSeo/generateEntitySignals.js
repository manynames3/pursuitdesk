import { normalizePhrase, phrasePresenceScore, titleCase } from "./scoring.js";

export function generateEntitySignals(input) {
  const notes = normalizePhrase(input.notes);
  const hasMaps = Boolean(input.mapsUrl);
  const hasName = Boolean(input.businessName);
  const hasLocation = Boolean(input.targetCity && input.targetState);
  const keyword = titleCase(input.mainKeyword || "Primary service");
  const city = titleCase(input.targetCity || "target city");

  return [
    signal("Business name consistency", hasName ? "strong" : "missing", hasName ? `Business name provided as ${input.businessName}.` : "No business name entered.", "Match the exact business name across the site, GBP, citations, schema, and reviews."),
    signal("Address and phone consistency", notesMatch(notes, ["address", "phone", "nap"]) ? "needs-work" : "missing", "Address/phone consistency cannot be confirmed without a crawl or citation source.", "Expose a consistent NAP block and validate it against GBP and major citations."),
    signal("Service categories", input.mainKeyword ? "needs-work" : "missing", input.mainKeyword ? `Primary service entered as ${keyword}.` : "Primary service keyword missing.", "Map the primary service to GBP categories, service pages, headings, and schema."),
    signal("City mentions", hasLocation ? "strong" : "missing", hasLocation ? `Target market entered as ${city}, ${String(input.targetState).toUpperCase()}.` : "City/state missing.", "Mention the city naturally on the homepage, service pages, location pages, testimonials, and project pages."),
    signal("Nearby neighborhood mentions", notesMatch(notes, ["neighborhood", "county", "suburb", "nearby"]) ? "needs-work" : "missing", "Neighborhood coverage is not confirmed in the current inputs.", "Add a local area hub with helpful neighborhood references and avoid thin duplicated pages."),
    signal("Team/about page", notesMatch(notes, ["team", "about", "owner", "founder"]) ? "strong" : "missing", "Team/about evidence is not confirmed by the current placeholder workflow.", "Create or strengthen an about page with team, experience, local presence, and credentials."),
    signal("Reviews/testimonials", notesMatch(notes, ["review", "testimonial", "rating"]) ? "strong" : "needs-work", "Review evidence needs a GBP or review source connection for validation.", "Connect reviews to service and city proof; summarize review themes without marking them up improperly."),
    signal("Project examples", notesMatch(notes, ["project", "case study", "before", "after"]) ? "strong" : "missing", "Project examples are not confirmed without site crawl data.", `Publish ${keyword} project examples in ${city} with photos, context, and outcomes.`),
    signal("Licenses/certifications", notesMatch(notes, ["license", "certified", "certification", "insured", "bonded"]) ? "strong" : "missing", "Licensing/certification signals are not confirmed in structured inputs.", "Add licenses, certifications, insurance, and associations where relevant."),
    signal("Service area page", notesMatch(notes, ["service area", "areas served", "locations"]) ? "needs-work" : "missing", "Service-area architecture needs crawl validation.", "Build a service-area hub that links to the main service, city, neighborhood, and project pages."),
    signal("GBP alignment", hasMaps ? "needs-work" : "missing", hasMaps ? "GBP / Maps URL provided for future validation." : "No GBP / Maps URL provided.", "Align GBP categories, services, description, photos, reviews, and website landing pages."),
    signal("LocalBusiness schema", notesMatch(notes, ["schema", "localbusiness"]) ? "needs-work" : "missing", "Schema cannot be verified until a crawler or schema parser is connected.", "Add LocalBusiness schema with name, URL, area served, phone, address, opening hours, and sameAs links."),
    signal("FAQ schema", notesMatch(notes, ["faq schema", "faq"]) ? "needs-work" : "missing", "FAQ schema presence is not confirmed.", "Use FAQ schema only on visible, helpful FAQ content that matches the page intent."),
    signal("Review schema where appropriate", notesMatch(notes, ["review schema"]) ? "needs-work" : "missing", "Review markup needs policy-aware validation.", "Use review markup only where it is eligible and visible on-page; avoid self-serving misuse."),
    signal("Breadcrumb schema", notesMatch(notes, ["breadcrumb"]) ? "needs-work" : "missing", "Breadcrumb schema is not confirmed.", "Use breadcrumbs on service, city, blog, FAQ, and project templates to clarify hierarchy."),
  ];
}

export function generateAiSearchReadiness(input) {
  const notes = normalizePhrase(input.notes);
  const hasIdentity = Boolean(input.businessName && input.websiteUrl);
  const hasService = Boolean(input.mainKeyword);
  const hasArea = Boolean(input.targetCity && input.targetState);

  return [
    signal("Clear business identity", hasIdentity ? "strong" : "missing", hasIdentity ? `${input.businessName} and website URL provided.` : "Business identity is incomplete.", "Make the company name, website, phone, address, and service area explicit."),
    signal("Clear services", hasService ? "needs-work" : "missing", hasService ? `Primary service is ${titleCase(input.mainKeyword)}.` : "Primary service missing.", "Build a service taxonomy that links main, supporting, emergency, cost, and FAQ content."),
    signal("Clear service area", hasArea ? "strong" : "missing", hasArea ? `Service area target is ${titleCase(input.targetCity)}, ${String(input.targetState).toUpperCase()}.` : "Target market missing.", "Use consistent city, state, service-area, and nearby area language."),
    signal("Clear proof", notesMatch(notes, ["review", "testimonial", "project", "case study"]) ? "needs-work" : "missing", "Proof signals need source validation.", "Show reviews, testimonials, project examples, photos, and measurable outcomes."),
    signal("Clear pricing/cost guidance", notesMatch(notes, ["price", "pricing", "cost"]) ? "needs-work" : "missing", "Cost guidance is not confirmed.", "Publish cost ranges, factors that affect price, and quote process details where appropriate."),
    signal("Clear process", notesMatch(notes, ["process", "timeline", "inspection", "estimate"]) ? "needs-work" : "missing", "Process content is not confirmed.", "Explain the service process from first contact through completion and follow-up."),
    signal("Clear FAQs", notesMatch(notes, ["faq", "question"]) ? "needs-work" : "missing", "FAQ coverage is not confirmed.", "Answer real customer questions on the relevant service and city pages."),
    signal("Structured data", notesMatch(notes, ["schema", "structured data"]) ? "needs-work" : "missing", "Structured data must be verified by a future crawler.", "Add LocalBusiness, Breadcrumb, FAQ, and service-relevant schema where eligible."),
    signal("Author/company credibility", notesMatch(notes, ["author", "expert", "owner", "team"]) ? "needs-work" : "missing", "Credibility signals are not confirmed.", "Show who stands behind the content and why the company is qualified."),
    signal("Updated content", notesMatch(notes, ["updated", "fresh", "2026", "recent"]) ? "needs-work" : "missing", "Freshness cannot be verified without crawl timestamps.", "Refresh key service, city, cost, FAQ, and project content on a visible cadence."),
  ];
}

function signal(label, status, evidence, recommendation) {
  return { label, status, evidence, recommendation };
}

function notesMatch(notes, phrases) {
  return phrasePresenceScore(notes, phrases) > 0;
}
