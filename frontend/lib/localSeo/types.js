/**
 * Data model reference for the static Local SEO analyzer.
 *
 * The frontend is a browser-only app, so these are JSDoc shapes instead of
 * TypeScript interfaces. They mirror the API-ready contracts expected by the
 * analyzer modules.
 *
 * @typedef {Object} CompetitorInput
 * @property {string} websiteUrl
 * @property {string} mapsUrl
 *
 * @typedef {Object} LocalSeoInput
 * @property {string} websiteUrl
 * @property {string} businessName
 * @property {string} targetCity
 * @property {string} targetState
 * @property {string} mainKeyword
 * @property {string} mapsUrl
 * @property {string} notes
 * @property {CompetitorInput[]} competitors
 *
 * @typedef {Object} SeoScore
 * @property {string} key
 * @property {string} label
 * @property {number} value
 * @property {"strong" | "moderate" | "weak"} band
 * @property {string} summary
 *
 * @typedef {Object} CompetitorAnalysis
 * @property {string} label
 * @property {string} website
 * @property {boolean} isUser
 * @property {number} topicalCoverage
 * @property {number} servicePageDepth
 * @property {number} cityRelevance
 * @property {number} trustSignals
 * @property {number} internalLinking
 * @property {number} schemaReadiness
 * @property {number} contentFreshness
 * @property {number} overallStrength
 * @property {string} note
 *
 * @typedef {Object} TopicGap
 * @property {string} topic
 * @property {string} type
 * @property {string} why
 * @property {number} priority
 * @property {string} suggestedPageType
 *
 * @typedef {Object} EntitySignal
 * @property {string} label
 * @property {"strong" | "needs-work" | "missing"} status
 * @property {string} evidence
 * @property {string} recommendation
 *
 * @typedef {Object} InternalLinkRecommendation
 * @property {string} from
 * @property {string} to
 * @property {string} anchor
 * @property {string} reason
 *
 * @typedef {Object} RoadmapTask
 * @property {string} task
 * @property {string} why
 * @property {"High" | "Medium" | "Low"} impact
 * @property {"High" | "Medium" | "Low"} difficulty
 * @property {number} priority
 *
 * @typedef {Object} LocalSeoReport
 * @property {string} id
 * @property {string} createdAt
 * @property {LocalSeoInput} input
 * @property {SeoScore[]} scores
 * @property {CompetitorAnalysis[]} competitors
 * @property {TopicGap[]} topicGaps
 * @property {EntitySignal[]} entitySignals
 * @property {InternalLinkRecommendation[]} internalLinks
 * @property {EntitySignal[]} aiSearchReadiness
 * @property {{thisWeek: RoadmapTask[], thisMonth: RoadmapTask[], nextQuarter: RoadmapTask[]}} roadmap
 * @property {string[]} assumptions
 * @property {string[]} todos
 */

export const LOCAL_SEO_ANALYSIS_MODE = "Estimated / placeholder until live crawl is connected";
