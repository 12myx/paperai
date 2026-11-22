export interface User {
  id: string;
  email: string;
  display_name: string;
  affiliation?: string | null;
  avatar_color: string;
  plan: string;
  created_at?: string;
  last_login_at?: string | null;
}

export interface Settings {
  theme: "light" | "dark" | "system";
  language: string;
  reading_font_size: number;
  reading_width: string;
  default_summary_mode: string;
  translation_language: string;
  translation_style: string;
  model_provider: string;
  model_base_url?: string | null;
  model_name?: string | null;
  temperature: number;
  max_tokens: number;
  onboarding_completed: boolean;
  privacy: Record<string, unknown>;
  has_api_key: boolean;
}

export interface ModelStatus {
  configured: boolean;
  provider: string;
  model?: string | null;
  base_url?: string | null;
  source?: string | null;
  mode: "generative" | "extractive";
  capabilities: Record<string, boolean>;
}

export interface Paper {
  id: string;
  title: string;
  authors?: string | null;
  year?: number | null;
  venue?: string | null;
  abstract?: string;
  language: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  status: "processing" | "ready" | "failed";
  error?: string | null;
  tags: string[];
  favorite: boolean;
  note?: string | null;
  created_at: string;
  updated_at: string;
  chunk_count?: number | null;
  doi?: string | null;
  sections?: PaperSection[];
  figures_count?: number;
  annotations_count?: number;
  chunks_count?: number;
  meta?: Record<string, unknown>;
}

export interface PaperSection {
  id: string;
  title: string;
  level: number;
  page_start: number;
  page_end: number;
  order_index?: number;
}

export interface OutlineChunk {
  id: string;
  section_id: string | null;
  section: string;
  page_start: number;
  page_end: number;
  order_index: number;
  tags: string[];
  preview: string;
}

export interface Annotation {
  id: string;
  paper_id: string;
  page: number;
  color: "yellow" | "blue" | "green" | "red" | "purple";
  quote: string;
  rects: HighlightRect[];
  note?: string | null;
  tags: string[];
  favorite: boolean;
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
}

export interface HighlightRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Figure {
  id: string;
  paper_id: string;
  paper_title?: string | null;
  page: number;
  kind: string;
  caption?: string | null;
  width: number;
  height: number;
  ai_explanation?: string | null;
  note?: string | null;
  saved: boolean;
  table_markdown?: string | null;
  image_url?: string | null;
  detected_kind?: "figure" | "table" | "page_snapshot" | "unclassified";
  quality_score?: number;
  caption_confidence?: number;
  is_page_snapshot?: boolean;
  ignored?: boolean;
  review_status?: "auto" | "confirmed" | "rejected";
  visual_status?: string;
  needs_review?: boolean;
}

export interface Collection {
  id: string;
  name: string;
  description?: string | null;
  color: string;
  paper_count: number;
  created_at: string;
}

export interface KnowledgeItem {
  id: string;
  title: string;
  content: string;
  kind: string;
  tags: string[];
  auto_tags?: string[];
  cluster_key?: string;
  cluster_label?: string;
  version?: number;
  duplicate_of?: string | null;
  search_score?: number | null;
  pinned: boolean;
  project_id?: string | null;
  source_paper_id?: string | null;
  source_paper_title?: string | null;
  source_page?: number | null;
  source_quote?: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeVersion {
  id: string;
  version: number;
  title: string;
  content: string;
  kind: string;
  tags: string[];
  note?: string | null;
  changed_fields: string[];
  created_at: string;
}

export interface KnowledgeCluster {
  key: string;
  label: string;
  count: number;
  item_ids: string[];
}

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  goal?: string | null;
  status: string;
  progress: number;
  color: string;
  counts: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface ProjectItem {
  id: string;
  project_id: string;
  kind: string;
  ref_id?: string | null;
  title: string;
  content?: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Citation {
  key: string;
  chunk_id?: string;
  paper_id?: string | null;
  paper_title: string;
  paper_year?: number | null;
  section: string;
  page: number;
  page_end?: number;
  quote: string;
  score?: number;
  kind?: string;
  tags?: string[];
  resource_type?: "paper" | "knowledge" | "image" | "artifact" | "project";
  resource_id?: string;
  resource_title?: string;
  source_paper_title?: string | null;
  image_path?: string | null;
  figure_kind?: string;
  quality_status?: string;
  quality_score?: number;
  progress?: number;
}

export interface AgentStep {
  id?: string;
  index: number;
  tool: string;
  label: string;
  status: "running" | "done" | "error" | "pending";
  summary?: string;
  input?: Record<string, unknown>;
  duration_ms?: number;
  citations?: string[];
}

export interface PendingAction {
  action_id?: string;
  expires_at?: number;
  args_digest?: string;
  tool: string;
  args: Record<string, unknown>;
  label: string;
  preview?: string;
}

export interface AgentPlanStep {
  id: string;
  title: string;
  tool?: string | null;
  depends_on?: string[];
  description?: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
}

export interface AgentSelfCheck {
  status: "pass" | "warning" | "fail";
  score: number;
  goal_completed: boolean;
  citation_count: number;
  paper_count: number;
  missing_citation_keys: string[];
  failed_steps: { index: number; tool?: string | null; error: string }[];
  issues: string[];
  warnings: string[];
  summary: string;
}

export interface AgentTask {
  id: string;
  conversation_id?: string | null;
  run_id?: string | null;
  result_message_id?: string | null;
  goal: string;
  mode: string;
  scope_type: string;
  scope_ids: string[];
  status: "queued" | "running" | "paused" | "cancelled" | "completed" | "failed";
  plan: AgentPlanStep[];
  plan_source: string;
  plan_confirmed: boolean;
  progress: number;
  current_step?: string | null;
  self_check: AgentSelfCheck | Record<string, never>;
  error?: string | null;
  provider: string;
  rerun_of?: string | null;
  created_at: string;
  updated_at: string;
  finished_at?: string | null;
}

export interface TaskDetail {
  task: AgentTask;
  steps: AgentStep[];
  result_message?: ChatMessage | null;
}

export interface ChatMessage {
  id: string;
  serverId?: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  mode?: string;
  model?: string | null;
  created_at?: string;
  steps?: AgentStep[];
  actions?: PendingAction[];
  streaming?: boolean;
  error?: string | null;
  local?: boolean;
  taskId?: string;
  plan?: AgentPlanStep[];
  planState?: "preview" | "executing" | "paused" | "completed" | "cancelled" | "failed";
  selfCheck?: AgentSelfCheck;
  runId?: string;
  resourceUsage?: ResourceUsage[];
}

export interface ResourceUsage {
  id: string;
  resource_type: string;
  resource_id: string;
  resource_name: string;
  stage: "retrieved" | "included" | "read" | "referenced";
  selection_source: string;
  retrieval_reason?: string | null;
  tool_name?: string | null;
  created_at?: string;
}

export interface Conversation {
  id: string;
  title: string;
  mode: string;
  scope_type: string;
  scope_ids: string[];
  archived: boolean;
  message_count: number;
  preview?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExportRecord {
  id: string;
  kind: string;
  title: string;
  format: string;
  filename: string;
  size_bytes: number;
  created_at: string;
  download_url: string;
}

export interface Stats {
  papers: number;
  papers_ready: number;
  pages: number;
  chunks: number;
  annotations: number;
  knowledge: number;
  figures: number;
  projects: number;
  conversations: number;
}

export interface GraphNode {
  id: string;
  type: "paper" | "knowledge" | "tag" | "method" | "dataset" | "question";
  label: string;
  meta: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type ScopeType = "all" | "papers" | "collection" | "project";

export interface ScopeSelection {
  type: ScopeType;
  ids: string[];
  label: string;
  papers?: Paper[];
}

export interface StreamEvent {
  type: "start" | "plan" | "step" | "delta" | "action" | "notice" | "paused" | "resumed" | "cancelled" | "self_check" | "done" | "error" | "answer";
  [key: string]: unknown;
}

export type EvidenceType = "direct" | "shared" | "inferred" | "hypothesis" | "insufficient" | "external";

export interface Evidence {
  id: string;
  paper_id?: string | null;
  paper_title?: string | null;
  chunk_id?: string | null;
  analysis_id?: string | null;
  page?: number | null;
  section?: string | null;
  quote: string;
  claim?: string | null;
  evidence_type: EvidenceType;
  type_label: string;
  confidence: number;
  verified: boolean;
  verification_note?: string | null;
  source_type: string;
  source_id?: string | null;
  can_locate: boolean;
  created_at: string;
  meta: Record<string, unknown>;
  source_label?: string | null;
  source_title?: string | null;
  source_excerpt?: string | null;
  source_url?: string | null;
  source_available?: boolean;
  gap_reason?: string | null;
}

export interface EvidenceStats {
  total: number;
  verified: number;
  papers: number;
  by_type: Record<string, number>;
  types: Record<string, string>;
}

export interface EvidenceTarget {
  sourceType: string;
  sourceId: string;
  label?: string;
}

export interface FacetCell {
  text: string;
  quote?: string | null;
  page?: number | null;
  section?: string | null;
  chunk_id?: string | null;
  evidence_id?: string | null;
  verified?: boolean;
}

export interface FacetRow {
  paper_id: string;
  title: string;
  year?: number | null;
  local: boolean;
  fields: Record<string, FacetCell>;
}

export interface MatrixResult {
  insight_id: string;
  rows: FacetRow[];
  dimensions: { id: string; label: string }[];
  local: boolean;
  scope: string;
  note: string;
  citations: Citation[];
}

export interface ComparabilityPair {
  paper_a: string;
  paper_b: string;
  title_a: string;
  title_b: string;
  dataset_a: string;
  dataset_b: string;
  metrics_a: string;
  metrics_b: string;
  same_dataset: boolean;
  same_metric: boolean;
  comparable: boolean;
  reason: string;
}

export interface ConflictProfile {
  paper_id: string;
  title: string;
  year?: number | null;
  method: string;
  findings: string;
  limits: string;
}

export interface ConflictItem {
  question: string;
  stance_a: string;
  stance_b: string;
  paper_a: string;
  paper_b: string;
  analysis: string;
  severity: string;
  comparable: boolean;
  evidence: Citation[];
}

export interface ConflictResult {
  insight_id: string;
  conflicts: ConflictItem[];
  comparability: ComparabilityPair[];
  profiles: ConflictProfile[];
  local: boolean;
  note: string;
  scope: string;
  citations: Citation[];
}

export interface EvolutionItem {
  paper_id: string;
  title: string;
  year?: number | null;
  method: string;
  findings: string;
  evidence_id?: string | null;
}

export interface EvolutionRelation {
  from_paper: string;
  to_paper: string;
  relation: string;
  reason: string;
  status: "explicit" | "possible" | "unknown";
  evidence: Citation[];
}

export interface EvolutionResult {
  insight_id: string;
  timeline: EvolutionItem[];
  relations: EvolutionRelation[];
  local: boolean;
  note: string;
  scope: string;
  citations: Citation[];
}

export interface GapSupport {
  paper_id: string;
  paper_title: string;
  page: number;
  section: string;
  quote: string;
  evidence_key: string;
}

export interface GapValidation {
  insight_id: string;
  claim: string;
  supports: GapSupport[];
  support_count: number;
  paper_count: number;
  strength: "multi" | "single" | "none";
  local: boolean;
  note: string;
  scope: string;
  citations: Citation[];
}

export interface IntelligenceScope {
  type: string;
  id?: string | null;
  label: string;
  paper_count: number;
  years: number[];
  year_min?: number | null;
  year_max?: number | null;
  unknown_years: number;
  boundary: string;
  external_data: boolean;
  limited?: boolean;
}

export interface LandscapeItem {
  text: string;
  quote?: string | null;
  page?: number | null;
  section?: string | null;
  paper_id: string;
  paper_title: string;
  year?: number | null;
  evidence_id?: string | null;
  evidence_key?: string | null;
  verified?: boolean;
}

export interface LandscapeData {
  overview: string;
  core_questions: LandscapeItem[];
  technical_routes: LandscapeItem[];
  key_methods: LandscapeItem[];
  representative_papers: {
    paper_id: string;
    title: string;
    year?: number | null;
    method: string;
    findings: string;
  }[];
  challenges: LandscapeItem[];
  future_directions: LandscapeItem[];
  local: boolean;
  note: string;
  scope: IntelligenceScope;
}

export interface TrendsData {
  year_counts: { year: number; count: number }[];
  unknown_year_count: number;
  keyword_trends: { year: number; terms: { term: string; count: number }[] }[];
  method_counts: { method: string; count: number }[];
  observations: string[];
  local: boolean;
  note: string;
  scope: IntelligenceScope;
}

export interface ConnectionNode {
  id: string;
  type: "paper" | "method" | "dataset" | "question" | "knowledge";
  label: string;
  meta: Record<string, unknown>;
}

export interface ConnectionEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  basis: {
    paper_id?: string;
    page?: number | null;
    quote?: string | null;
    evidence_id?: string | null;
    knowledge_id?: string | null;
  };
}

export interface ConnectionsData {
  nodes: ConnectionNode[];
  edges: ConnectionEdge[];
  counts: Record<string, number>;
  local: boolean;
  note: string;
  scope: IntelligenceScope;
}

export interface Opportunity {
  id: string;
  title: string;
  background: string;
  related_papers: { paper_id: string; title: string }[];
  evidence: LandscapeItem;
  existing_gap: string;
  why: string;
  entry_point: string;
  experiment_plan: string;
  difficulty: string;
  knowledge_needed: string;
  risks: string;
  ai_generated: boolean;
  heuristic: boolean;
}

export interface OpportunitiesData {
  opportunities: Opportunity[];
  local: boolean;
  note: string;
  scope: IntelligenceScope;
}

export interface IntelligenceReport<T> {
  id: string;
  kind: string;
  scope_type: string;
  scope_id?: string | null;
  scope_label: string;
  paper_ids: string[];
  data: T;
  citations: Citation[];
  local: boolean;
  model?: string | null;
  created_at?: string;
}

export interface IntelligenceOverview {
  scope: IntelligenceScope;
  generated_at: string;
  reports: {
    landscape: IntelligenceReport<LandscapeData>;
    trends: IntelligenceReport<TrendsData>;
    connections: IntelligenceReport<ConnectionsData>;
    opportunities: IntelligenceReport<OpportunitiesData>;
  };
}

export interface ArtifactKind {
  id: string;
  label: string;
  description: string;
}

export interface ArtifactQualityIssue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  location?: string;
}

export interface ArtifactQuality {
  id?: string;
  status: "pass" | "warning" | "fail" | "unchecked";
  score: number;
  issues: ArtifactQualityIssue[];
  summary: string;
  checked_at?: string;
}

export interface ArtifactEvidenceRow {
  key: string;
  paper_id: string;
  paper_title: string;
  page?: number | null;
  section?: string | null;
  quote: string;
  verified: boolean;
}

export interface AcademicArtifact {
  id: string;
  kind: string;
  title: string;
  scope_type: string;
  scope_ids: string[];
  paper_ids: string[];
  content: string;
  citations: Citation[];
  evidence_table: ArtifactEvidenceRow[];
  scope_statement: string;
  local: boolean;
  model?: string | null;
  quality_score: number;
  quality_status: string;
  knowledge_item_ids?: string[];
  knowledge_saved_at?: string | null;
  knowledge_saved?: boolean;
  created_at: string;
  updated_at: string;
}

export interface ArtifactPreflight {
  paper_id: string;
  title: string;
  year?: number | null;
  status: string;
  pages: number;
  chunks: number;
  chars: number;
  figures: number;
  ready: boolean;
  reason: "ready" | "scanned_pdf" | "too_little_text" | "not_parsed";
  message: string;
}

export interface ProcessingJob {
  id: string;
  paper_id: string;
  status: "queued" | "running" | "retrying" | "completed" | "failed" | "cancelled";
  stage: string;
  progress: number;
  attempts: number;
  max_attempts: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
}