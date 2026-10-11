import {
  AlertTriangle,
  Clock3,
  LoaderCircle,
  Lock,
  Network,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import {
  getRunTrace,
  runCapability,
} from "../api";
import type { RunTraceEvent } from "../types";

interface ScenarioDefinition {
  id: string;
  name: string;
  description: string;
  defaultInput: Record<string, unknown>;
  icon: typeof Clock3;
}

const SCENARIOS: ScenarioDefinition[] = [
  {
    id: "retry_backoff",
    name: "Retry and Backoff",
    description:
      "Retry temporary failures with bounded backoff and attempt tracking.",
    defaultInput: {
      succeed_on_attempt: 2,
      max_attempts: 3,
      base_delay_ms: 10,
      max_delay_ms: 100,
      jitter_ratio: 0,
    },
    icon: RefreshCw,
  },
  {
    id: "fallback_chain",
    name: "Fallback Chain",
    description:
      "Move to an ordered fallback when the primary operation is unavailable.",
    defaultInput: {
      fallback_success: "bm25_only",
    },
    icon: Network,
  },
  {
    id: "circuit_breaker",
    name: "Circuit Breaker",
    description:
      "Open after repeated failures, reject calls and recover after cooldown.",
    defaultInput: {
      failure_threshold: 2,
      recovery_timeout_ms: 50,
    },
    icon: ShieldCheck,
  },
  {
    id: "rate_limit",
    name: "Rate Limit",
    description:
      "Compare local and Redis sliding-window rate limiter decisions.",
    defaultInput: {
      limit: 2,
      window_seconds: 60,
      request_count: 3,
    },
    icon: Clock3,
  },
  {
    id: "distributed_lock",
    name: "Distributed Lock",
    description:
      "Acquire, reject and release a real Redis distributed lock.",
    defaultInput: {
      ttl_ms: 500,
    },
    icon: Lock,
  },
  {
    id: "idempotency",
    name: "Idempotency",
    description:
      "Execute one request key twice and replay the stored result.",
    defaultInput: {
      key: "",
    },
    icon: ShieldCheck,
  },
  {
    id: "checkpoint_recovery",
    name: "Checkpoint Recovery",
    description:
      "Persist a real PostgreSQL checkpoint and restore the latest state.",
    defaultInput: {},
    icon: Workflow,
  },
];

function TraceList({
  events,
}: {
  events: RunTraceEvent[];
}) {
  if (!events.length) {
    return (
      <div className="resilience-empty">
        <span>No trace events.</span>
      </div>
    );
  }

  return (
    <div className="resilience-trace">
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
          <span>attempt {event.attempt}</span>
          <span>{event.duration_ms.toFixed(2)} ms</span>
        </article>
      ))}
    </div>
  );
}

function ScenarioCard({
  scenario,
}: {
  scenario: ScenarioDefinition;
}) {
  const Icon = scenario.icon;
  const [inputText, setInputText] = useState(
    JSON.stringify(
      scenario.defaultInput,
      null,
      2,
    ),
  );
  const [output, setOutput] = useState<
    Record<string, unknown> | null
  >(null);
  const [trace, setTrace] = useState<
    RunTraceEvent[]
  >([]);
  const [runId, setRunId] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function runScenario() {
    setRunning(true);
    setError("");
    setOutput(null);
    setTrace([]);
    setRunId("");

    try {
      const parsed = JSON.parse(
        inputText || "{}",
      ) as Record<string, unknown>;

      if (
        scenario.id === "idempotency" &&
        !parsed.key
      ) {
        parsed.key = `d05:${crypto.randomUUID()}`;
      }

      const response = await runCapability(
        scenario.id,
        {
          thread_id: "resilience-tab",
          input: parsed,
        },
      );

      setOutput(response.output);
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

  return (
    <article className="resilience-card">
      <header>
        <Icon size={19} />
        <div>
          <strong>{scenario.name}</strong>
          <p>{scenario.description}</p>
        </div>
      </header>

      <label>
        <span>Input</span>
        <textarea
          value={inputText}
          rows={7}
          onChange={(event) =>
            setInputText(event.target.value)
          }
        />
      </label>

      <div className="resilience-actions">
        <code>{scenario.id}</code>
        <button
          type="button"
          disabled={running}
          onClick={runScenario}
        >
          {running ? (
            <LoaderCircle
              className="ops-spin"
              size={16}
            />
          ) : (
            <Icon size={16} />
          )}
          {running ? "Running" : "Run"}
        </button>
      </div>

      {error ? (
        <div className="resilience-error">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      ) : null}

      {output ? (
        <>
          <div className="resilience-run-meta">
            <span>
              run: {runId.slice(0, 12)}
            </span>
            <span>{trace.length} events</span>
          </div>
          <pre className="resilience-output">
            {JSON.stringify(output, null, 2)}
          </pre>
        </>
      ) : null}

      <TraceList events={trace} />
    </article>
  );
}

export default function ResilienceTab() {
  return (
    <div className="ops-tab-body resilience-tab">
      <div className="ops-tab-heading">
        <RefreshCw size={24} />
        <div>
          <p className="ops-kicker">Failure control</p>
          <h2>Resilience Lab</h2>
          <p>
            Run real retry, fallback, breaker, rate limit,
            lock, idempotency and checkpoint scenarios.
          </p>
        </div>
      </div>

      <div className="resilience-grid">
        {SCENARIOS.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            scenario={scenario}
          />
        ))}
      </div>
    </div>
  );
}