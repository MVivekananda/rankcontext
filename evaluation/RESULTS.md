# Evaluation: RankContext vs. Flat/Alphabetical Dump

This fulfils PRD section 14 (Evaluation Plan): compare RankContext's
ranked selection against a gitingest-style flat dump, on real
repositories, at the same token budget.

## Method

`evaluation/run_eval.py` runs both selection strategies over the same
repo + budget and reports:

- **avg_centrality** — mean import-graph centrality of the included
  file set (higher = the bundle is denser in structurally important
  files, not just early-alphabetical ones).
- **top10%_hit_rate** — what fraction of the repo's most-central decile
  of files made it into the bundle.
- **readme** — whether README.md was included.

**Repos used:** Flask and NetworkX (real, sizeable open-source Python
codebases, via their installed package source) and RankContext's own
repository (which has real git history, so it also exercises the
recency signal). This sandbox has no network access to `git clone`
arbitrary GitHub repos on demand, so these on-disk real codebases stand
in for the PRD's "small / medium / large" repo set. Flask/NetworkX are
pip-installed with no `.git` directory, so recency contributes 0 for
them — their ranking is driven by centrality + token cost + the
doc/config boost only.

## Results

```
repo            budget  method                     files    tokens  avg_cent  top10%_hit  readme
----------------------------------------------------------------------------------------------
rankcontext (self)    1500  ranked (RankContext)       6/20      1,300     0.257       50.0%      no
rankcontext (self)    1500  flat (gitingest-style)     5/20      1,451     0.081        0.0%     yes
rankcontext (self)    4000  ranked (RankContext)      10/20      3,538     0.264      100.0%      no
rankcontext (self)    4000  flat (gitingest-style)     7/20      3,836     0.098        0.0%     yes

flask             3000  ranked (RankContext)       8/26      2,772     0.216      100.0%     yes
flask             3000  flat (gitingest-style)     7/26      2,897     0.084       50.0%     yes
flask            10000  ranked (RankContext)      12/26      9,178     0.210      100.0%     yes
flask            10000  flat (gitingest-style)     9/26      9,674     0.105       50.0%     yes

networkx          5000  ranked (RankContext)      65/580     4,882     0.017        3.3%      no
networkx          5000  flat (gitingest-style)    19/580     5,000     0.000        0.0%      no
networkx         20000  ranked (RankContext)     103/580    19,864     0.018        6.7%      no
networkx         20000  flat (gitingest-style)    23/580    20,000     0.000        0.0%      no

Summary (averaged across all repos/budgets):
ranked (RankContext)     avg_centrality=0.164  avg_top10%_hit_rate=60.0%  readme_included_rate=33%
flat (gitingest-style)   avg_centrality=0.061  avg_top10%_hit_rate=16.7%  readme_included_rate=67%
```

## Reading the results

- **Ranked selection is 2.7x denser in structurally central files**
  (avg centrality 0.164 vs 0.061) and captures **3.6x more of the
  top-10%-most-central files** (60% vs 16.7% hit rate) at the same
  token budget. This is the core claim of the project — under a fixed
  budget, RankContext spends tokens on structurally important code,
  flat dumps spend tokens on whatever sorts early.
- **On NetworkX** (580 files, the "large" case) the effect is most
  dramatic on hit rate: flat dump's 0% top-decile hit rate at both
  budgets shows the real failure mode the PRD describes — alphabetical
  order has zero correlation with importance once a repo is large
  enough that most of it won't fit in the budget anyway.
- **README inclusion is mixed and worth being honest about:** flat
  dump "wins" on README inclusion rate (67% vs 33%) in this sample,
  simply because `README.md` sorts alphabetically early in small repos
  and gets swept in for free. RankContext's 2.5x doc boost measurably
  helps README compete (see the bug-fix note below) but it can still
  lose a tight budget's knapsack fight against several smaller,
  higher-value files — which is arguably the *correct* trade-off, not
  a flaw: a 1,089-token README isn't automatically worth more than six
  smaller core files that together explain more of the codebase.

## A bug this evaluation caught

Running this evaluation against RankContext's own repo surfaced a real
scoring bug: the multiplicative doc/config boost was being applied
*after* min-max normalizing the composite score to 0..1, which floors
the lowest-scoring file to exactly 0. Multiplying 0 by any boost is
still 0 — silently defeating the boost for exactly the thin,
low-centrality README files it exists to rescue. Confirmed on this
repo: README.md's score was 0.000 before the fix and 0.532 (rank #4 of
20) after it. Fixed in `scoring.compute_scores` (shift raw scores to a
positive floor, boost, *then* normalize for display) and covered by a
regression test (`test_doc_boost_is_not_neutralized_by_normalization`).
This is worth including in a report/viva as a concrete example of
evaluation-driven debugging, not just a working demo.

## Limitations of this evaluation (be upfront about these)

- No ground-truth "core files" labels — the top-decile-centrality proxy
  is a reasonable stand-in but isn't the same as human judgment of
  importance. A stronger version of this evaluation would hand-label
  5-8 repos' "true" core files and report precision/recall against
  that, or run the downstream LLM-question comparison the PRD also
  proposes.
- Flask/NetworkX lack git history in this environment, so the recency
  signal is untested here (it's covered separately by the pipeline
  unit tests, which use a repo with real commits).
- Only one weight configuration (the default 0.5/0.3/0.2) was
  evaluated; an ablation over weights would show how much each signal
  individually contributes — flagged in the original PRD review as a
  gap between "major project" and "research paper."
