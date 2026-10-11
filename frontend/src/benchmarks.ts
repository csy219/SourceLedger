export const benchmarkSnapshot = {
  retrieval: {
    hitAt1: 0.9762,
    recallAt4: 0.9881,
    mrr: 0.9881,
    ndcgAt4: 0.9763,
  },
  context: {
    invalidCitations: 0,
    citationRecall: 1.0,
    conflictCoverage: "3 / 3",
    injectionCoverage: "2 / 2",
    averageTokens: 451,
  },
  load: {
    p50: 135.01,
    p95: 286.89,
    max: 354.09,
    successful: 20,
    failed: 0,
    contextTokens: 2400,
  },
};

