import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Database,
  FileText,
  GitBranch,
  Layers,
  LoaderCircle,
  Lock,
  MessageSquare,
  Search,
  Send,
  Server,
  ShieldAlert,
  ShieldCheck,
  Upload,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import {
  type ChangeEvent,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  API_BASE_URL,
  askQuestion,
  createSession,
  getCapabilities,
  getHealth,
  getReadiness,
  getRunTrace,
  uploadDocument,
} from "./api";
import ContextTab from "./components/ContextTab";
import ResilienceTab from "./components/ResilienceTab";
import RuntimeTab from "./components/RuntimeTab";
import SecurityTab from "./components/SecurityTab";
import RetrievalTab from "./components/RetrievalTab";
import type {
  ApiStatus,
  CapabilityDescriptor,
  Citation,
  OpsTab,
  RunTraceResponse,
  SessionResponse,
} from "./types";

interface TabDefinition {
  id: OpsTab;
  label: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
}

const TAB_DEFINITIONS: TabDefinition[] = [
  {
    id: "query",
    label: "Query",
    eyebrow: "Grounded answer",
    description:
      "Run the real advanced RAG pipeline and inspect evidence, citations, latency and token usage.",
    icon: MessageSquare,
  },
  {
    id: "retrieval",
    label: "Retrieval",
    eyebrow: "Hybrid retrieval",
    description:
      "Compare Vector, BM25 and RRF candidates for the same question.",
    icon: Search,
  },
  {
    id: "context",
    label: "Context",
    eyebrow: "Evidence packing",
    description:
      "Inspect deduplication, budget, source diversity, citations, conflicts and injection signals.",
    icon: Layers,
  },
  {
    id: "resilience",
    label: "Resilience",
    eyebrow: "Failure control",
    description:
      "Run retry, fallback, circuit breaker, rate limit, lock, idempotency and recovery scenarios.",
    icon: Lock,
  },
  {
    id: "security",
    label: "Security",
    eyebrow: "Trust boundary",
    description:
      "Inspect prompt injection detection, abstention and untrusted evidence handling.",
    icon: ShieldCheck,
  },
  {
    id: "runtime",
    label: "Runtime",
    eyebrow: "Execution trace",
    description:
      "Follow run state, checkpoints, tool calls and stage-by-stage execution events.",
    icon: Workflow,
  },
];

const CAPABILITY_IDS_BY_TAB: Record<
  OpsTab,
  string[]
> = {
  query: [],
  retrieval: [
    "retrieval_hybrid",
    "rerank_comparison",
  ],
  context: ["context_packing"],
  resilience: [
    "retry_backoff",
    "fallback_chain",
    "circuit_breaker",
    "rate_limit",
    "distributed_lock",
    "idempotency",
  ],
  security: [
    "security_injection",
    "security_no_evidence",
  ],
  runtime: [
    "checkpoint_recovery",
  ],
};

function App() {
  const [activeTab, setActiveTab] =
    useState<OpsTab>("query");
  const [apiStatus, setApiStatus] =
    useState<ApiStatus>("checking");
  const [serviceName, setServiceName] =
    useState("source-ledger");
  const [databaseReady, setDatabaseReady] =
    useState(false);
  const [redisReady, setRedisReady] =
    useState(false);
  const [session, setSession] =
    useState<SessionResponse | null>(null);
  const [capabilities, setCapabilities] =
    useState<CapabilityDescriptor[]>([]);
  const [selectedFile, setSelectedFile] =
    useState<File | null>(null);
  const [uploadedSource, setUploadedSource] =
    useState("");
  const [indexedChunks, setIndexedChunks] =
    useState(0);
  const [question, setQuestion] = useState(
    "差旅报销制度中的住宿标准是什么？",
  );
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<
    Citation[]
  >([]);
  const [runId, setRunId] = useState("");
  const [trace, setTrace] =
    useState<RunTraceResponse | null>(null);
  const [traceLoading, setTraceLoading] =
    useState(false);
  const [traceError, setTraceError] =
    useState("");
  const [usage, setUsage] = useState({
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    cacheReadTokens: 0,
    contextTokens: 0,
    latencyMs: 0,
  });
  const [querying, setQuerying] =
    useState(false);
  const [uploading, setUploading] =
    useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const [
          health,
          readiness,
          createdSession,
          capabilityList,
        ] = await Promise.all([
          getHealth(),
          getReadiness(),
          createSession(),
          getCapabilities(),
        ]);

        if (!active) {
          return;
        }

        setServiceName(health.service);
        setDatabaseReady(readiness.database);
        setRedisReady(readiness.redis);
        setSession(createdSession);
        setCapabilities(capabilityList);
        setApiStatus(
          readiness.ready ? "online" : "offline",
        );
      } catch (bootstrapError) {
        if (!active) {
          return;
        }

        setApiStatus("offline");
        setError(
          bootstrapError instanceof Error
            ? bootstrapError.message
            : String(bootstrapError),
        );
      }
    }

    void bootstrap();

    return () => {
      active = false;
    };
  }, []);

  const statusLabel = useMemo(() => {
    if (apiStatus === "online") {
      return "Runtime ready";
    }
    if (apiStatus === "checking") {
      return "Checking runtime";
    }
    return "Runtime offline";
  }, [apiStatus]);

  const activeDefinition =
    TAB_DEFINITIONS.find(
      (tab) => tab.id === activeTab,
    ) ?? TAB_DEFINITIONS[0];

  const ActiveIcon = activeDefinition.icon;

  const activeCapabilities =
    capabilities.filter((capability) =>
      CAPABILITY_IDS_BY_TAB[
        activeTab
      ].includes(capability.capability_id),
    );

  function handleFileChange(
    event: ChangeEvent<HTMLInputElement>,
  ) {
    setSelectedFile(
      event.target.files?.[0] ?? null,
    );
    setError("");
  }

  async function handleUpload() {
    if (!selectedFile) {
      return;
    }

    setUploading(true);
    setError("");

    try {
      const result = await uploadDocument(
        selectedFile,
      );
      setUploadedSource(result.source);
      setIndexedChunks(result.indexed_chunks);
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : String(uploadError),
      );
    } finally {
      setUploading(false);
    }
  }

  async function handleAsk() {
    if (!session || !question.trim()) {
      return;
    }

    setQuerying(true);
    setError("");
    setTrace(null);
    setTraceError("");

    try {
      const result = await askQuestion({
        question: question.trim(),
        thread_id: session.thread_id,
        request_id: crypto.randomUUID(),
        stream: false,
      });

      setAnswer(result.answer);
      setCitations(result.citations);
      setRunId(result.run_id);
      setUsage({
        inputTokens: result.input_tokens,
        outputTokens: result.output_tokens,
        totalTokens: result.total_tokens,
        cacheReadTokens:
          result.cache_read_tokens,
        contextTokens:
          result.context_tokens_est,
        latencyMs: result.latency_ms,
      });

      setTraceLoading(true);

      try {
        const traceResult = await getRunTrace(
          result.run_id,
        );
        setTrace(traceResult);
      } catch (traceLoadError) {
        setTraceError(
          traceLoadError instanceof Error
            ? traceLoadError.message
            : String(traceLoadError),
        );
      } finally {
        setTraceLoading(false);
      }
    } catch (queryError) {
      setError(
        queryError instanceof Error
          ? queryError.message
          : String(queryError),
      );
    } finally {
      setQuerying(false);
    }
  }

  function renderQueryTab() {
    return (
      <div className="ops-query-stack">
      <div className="ops-grid ops-query-grid">
        <section className="ops-panel">
          <header className="ops-panel-header">
            <div>
              <p className="ops-kicker">Ingest</p>
              <h2>Document Index</h2>
            </div>
            <Database size={20} />
          </header>

          <label className="ops-drop-zone">
            <Upload size={26} />
            <strong>
              {selectedFile
                ? selectedFile.name
                : "Select PDF"}
            </strong>
            <span>
              Parse, embed and index through the API.
            </span>
            <input
              type="file"
              accept=".pdf,application/pdf"
              onChange={handleFileChange}
            />
          </label>

          <button
            className="ops-primary-button"
            type="button"
            disabled={!selectedFile || uploading}
            onClick={handleUpload}
          >
            {uploading ? (
              <LoaderCircle
                className="ops-spin"
                size={17}
              />
            ) : (
              <Upload size={17} />
            )}
            {uploading
              ? "Indexing"
              : "Upload and index"}
          </button>

          <div className="ops-source-state">
            <FileText size={18} />
            <div>
              <strong>
                {uploadedSource ||
                  "No document indexed"}
              </strong>
              <span>
                {uploadedSource
                  ? `${indexedChunks} chunks indexed`
                  : "Upload a document to begin"}
              </span>
            </div>
          </div>
        </section>

        <section className="ops-panel">
          <header className="ops-panel-header">
            <div>
              <p className="ops-kicker">Query</p>
              <h2>Grounded Answer</h2>
            </div>
            <MessageSquare size={20} />
          </header>

          <textarea
            className="ops-question-input"
            value={question}
            onChange={(event) =>
              setQuestion(event.target.value)
            }
            placeholder="Ask a question against the indexed corpus"
            rows={5}
          />

          <div className="ops-query-actions">
            <div className="ops-thread-id">
              <span>Thread</span>
              <code>
                {session?.thread_id ?? "offline"}
              </code>
            </div>
            <button
              className="ops-send-button"
              type="button"
              disabled={
                querying ||
                !question.trim() ||
                !session
              }
              onClick={handleAsk}
            >
              {querying ? (
                <LoaderCircle
                  className="ops-spin"
                  size={17}
                />
              ) : (
                <Send size={17} />
              )}
              {querying ? "Running" : "Run query"}
            </button>
          </div>

          <article className="ops-answer">
            <div className="ops-answer-header">
              <Activity size={17} />
              <span>Response</span>
              {runId ? (
                <code>{runId.slice(0, 12)}</code>
              ) : null}
            </div>
            <p>
              {answer ||
                "The grounded answer will appear here."}
            </p>
          </article>
        </section>

        <aside className="ops-panel">
          <header className="ops-panel-header">
            <div>
              <p className="ops-kicker">Evidence</p>
              <h2>Citations</h2>
            </div>
            <FileText size={20} />
          </header>

          <div className="ops-citation-list">
            {citations.length ? (
              citations.map((citation) => (
                <article
                  className="ops-citation"
                  key={citation.citation_id}
                >
                  <code>
                    {citation.citation_id}
                  </code>
                  <div>
                    <strong>
                      {citation.source}
                    </strong>
                    <p>
                      Page {citation.page}
                    </p>
                  </div>
                </article>
              ))
            ) : (
              <div className="ops-empty-state">
                <FileText size={22} />
                <span>
                  Citations appear after a grounded
                  answer.
                </span>
              </div>
            )}
          </div>

          <div className="ops-usage-grid">
            <div>
              <span>Input</span>
              <strong>{usage.inputTokens}</strong>
            </div>
            <div>
              <span>Output</span>
              <strong>{usage.outputTokens}</strong>
            </div>
            <div>
              <span>Total</span>
              <strong>{usage.totalTokens}</strong>
            </div>
            <div>
              <span>Context</span>
              <strong>{usage.contextTokens}</strong>
            </div>
            <div>
              <span>Cache</span>
              <strong>
                {usage.cacheReadTokens}
              </strong>
            </div>
            <div>
              <span>Latency</span>
              <strong>
                {usage.latencyMs.toFixed(0)} ms
              </strong>
            </div>
          </div>
        </aside>
      </div>

        <section className="ops-trace-panel">
          <header className="ops-trace-header">
            <div>
              <p className="ops-kicker">Execution</p>
              <h2>Run Trace</h2>
            </div>
            {trace ? (
              <span>{trace.event_count} events</span>
            ) : null}
          </header>

          {traceLoading ? (
            <div className="ops-empty-state">
              <LoaderCircle
                className="ops-spin"
                size={22}
              />
              <span>Loading real trace events.</span>
            </div>
          ) : traceError ? (
            <div className="ops-empty-state">
              <AlertTriangle size={22} />
              <span>{traceError}</span>
            </div>
          ) : trace ? (
            <div className="ops-trace-list">
              {trace.events.map((event) => (
                <article
                  className="ops-trace-event"
                  key={event.event_id}
                >
                  <span
                    className={`ops-event-status ops-event-${event.status}`}
                  >
                    {event.status}
                  </span>
                  <div>
                    <strong>
                      {event.operation}
                    </strong>
                    <p>
                      {event.action || "completed"}
                    </p>
                  </div>
                  <div className="ops-event-meta">
                    <span>attempt {event.attempt}</span>
                    <span>
                      {event.duration_ms.toFixed(2)} ms
                    </span>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="ops-empty-state">
              <Workflow size={22} />
              <span>
                Run a query to load its real execution
                timeline.
              </span>
            </div>
          )}
        </section>
      </div>
    );
  }

  function renderCapabilityTab() {
    return (
      <div className="ops-tab-body">
        <div className="ops-tab-heading">
          <ActiveIcon size={24} />
          <div>
            <p className="ops-kicker">
              {activeDefinition.eyebrow}
            </p>
            <h2>{activeDefinition.label}</h2>
            <p>
              {activeDefinition.description}
            </p>
          </div>
        </div>

        <div className="ops-capability-grid">
          {activeCapabilities.length ? (
            activeCapabilities.map((capability) => (
              <article
                className="ops-capability-card"
                key={capability.capability_id}
              >
                <div>
                  <span>
                    {capability.category}
                  </span>
                  <strong>{capability.name}</strong>
                </div>
                <p>{capability.description}</p>
                <code>
                  {capability.capability_id}
                </code>
              </article>
            ))
          ) : (
            <div className="ops-empty-state">
              <Cpu size={22} />
              <span>
                No capability metadata is available.
              </span>
            </div>
          )}
        </div>

        <section className="ops-trace-placeholder">
          <div>
            <Workflow size={20} />
            <strong>Run trace</strong>
          </div>
          <p>
            Execute a capability and attach its run_id to
            render the real execution timeline.
          </p>
          <span>
            D01 establishes the shell. Later steps bind
            each tab to its real result renderer.
          </span>
        </section>
      </div>
    );
  }

  return (
    <div className="ops-shell">
      <header className="ops-topbar">
        <div className="ops-brand">
          <div className="ops-brand-mark">SL</div>
          <div>
            <p className="ops-kicker">
              Verifiable RAG Runtime
            </p>
            <h1>SourceLedger Ops Console</h1>
          </div>
        </div>

        <div className="ops-runtime-summary">
          <span
            className={`ops-status-dot ops-status-${apiStatus}`}
          />
          <div>
            <strong>{statusLabel}</strong>
            <span>{serviceName}</span>
          </div>
        </div>

        <div className="ops-infra-strip">
          <span>
            <Database size={15} />
            PostgreSQL{" "}
            {databaseReady ? "up" : "down"}
          </span>
          <span>
            <Server size={15} />
            Redis {redisReady ? "up" : "down"}
          </span>
          <span>
            <GitBranch size={15} />
            {runId
              ? runId.slice(0, 12)
              : "no run"}
          </span>
        </div>
      </header>

      {error ? (
        <div className="ops-error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="ops-layout">
        <nav className="ops-nav" aria-label="Ops console">
          {TAB_DEFINITIONS.map((tab) => {
            const Icon = tab.icon;

            return (
              <button
                className={
                  activeTab === tab.id
                    ? "ops-nav-item active"
                    : "ops-nav-item"
                }
                key={tab.id}
                type="button"
                onClick={() =>
                  setActiveTab(tab.id)
                }
              >
                <Icon size={18} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        <main className="ops-main">
          {activeTab === "query"
            ? renderQueryTab()
            : activeTab === "retrieval"
              ? <RetrievalTab />
              : activeTab === "context"
                ? <ContextTab />
                : activeTab === "resilience"
                  ? <ResilienceTab />
                  : activeTab === "security"
                    ? <SecurityTab />
                    : activeTab === "runtime"
                      ? <RuntimeTab />
                      : renderCapabilityTab()}
        </main>
      </div>

      <footer className="ops-footer">
        <span>{API_BASE_URL}</span>
        <span>
          <CheckCircle2 size={15} />
          {capabilities.length} capabilities registered
        </span>
        <span>
          <ShieldAlert size={15} />
          Untrusted retrieved content
        </span>
      </footer>
    </div>
  );
}

export default App;