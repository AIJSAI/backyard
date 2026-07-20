export const meta = {
  name: 'judge-content',
  description: 'Four-lens judge panel for any public-facing Backyard writing (docs, posts, README)',
  whenToUse: 'Before shipping ANY outward-facing prose: repo docs, launch posts, X/LinkedIn drafts, docs-site pages.',
  phases: [{ title: 'Judge', detail: 'four independent lenses per file; consensus required' }],
}

const VERDICT = {
  type: 'object',
  additionalProperties: false,
  required: ['file', 'lens', 'score', 'blockers', 'edits', 'one_liner'],
  properties: {
    file: { type: 'string' },
    lens: { type: 'string' },
    score: { type: 'number', minimum: 1, maximum: 10 },
    blockers: { type: 'array', items: { type: 'string' }, description: 'Issues that MUST be fixed before shipping; empty if none' },
    edits: { type: 'array', items: { type: 'string' }, description: 'Concrete suggested edits (quote the exact text and give the replacement)' },
    one_liner: { type: 'string', description: 'The verdict in one sentence' },
  },
}

const LENSES = [
  {
    key: 'slop',
    charter: `SLOP DETECTOR. You are a skeptical senior engineer who instantly smells LLM-generated content. Hunt for: AI-tell vocabulary (delve, seamless, robust, leverage, journey, empower, game-changer, revolutionize, "in today's world"), em-dashes, listicle cadence, engagement-bait hooks, hollow superlatives, symmetrical paragraph rhythm, conclusions that restate the intro. Score 10 = reads like a sharp human wrote it fast; anything that would make you mutter "AI wrote this" is a blocker.`,
  },
  {
    key: 'substance',
    charter: `SUBSTANCE JUDGE. You are a principal product manager reviewing a peer's public artifact. Hunt for: claims without receipts, framework theater, vague benefit language where a concrete mechanism should be, decisions presented without trade-offs, anything a sharp interviewer would puncture with one follow-up question. Score 10 = every claim is either evidenced, honestly labeled as a bet, or scoped; unsupported claims are blockers.`,
  },
  {
    key: 'audience',
    charter: `AUDIENCE JUDGE. You are a long-time r/selfhosted and Hacker News regular who is actively hostile to marketing speak. Hunt for: hype, unearned superlatives, corporate voice, anything that would draw a snarky top comment, overpromising versus what the repo actually contains today. Score 10 = you would upvote it and say "finally, someone gets it"; anything that would get roasted in the first hour is a blocker.`,
  },
  {
    key: 'voice',
    charter: `VOICE JUDGE. The author is a direct, plainspoken product manager from Omaha who hates corporate speak and AI-flavored prose. Rules of his voice: no em-dashes, no banlist words (delve, seamless, leverage, empower, journey), short declaratives over subordinate-clause towers, opinions stated as opinions, dry humor allowed, no exclamation marks doing the enthusiasm's job. Score 10 = he could read it aloud without wincing; voice violations are edits, systematic ones are blockers.`,
  },
]

const input = typeof args === 'string' ? JSON.parse(args) : args
const FILES = (input && input.files) || []
if (!FILES.length) throw new Error('judge-content requires args.files: [paths]')
const CONTEXT = (input && input.context) || 'Backyard: open-source, self-hosted private family social network. Pre-alpha, built in public. Tone: calm, evidence-first, zero hype.'

phase('Judge')
log(`Judging ${FILES.length} file(s) across ${LENSES.length} lenses`)

const results = await pipeline(
  FILES,
  (file) =>
    parallel(
      LENSES.map((l) => () =>
        agent(
          `${l.charter}

PROJECT CONTEXT: ${CONTEXT}

Read the file at: ${file}
Judge ONLY the prose a reader sees (ignore YAML/code mechanics unless the words inside them are reader-facing). Return your verdict via structured output. Set "file" to "${file}" and "lens" to "${l.key}". Be specific: quote exact offending text in blockers/edits. Do not invent problems to seem rigorous; a clean file deserves its 9.`,
          { label: `judge:${l.key}:${file.split('/').pop()}`, phase: 'Judge', schema: VERDICT }
        )
      )
    ),
  (verdicts, file) => {
    const clean = verdicts.filter(Boolean)
    const blockers = clean.flatMap((v) => v.blockers.map((b) => `[${v.lens}] ${b}`))
    const minScore = Math.min(...clean.map((v) => v.score))
    return {
      file,
      ship: blockers.length === 0 && minScore >= 8,
      minScore,
      scores: Object.fromEntries(clean.map((v) => [v.lens, v.score])),
      blockers,
      edits: clean.flatMap((v) => v.edits.map((e) => `[${v.lens}] ${e}`)),
      one_liners: clean.map((v) => `${v.lens}: ${v.one_liner}`),
    }
  }
)

const done = results.filter(Boolean)
log(`Verdicts: ${done.filter((r) => r.ship).length}/${done.length} ship as-is`)
return { verdicts: done }
