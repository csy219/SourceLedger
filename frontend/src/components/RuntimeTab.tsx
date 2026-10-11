import {
  AlertTriangle,
  CheckCircle2,
  Database,
  GitBranch,
  LoaderCircle,
  RotateCcw,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import {
  getRunTrace,
  runCapability,
} from "../api";
import type { RunTraceEvent } from "../types";

interface RuntimeOutput {
  status: string;
  run_id: string;
  first_checkpoint: number;
  second_checkpoint: number;
  versions: number[];
  recovered_node: string;
  recovered_step_count: number;
}

function TraceList({
  events,
}: {
  events: RunTraceEvent[];
}) {
  if (!events.length) {
    return (
      <div className="runtime-empty">
        <span>No trace events.</span>
      </div>
    );
  }

  return (
    <div className="runtime-trace">
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

export default function RuntimeTab() {
  const [output, setOutput] =
    useState<RuntimeOutput | null>(null);
  const [trace, setTrace] = useState<
    RunTraceEvent[]
  >([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  async function runRecovery() {
    setRunning(true);
    setError("");
    setOutput(null);
    setTrace([]);

    try {
      const response = await runCapability(
        "checkpoint_recovery",
        {
          thread_id: "runtime-tab",
          input: {},
        },
      );

      const runtimeOutput =
        response.output as unknown as RuntimeOutput;

      setOutput(runtimeOutput);

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
    <div className="ops-tab-body runtime-tab">
      <div className="ops-tab-heading">
        <Workflow size={24} />
        <div>
          <p className="ops-kicker">Execution state</p>
          <h2>Runtime Lab</h2>
          <p>
            Persist a real PostgreSQL checkpoint, restore the
            latest state and inspect the run trace.
          </p>
        </div>
      </div>

      <section className="runtime-controls">
        <div>
          <strong>Checkpoint Recovery</strong>
          <p>
            The scenario creates a run, writes a checkpoint,
            restores it and writes a second checkpoint.
          </p>
        </div>
        <button
          type="button"
          disabled={running}
          onClick={runRecovery}
        >
          {running ? (
            <LoaderCircle
              className="ops-spin"
              size={17}
            />
          ) : (
            <RotateCcw size={17} />
          )}
          {running ? "Running" : "Run recovery"}
        </button>
      </section>

      {error ? (
        <div className="ops-error-banner">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      ) : null}

      {output ? (
        <>
          <section className="runtime-flow">
            {[
              "running",
              `checkpoint v${output.first_checkpoint}`,
              "checkpoint loaded",
              output.recovered_node,
            ].map((step, index, steps) => (
              <div
                className="runtime-flow-step"
                key={`${step}-${index}`}
              >
                <span>{index + 1}</span>
                <strong>{step}</strong>
                {index < steps.length - 1 ? (
                  <i aria-hidden="true">→</i>
                ) : null}
              </div>
            ))}
          </section>

          <section className="runtime-summary">
            <div>
              <span>Run ID</span>
              <strong>{output.run_id}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{output.status}</strong>
            </div>
            <div>
              <span>Checkpoint versions</span>
              <strong>
                {output.versions.join(", ")}
              </strong>
            </div>
            <div>
              <span>Recovered node</span>
              <strong>{output.recovered_node}</strong>
            </div>
            <div>
              <span>Recovered step</span>
              <strong>
                {output.recovered_step_count}
              </strong>
            </div>
            <div>
              <span>Trace events</span>
              <strong>{trace.length}</strong>
            </div>
          </section>

          <div className="runtime-grid">
            <section className="runtime-panel">
              <header>
                <Database size={17} />
                <strong>Checkpoints</strong>
              </header>
              <div className="runtime-checkpoints">
                <article>
                  <CheckCircle2 size={17} />
                  <div>
                    <strong>
                      v{output.first_checkpoint}
                    </strong>
                    <span>before_crash</span>
                  </div>
                </article>
                <article>
                  <CheckCircle2 size={17} />
                  <div>
                    <strong>
                      v{output.second_checkpoint}
                    </strong>
                    <span>recovered</span>
                  </div>
                </article>
              </div>
            </section>

            <section className="runtime-panel">
              <header>
                <GitBranch size={17} />
                <strong>Tool Calls</strong>
              </header>
              <div className="runtime-empty">
                <span>
                  No tool calls were registered for this
                  recovery scenario.
                </span>
              </div>
            </section>
          </div>

          <section className="runtime-panel">
            <header>
              <Workflow size={17} />
              <strong>Runtime Trace</strong>
              <span>{trace.length}</span>
            </header>
            <TraceList events={trace} />
          </section>
        </>
      ) : (
        <div className="runtime-empty runtime-main-empty">
          <Workflow size={24} />
          <span>
            Run recovery to inspect state, checkpoints and
            trace.
          </span>
        </div>
      )}
    </div>
  );
}