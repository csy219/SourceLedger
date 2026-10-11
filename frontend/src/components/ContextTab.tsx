import {
  AlertTriangle,
  FileText,
  Layers,
  Link2,
  LoaderCircle,
  ShieldAlert,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import {
  getRunTrace,
  runCapability,
} from "../api";
import type { RunTraceEvent } from "../types";

interface ContextStats {
  input_count?: number;
  deduped_count?: number;
  duplicate_text_count?: number;
  selected_count?: number;
  unique_sources?: number;
  unique_pages?: number;
  suspicious_count?: number;
  retrieval_tokens?: number;
  retrieval_remaining?: number;
  page_limit_skipped?: number;
  parent_limit_skipped?: number;
  budget_skipped?: number;
}

interface EvidenceView {
  evidence_id: string;
  chunk_id: string;
  source: string;
  page: number;
  text: string;
  score: number;
  trust_level: string;
  suspicious_instruction: boolean;
  content_type: string;
}

interface CitationView {
  citation_id: string;
  evidence_id: string;
  source: string;
  page: number;
}

interface ConflictView {
  topic: string;
  source_a: string;
  source_b: string;
  differences: string[];
  requires_disclosure: boolean;
}

interface InjectionView {
  finding_id: string;
  chunk_id: string;
  severity: string;
  matched_pattern: string;
  action: string;
  excerpt: string;
}

interface ContextBody {
  context_text: string;
  evidence: EvidenceView[];
  citations: CitationView[];
  conflicts: ConflictView[];
  injections: InjectionView[];
  context_tokens: number;
  budget_used: number;
  duplicate_text_count: number;
  source_diversity: number;
  metadata?: {
    context_stats?: ContextStats;
  };
}

interface ContextOutput {
  context: ContextBody;
  evidence_count: number;
  citation_count: number;
  conflict_count: number;
  injection_count: number;
  context_tokens: number;
  source_diversity: number;
}

function numberFrom(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function TraceList({
  events,
}: {
  events: RunTraceEvent[];
}) {
  if (!events.length) {
    return (
      <div className="context-empty">
        <Workflow size={20} />
        <span>No trace events yet.</span>
      </div>
    );
  }

  return (
    <div className="context-trace-list">
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

export default function ContextTab() {
  const [question, setQuestion] = useState(
    "差旅报销制度中的住宿标准是什么？",
  );
  const [semanticQuery, setSemanticQuery] =
    useState("差旅报销制度中的住宿标准是什么？");
  const [keywordQuery, setKeywordQuery] =
    useState("差旅 报销 制度 住宿 标准");
  const [candidateK, setCandidateK] = useState(12);
  const [retrievalBudget, setRetrievalBudget] =
    useState(1800);
  const [maxChunkPerPage, setMaxChunkPerPage] =
    useState(2);
  const [maxChunkPerParent, setMaxChunkPerParent] =
    useState(2);
  const [allowRerank, setAllowRerank] =
    useState(false);
  const [contextOutput, setContextOutput] =
    useState<ContextOutput | null>(null);
  const [trace, setTrace] = useState<
    RunTraceEvent[]
  >([]);
  const [runId, setRunId] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function runContextPacking() {
    if (!question.trim()) {
      return;
    }

    setRunning(true);
    setError("");
    setContextOutput(null);
    setTrace([]);
    setRunId("");

    try {
      const response = await runCapability(
        "context_packing",
        {
          thread_id: "context-tab",
          input: {
            question: question.trim(),
            semantic_query:
              semanticQuery.trim() || question.trim(),
            keyword_query:
              keywordQuery.trim() || question.trim(),
            candidate_k: Number(candidateK) || 12,
            retrieval_budget:
              Number(retrievalBudget) || 1800,
            max_chunk_per_page:
              Number(maxChunkPerPage) || 2,
            max_chunk_per_parent:
              Number(maxChunkPerParent) || 2,
            allow_rerank: allowRerank,
          },
        },
      );

      setContextOutput(
        response.output as unknown as ContextOutput,
      );
      setRunId(response.run_id);

      const traceResult = await getRunTrace(
        response.run_id,
      );
      setTrace(traceResult.events);
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

  const context = contextOutput?.context;
  const stats = context?.metadata?.context_stats ?? {};

  return (
    <div className="ops-tab-body context-tab">
      <div className="ops-tab-heading">
        <Layers size={24} />
        <div>
          <p className="ops-kicker">Evidence packing</p>
          <h2>Context Lab</h2>
          <p>
            Inspect deduplication, budget, citations,
            conflicts and injection handling.
          </p>
        </div>
      </div>

      <section className="context-controls">
        <label className="context-question">
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
              setSemanticQuery(event.target.value)
            }
          />
        </label>

        <label>
          <span>Keyword query</span>
          <input
            value={keywordQuery}
            onChange={(event) =>
              setKeywordQuery(event.target.value)
            }
          />
        </label>

        <label>
          <span>Candidate K</span>
          <input
            min={1}
            max={50}
            type="number"
            value={candidateK}
            onChange={(event) =>
              setCandidateK(Number(event.target.value))
            }
          />
        </label>

        <label>
          <span>Token budget</span>
          <input
            min={100}
            step={100}
            type="number"
            value={retrievalBudget}
            onChange={(event) =>
              setRetrievalBudget(
                Number(event.target.value),
              )
            }
          />
        </label>

        <label>
          <span>Max / page</span>
          <input
            min={1}
            max={20}
            type="number"
            value={maxChunkPerPage}
            onChange={(event) =>
              setMaxChunkPerPage(
                Number(event.target.value),
              )
            }
          />
        </label>

        <label>
          <span>Max / parent</span>
          <input
            min={1}
            max={20}
            type="number"
            value={maxChunkPerParent}
            onChange={(event) =>
              setMaxChunkPerParent(
                Number(event.target.value),
              )
            }
          />
        </label>

        <label className="context-checkbox">
          <input
            checked={allowRerank}
            type="checkbox"
            onChange={(event) =>
              setAllowRerank(event.target.checked)
            }
          />
          <span>Allow Rerank</span>
        </label>

        <button
          type="button"
          disabled={running || !question.trim()}
          onClick={runContextPacking}
        >
          {running ? (
            <LoaderCircle
              className="ops-spin"
              size={17}
            />
          ) : (
            <Layers size={17} />
          )}
          {running ? "Running" : "Build context"}
        </button>
      </section>

      {error ? (
        <div className="ops-error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {context ? (
        <>
          <section className="context-summary">
            {[
              ["Input", stats.input_count],
              ["Deduped", stats.deduped_count],
              [
                "Duplicates",
                stats.duplicate_text_count,
              ],
              ["Selected", stats.selected_count],
              [
                "Context tokens",
                context.context_tokens,
              ],
              [
                "Remaining",
                stats.retrieval_remaining,
              ],
              ["Sources", stats.unique_sources],
              [
                "Diversity",
                context.source_diversity,
              ],
              [
                "Conflicts",
                context.conflicts.length,
              ],
              [
                "Injections",
                context.injections.length,
              ],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <span>{label}</span>
                <strong>
                  {numberFrom(value).toFixed(
                    label === "Diversity" ? 4 : 0,
                  )}
                </strong>
              </div>
            ))}
          </section>

          <div className="context-metrics-line">
            <span>
              Page limit skipped:{" "}
              {numberFrom(stats.page_limit_skipped)}
            </span>
            <span>
              Parent limit skipped:{" "}
              {numberFrom(stats.parent_limit_skipped)}
            </span>
            <span>
              Budget skipped:{" "}
              {numberFrom(stats.budget_skipped)}
            </span>
            <span>Run: {runId.slice(0, 12)}</span>
          </div>

          <div className="context-grid">
            <section className="context-panel">
              <header>
                <FileText size={17} />
                <strong>Evidence</strong>
                <span>{context.evidence.length}</span>
              </header>
              <div className="context-list">
                {context.evidence.map((item) => (
                  <article
                    className="context-evidence"
                    key={item.evidence_id}
                  >
                    <div>
                      <code>{item.evidence_id}</code>
                      <span>{item.source}</span>
                      <span>Page {item.page}</span>
                    </div>
                    <p>{item.text}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="context-panel">
              <header>
                <Link2 size={17} />
                <strong>Citations</strong>
                <span>{context.citations.length}</span>
              </header>
              <div className="context-list">
                {context.citations.map((citation) => (
                  <article
                    className="context-citation"
                    key={citation.citation_id}
                  >
                    <code>{citation.citation_id}</code>
                    <div>
                      <strong>{citation.source}</strong>
                      <span>
                        Page {citation.page} ·{" "}
                        {citation.evidence_id}
                      </span>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          </div>

          <div className="context-grid">
            <section className="context-panel">
              <header>
                <AlertTriangle size={17} />
                <strong>Conflicts</strong>
                <span>{context.conflicts.length}</span>
              </header>
              {context.conflicts.length ? (
                <div className="context-list">
                  {context.conflicts.map(
                    (conflict, index) => (
                      <article
                        className="context-conflict"
                        key={`${conflict.topic}-${index}`}
                      >
                        <strong>{conflict.topic}</strong>
                        <span>{conflict.source_a}</span>
                        <span>{conflict.source_b}</span>
                        {conflict.differences.map(
                          (difference) => (
                            <p key={difference}>
                              {difference}
                            </p>
                          ),
                        )}
                      </article>
                    ),
                  )}
                </div>
              ) : (
                <div className="context-empty">
                  <span>No version conflict detected.</span>
                </div>
              )}
            </section>

            <section className="context-panel">
              <header>
                <ShieldAlert size={17} />
                <strong>Injections</strong>
                <span>{context.injections.length}</span>
              </header>
              {context.injections.length ? (
                <div className="context-list">
                  {context.injections.map(
                    (injection) => (
                      <article
                        className="context-injection"
                        key={injection.finding_id}
                      >
                        <strong>{injection.severity}</strong>
                        <span>{injection.chunk_id}</span>
                        <p>{injection.matched_pattern}</p>
                      </article>
                    ),
                  )}
                </div>
              ) : (
                <div className="context-empty">
                  <span>No injection signal detected.</span>
                </div>
              )}
            </section>
          </div>

          <section className="context-panel">
            <header>
              <Layers size={17} />
              <strong>Final Context</strong>
            </header>
            <pre className="context-text">
              {context.context_text}
            </pre>
          </section>

          <section className="context-panel">
            <header>
              <Workflow size={17} />
              <strong>Context Trace</strong>
              <span>{trace.length}</span>
            </header>
            <TraceList events={trace} />
          </section>
        </>
      ) : (
        <div className="context-empty context-main-empty">
          <Layers size={24} />
          <span>
            Build a context to inspect evidence and
            citations.
          </span>
        </div>
      )}
    </div>
  );
}