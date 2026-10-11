import type {
  AskResponse,
  CapabilityDescriptor,
  CapabilityRunPayload,
  CapabilityRunResponse,
  HealthResponse,
  ReadinessResponse,
  SessionResponse,
  StandardAskPayload,
  StreamEvent,
  RunTraceResponse,
  StreamPayload,
  TaskStatusResponse,
  UploadResponse,
} from "./types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  "http://127.0.0.1:8000";

async function parseResponse<T>(
  response: Response,
): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(
      text || `HTTP ${response.status}`,
    );
  }

  return (await response.json()) as T;
}

export async function getHealth(): Promise<HealthResponse> {
  return parseResponse<HealthResponse>(
    await fetch(`${API_BASE_URL}/health`),
  );
}

export async function getReadiness(): Promise<ReadinessResponse> {
  return parseResponse<ReadinessResponse>(
    await fetch(`${API_BASE_URL}/ready`),
  );
}

export async function createSession(): Promise<SessionResponse> {
  return parseResponse<SessionResponse>(
    await fetch(`${API_BASE_URL}/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        user_id: "workbench-user",
        title: "SourceLedger workbench session",
      }),
    }),
  );
}

export async function uploadDocument(
  file: File,
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  return parseResponse<UploadResponse>(
    await fetch(`${API_BASE_URL}/documents/upload`, {
      method: "POST",
      body: formData,
    }),
  );
}

export async function askQuestion(
  payload: StandardAskPayload,
): Promise<AskResponse> {
  return parseResponse<AskResponse>(
    await fetch(`${API_BASE_URL}/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }),
  );
}

export async function getTaskStatus(
  runId: string,
): Promise<TaskStatusResponse> {
  return parseResponse<TaskStatusResponse>(
    await fetch(
      `${API_BASE_URL}/tasks/${encodeURIComponent(runId)}`,
    ),
  );
}

function parseSseBlock(
  block: string,
): StreamEvent | null {
  const lines = block.split("\n");
  const eventLine = lines.find((line) =>
    line.startsWith("event: "),
  );
  const dataLine = lines.find((line) =>
    line.startsWith("data: "),
  );

  if (!eventLine || !dataLine) {
    return null;
  }

  return {
    event: eventLine.slice(7).trim(),
    data: JSON.parse(
      dataLine.slice(6),
    ) as Record<string, unknown>,
  };
}

export async function streamQuestion(
  payload: StreamPayload,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/ask/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(payload),
    },
  );

  if (!response.ok || !response.body) {
    throw new Error(
      await response.text(),
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, {
      stream: true,
    });

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";

    for (const block of blocks) {
      const event = parseSseBlock(block);
      if (event) {
        onEvent(event);
      }
    }
  }

  const finalEvent = parseSseBlock(buffer);
  if (finalEvent) {
    onEvent(finalEvent);
  }
}
export async function getCapabilities(): Promise<
  CapabilityDescriptor[]
> {
  return parseResponse<CapabilityDescriptor[]>(
    await fetch(`${API_BASE_URL}/capabilities`),
  );
}

export async function runCapability(
  capabilityId: string,
  payload: CapabilityRunPayload,
): Promise<CapabilityRunResponse> {
  return parseResponse<CapabilityRunResponse>(
    await fetch(
      `${API_BASE_URL}/capabilities/${encodeURIComponent(
        capabilityId,
      )}/run`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      },
    ),
  );
}

export async function getRunTrace(
  runId: string,
): Promise<RunTraceResponse> {
  return parseResponse<RunTraceResponse>(
    await fetch(
      `${API_BASE_URL}/runs/${encodeURIComponent(
        runId,
      )}/trace`,
    ),
  );
}
