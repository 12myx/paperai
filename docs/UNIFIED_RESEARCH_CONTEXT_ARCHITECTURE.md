# Unified Research Context Architecture

> 实现对应代码：`backend/app/services/research_context.py`、`backend/app/services/tools.py`、`backend/app/services/agent.py`、`frontend/src/components/Chat.tsx`  
> 原则：真实资源、用户级隔离、按需检索、引用可追溯；没有视觉模型时不伪造视觉结论。

## 1. 数据流

```text
ChatStreamRequest
  message / scope_type / scope_ids / project_id
  knowledge_ids / image_ids / artifact_ids / exclude_ids
        |
        v
resolve_scope()                    papers (权限内)
        |
        v
resolve_research_context()         UnifiedResearchContext
  - project + project items/notes
  - explicit knowledge / project knowledge
  - question-relevant knowledge
  - explicit/project/question images
  - explicit/project/question artifacts
  - paper titles
        |
        +--> model: context.prompt_block() in system prompt
        |          + TOOL_SPECS (27 tools)
        |
        +--> local: deterministic tool routing
                   search_knowledge / get_project_context
                   search_images / read_image / analyze_image
                   list_artifacts / check_artifact / generate_artifact
                   retrieve_chunks / summarize_paper ...
        |
        v
ToolRunner
  _register() -> unified citations
  _guard() -> pending writes for UI confirmation
        |
        v
SSE steps / citations / answer
        |
        +--> Evidence harvest (source_type=knowledge/image/artifact/project)
        +--> Chat source cards -> focus URLs
```

## 2. Resource resolver

`UnifiedResearchContext` carries:

- `project` / `project_items` / `project_notes`
- `knowledge` + `knowledge_scores`
- `images` (Figure rows)
- `artifacts` (AcademicArtifact rows)
- `paper_titles` for knowledge/image provenance
- `excluded_ids`

Every query constrains `user_id`. Project is fetched only when `Project.user_id == user.id`. Project references are filtered by the project id. Explicit resource lists are intersected with the current user's rows. Foreign IDs are silently omitted, not trusted.

Project resources use the existing `ProjectItem` table:

```text
paper / knowledge / image|figure / artifact / note
```

No new association table was needed.

## 3. Retrieval

- Papers: existing `rag.search` chunk retrieval and `Paper` tables.
- Knowledge: existing `knowledge.hybrid_search` (BM25 + character n-gram cosine); project filter; score threshold.
- Images: `Figure` caption/note/table text search; project link via ProjectItem; explicit IDs.
- Artifacts: `AcademicArtifact` title/content search; project link via ProjectItem/scope_ids; explicit IDs.
- Context budget: at most 6 knowledge, 6 images, 6 artifacts, 7000 chars in the prompt block; no full-database dump.

## 4. Evidence

No new table. Existing `Evidence` fields are reused:

| Resource | source_type | source_id | paper_id | quote |
| --- | --- | --- | --- | --- |
| Knowledge | knowledge | KnowledgeItem.id | source paper if any | note content |
| Image | image | Figure.id | Figure.paper_id | caption/note |
| Artifact | artifact | AcademicArtifact.id | null | artifact excerpt |
| Project | project | Project.id | null | goal/description |

`harvest_citations` creates resource-specific evidence and stores answer provenance in `meta.answer_source_type/source_id`. A resource is never marked verified merely because its text resembles a paper; verification still requires a real chunk match.

## 5. Tools

Added tools:

```text
search_knowledge, read_knowledge
get_project_context, search_project_resources
search_images, read_image, analyze_image
list_artifacts, read_artifact, generate_artifact, check_artifact, export_artifact
```

Write tools:

- `generate_artifact` and `export_artifact` are guarded with the existing pending-action flow.
- Existing `save_knowledge` now accepts `project_id`, after project ownership validation.

## 6. Image path

`read_image` uses `storage.abs_path` after ownership check, reads real bytes, checks dimensions/hash/size. `analyze_image` checks the current model capability. The current DeepSeek text client has no image input; the tool returns an explicit capability limitation. It never pretends that a caption is pixel understanding.

## 7. Frontend

- Chat source cards display resource type and route to:
  - `/app/knowledge?focus=<id>`
  - `/app/figures?focus=<id>`
  - `/app/artifacts?focus=<id>`
  - `/app/projects?project=<id>`
- Knowledge/Figures/Artifacts pages consume `focus` to open the selected resource.
- The existing project scope remains; explicit backend IDs are available for future selectors.
- No new global state manager was introduced.

## 8. Permission boundaries

- `ToolRunner._project`, `_knowledge`, `_artifact`, `_paper`, `_figure` all check ownership.
- `_paper` also enforces paper scope.
- Image files are served by `/api/figures/{id}/image`, which checks ownership.
- Foreign IDs supplied through chat are ignored by the resolver; tools raise 404/error rather than reading them.
- No client-supplied `user_id` is trusted.

## 9. Known architectural gaps

- Explicit resource selection exists in the backend request schema but not as a complete frontend picker.
- The model tool loop is implemented but not validated with a paid/real model in this environment.
- Visual Provider interface is explicit but no provider is configured.
- No distributed cache; context is resolved per request.
