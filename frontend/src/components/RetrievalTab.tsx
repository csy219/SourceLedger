import {
  AlertTriangle,
  Gauge,
  LoaderCircle,
  Search,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import {
  getRunTrace,
  runCapability,
} from "../api";
import type {
  CapabilityRunResponse,
  RunTraceEvent,
} from "../types";

interface RetrievalCandidateView {
  chunk_id: string;
  source: string;
  page: number;
  vector_rank: number | null;
  vector_score: number | null;
  bm25_rank: number | null;
  bm25_score: number | null;
  rrf_rank: number | null;
  rrf_score: number | null;
  rerank_rank: number | null;
  rerank_score: number | null;
}

interface RetrievalData {
  vector_candidates: RetrievalCandidateView[];
  bm25_candidates: RetrievalCandidateView[];
  fused_candidates: RetrievalCandidateView[];
  reranked_candidates: RetrievalCandidateView[];
  latency_ms: number;
  mode: string;
  fallback_used: string;
}

interface RetrievalOutput {
  retrieval: RetrievalData;
  vector_count: number;
  bm25_count: number;
  fused_count: number;
}

interface RerankOutput {
  before: RetrievalCandidateView[];
  after: RetrievalCandidateView[];
  rerank_triggered: boolean;
  rerank_status: string;
  rerank_metadata: {
    backend?: string;
    model_name?: string;
    load_ms?: number;
    input_count?: number;
    output_count?: number;
    error?: string;
  };
}

type CandidateKind =
  | "vector"
  | "bm25"
  | "rrf"
  | "rerank";

function rankOf(
  candidate: RetrievalCandidateView,
  kind: CandidateKind,
): number | null {
  if (kind === "vector") {
    return candidate.vector_rank;
  }
  if (kind === "bm25") {
    return candidate.bm25_rank;
  }
  if (kind === "rrf") {
    return candidate.rrf_rank;
  }
  return candidate.rerank_rank;
}

function scoreOf(
  candidate: RetrievalCandidateView,
  kind: CandidateKind,
): number | null {
  if (kind === "vector") {
    return candidate.vector_score;
  }
  if (kind === "bm25") {
    return candidate.bm25_score;
  }
  if (kind === "rrf") {
    return candidate.rrf_score;
  }
  return candidate.rerank_score;
}

function formatScore(
  value: number | null,
): string {
  if (value === null) {
    return "-";
  }
  return value.toFixed(4);
}

function CandidateList({
  title,
  candidates,
  kind,
}: {
  title: string;
  candidates: RetrievalCandidateView[];
  kind: CandidateKind;
}) {
  return (
    <section className="retrieval-list">
      <header>
        <strong>{title}</strong>
        <span>{candidates.length}</span>
      </header>

      {candidates.length ? (
        <div className="retrieval-scroll">
          {candidates.map((candidate) => (
            <article
              className="retrieval-candidate"
              key={`${kind}-${candidate.chunk_id}-${rankOf(candidate, kind)}`}
            >
              <div className="retrieval-rank">
                <strong>
                  {rankOf(candidate, kind) ?? "-"}
                </strong>
                <span>
                  {formatScore(
                    scoreOf(candidate, kind),
                  )}
                </span>
              </div>
              <div className="retrieval-copy">
                <strong>{candidate.source}</strong>
                <span>
                  Page {candidate.page} ·{" "}
                  {candidate.chunk_id}
                </span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="retrieval-empty">
          <Search size={20} />
          <span>No candidates.</span>
        </div>
      )}
    </section>
  );
}

function TraceList({
  events,
}: {
  events: RunTraceEvent[];
}) {
  if (!events.length) {
    return (
      <div className="retrieval-empty">
        <Workflow size={20} />
        <span>No trace events yet.</span>
      </div>
    );
  }

  return (
    <div className="retrieval-trace">
      {events.map((event) => (
        <article key={event.event_id}>
          <span
            className={`ops-event-status ops-event-${event.status}`}
          >
            {event.status}
          </span>
          <div>
            <strong>{event.operation}</strong>
            <p>{event.action || "completed"}</p>
          </div>
          <span>{event.duration_ms.toFixed(2)} ms</span>
        </article>
      ))}
    </div>
  );
}

export default function RetrievalTab() {
  const [question, setQuestion] = useState(
    "差旅报销制度中的住宿标准是什么？",
  );
  const [semanticQuery, setSemanticQuery] =
    useState(
      "差旅报销制度中的住宿标准是什么？",
    );
  const [keywordQuery, setKeywordQuery] =
    useState("差旅 报销 制度 住宿 标准");
  const [candidateK, setCandidateK] =
    useState(5);
  const [retrieval, setRetrieval] =
    useState<RetrievalOutput | null>(null);
  const [rerank, setRerank] =
    useState<RerankOutput | null>(null);
  const [retrievalTrace, setRetrievalTrace] =
    useState<RunTraceEvent[]>([]);
  const [rerankTrace, setRerankTrace] =
    useState<RunTraceEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function runRetrieval() {
    if (!question.trim()) {
      return;
    }

    setRunning(true);
    setError("");
    setRetrieval(null);
    setRerank(null);
    setRetrievalTrace([]);
    setRerankTrace([]);

    const input = {
      question: question.trim(),
      semantic_query:
        semanticQuery.trim() || question.trim(),
      keyword_query:
        keywordQuery.trim() || question.trim(),
      candidate_k: Number(candidateK) || 5,
    };

    try {
      const retrievalResponse =
        await runCapability(
          "retrieval_hybrid",
          {
            thread_id: "retrieval-tab",
            input,
          },
        );

      setRetrieval(
        retrievalResponse.output as unknown as RetrievalOutput,
      );

      const retrievalTraceResult =
        await getRunTrace(
          retrievalResponse.run_id,
        );
      setRetrievalTrace(
        retrievalTraceResult.events,
      );

      const rerankResponse: CapabilityRunResponse =
        await runCapability(
          "rerank_comparison",
          {
            thread_id: "retrieval-tab",
            input,
          },
        );

      setRerank(
        rerankResponse.output as unknown as RerankOutput,
      );

      const rerankTraceResult =
        await getRunTrace(
          rerankResponse.run_id,
        );
      setRerankTrace(
        rerankTraceResult.events,
      );
    } catch (runError) {
      setError(
        runError instanceof Error
          ? runError.message
          : String(runError),
      );
    } finally {
      setRunning(false);
    }
  }

  const retrievalData = retrieval?.retrieval;

  return (
    <div className="ops-tab-body retrieval-tab">
      <div className="ops-tab-heading">
        <Search size={24} />
        <div>
          <p className="ops-kicker">
            Hybrid retrieval
          </p>
          <h2>Retrieval Lab</h2>
          <p>
            Run the real Vector, BM25, RRF and
            CrossEncoder pipeline for one question.
          </p>
        </div>
      </div>

      <section className="retrieval-controls">
        <label>
          <span>Question</span>
          <textarea
            value={question}
            rows={3}
            onChange={(event) =>
              setQuestion(event.target.value)
            }
          />
        </label>

        <label>
          <span>Semantic query</span>
          <input
            value={semanticQuery}
            onChange={(event) =>
              setSemanticQuery(
                event.target.value,
              )
            }
          />
        </label>

        <label>
          <span>Keyword query</span>
          <input
            value={keywordQuery}
            onChange={(event) =>
              setKeywordQuery(
                event.target.value,
              )
            }
          />
        </label>

        <label className="retrieval-k">
          <span>Candidate K</span>
          <input
            min={1}
            max={50}
            type="number"
            value={candidateK}
            onChange={(event) =>
              setCandidateK(
                Number(event.target.value),
              )
            }
          />
        </label>

        <button
          type="button"
          disabled={running || !question.trim()}
          onClick={runRetrieval}
        >
          {running ? (
            <LoaderCircle
              className="ops-spin"
              size={17}
            />
          ) : (
            <Gauge size={17} />
          )}
          {running ? "Running" : "Run comparison"}
        </button>
      </section>

      {error ? (
        <div className="ops-error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {retrievalData ? (
        <>
          <section className="retrieval-summary">
            <div>
              <span>Vector</span>
              <strong>
                {retrieval?.vector_count ?? 0}
              </strong>
            </div>
            <div>
              <span>BM25</span>
              <strong>
                {retrieval?.bm25_count ?? 0}
              </strong>
            </div>
            <div>
              <span>RRF</span>
              <strong>
                {retrieval?.fused_count ?? 0}
              </strong>
            </div>
            <div>
              <span>Mode</span>
              <strong>{retrievalData.mode}</strong>
            </div>
            <div>
              <span>Latency</span>
              <strong>
                {retrievalData.latency_ms.toFixed(
                  2,
                )}{" "}
                ms
              </strong>
            </div>
            <div>
              <span>Rerank</span>
              <strong>
                {rerank?.rerank_metadata
                  ?.backend ?? "pending"}
              </strong>
            </div>
          </section>

          <div className="retrieval-columns">
            <CandidateList
              title="Vector"
              candidates={
                retrievalData.vector_candidates
              }
              kind="vector"
            />
            <CandidateList
              title="BM25"
              candidates={
                retrievalData.bm25_candidates
              }
              kind="bm25"
            />
            <CandidateList
              title="RRF"
              candidates={
                retrievalData.fused_candidates
              }
              kind="rrf"
            />
            <CandidateList
              title="After Rerank"
              candidates={
                rerank?.after ??
                retrievalData.reranked_candidates
              }
              kind="rerank"
            />
          </div>

          <section className="retrieval-trace-panel">
            <header>
              <strong>Execution Trace</strong>
              <span>
                {retrievalTrace.length +
                  rerankTrace.length}{" "}
                events
              </span>
            </header>
            <TraceList
              events={[
                ...retrievalTrace,
                ...rerankTrace,
              ]}
            />
          </section>
        </>
      ) : (
        <div className="retrieval-empty retrieval-main-empty">
          <Search size={24} />
          <span>
            Run a query to compare retrieval and
            reranking.
          </span>
        </div>
      )}
    </div>
  );
}