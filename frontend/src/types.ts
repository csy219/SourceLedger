export type ApiStatus =
  | "checking"
  | "online"
  | "offline";

export type QueryMode = "stream" | "standard";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface ReadinessResponse {
  ready: boolean;
  database: boolean;
  redis: boolean;
  details: Record<string, string>;
}

export interface SessionResponse {
  session_id: string;
  thread_id: string;
  user_id: string;
  status: string;
}

export interface UploadResponse {
  filename: string;
  source: string;
  indexed_chunks: number;
  status: string;
}

export interface Citation {
  citation_id: string;
  source: string;
  page: number;
}

export interface AskResponse {
  run_id: string;
  thread_id: string;
  status: string;
  answer: string;
  citations: Citation[];
  context_tokens_est: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens: number;
  latency_ms: number;
  replayed: boolean;
}

export interface TaskStatusResponse {
  run_id: string;
  thread_id: string;
  status: string;
  current_node: string;
  step_count: number;
  max_steps: number;
  error: string;
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface StreamPayload {
  question: string;
  thread_id: string;
  request_id: string;
  stream: true;
}

export interface StandardAskPayload {
  question: string;
  thread_id: string;
  request_id: string;
  stream: false;
}
export type OpsTab =
  | "query"
  | "retrieval"
  | "context"
  | "resilience"
  | "security"
  | "runtime";

export interface CapabilityDescriptor {
  capability_id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  enabled: boolean;
}

export interface CapabilityRunPayload {
  run_id?: string;
  thread_id?: string;
  input: Record<string, unknown>;
}

export interface CapabilityRunResponse {
  run_id: string;
  capability_id: string;
  status: string;
  output: Record<string, unknown>;
  event_count: number;
  latency_ms: number;
}

export interface RunTraceEvent {
  event_id: string;
  run_id: string;
  timestamp: string;
  stage: string;
  operation: string;
  status: string;
  attempt: number;
  action: string;
  duration_ms: number;
  metadata: Record<string, unknown>;
}

export interface RunTraceResponse {
  run_id: string;
  event_count: number;
  events: RunTraceEvent[];
  created_at: string;
  updated_at: string;
}
