# UPLOAD-UX-02 修复报告

> 日期：2026-11-06  
> 任务：修复 U1 / U2  
> 范围：仅前端上传体验；未改后端、未改数据库、未提交、未推送。

## 1. 修复摘要

| 缺陷 | 状态 | 说明 |
| --- | --- | --- |
| U1 批量上传后研究空间统计不刷新 | **已修复** | 统一 usage 变更事件 + Shell 防抖/取消旧请求 |
| U2 部分失败被成功提示掩盖 | **已修复** | 批次 success/failed/skipped 统计、文件级结果、持久结果、失败重试 |
| 其他问题 | 记录 3 项 | 见第 7 节，不扩大本轮修复范围 |

本轮未修改后端；没有新增数据库字段或 migration。

## 2. 审计结论（修改前）

### U1 真实根因

1. `Shell.tsx` 的 `/settings/usage` effect 只依赖 `location.pathname`。上传、删除、重新解析都不会改变 pathname，因此 Sidebar 不刷新。
2. Uploader 上传完成后只调用 Home/Library 自己的 `refreshLibrary` / `refresh`，没有通知 Shell。
3. Library 删除论文、重新解析也没有通知 Shell。
4. usage 请求没有取消/序列控制；快速切换页面时旧请求可能覆盖新数据；组件卸载后仍可能 setState。

测试报告中的“可能原因”基本正确，但当前代码还多存在“无统一通知机制”和“无请求竞态保护”两点。

### U2 真实根因

1. Uploader 的 Phase 只有 waiting/uploading/parsing/done/error/duplicate，**没有 skipped**；非 PDF/超限文件在进入批次前就被过滤，只单独 toast，无法进入批次统计。
2. 批量重复文件被计入 `failedCount`，重复被错误地当成失败。
3. `completed.length > 0` 时就会调用 `onUploaded`，Home 立即关闭上传面板；失败/跳过文件的结果和原因随组件卸载丢失。
4. 完成 toast 只显示成功，不显示失败/跳过数量；失败原因只存在于 item 内部。
5. 没有失败重试入口；后端已有 `POST /papers/{id}/reprocess`，但前端未使用。
6. 文件级错误直接使用原始 error；缺少路径/长度清理。

## 3. 修改文件

| 文件 | 修改目的 |
| --- | --- |
| `frontend/src/lib/events.ts` | 新增 `USAGE_CHANGED_EVENT`、`UPLOAD_RESULT_EVENT` 和通知函数 |
| `frontend/src/components/Shell.tsx` | usage 可被事件触发；防抖、AbortController、序列号防旧响应覆盖；挂载全局上传结果提示 |
| `frontend/src/components/Uploader.tsx` | 批次状态、success/failed/skipped、文件级结果、持久结果、失败重试、安全错误文本 |
| `frontend/src/pages/Home.tsx` | 上传完成刷新列表；只有全部成功才关闭上传面板 |
| `frontend/src/pages/Library.tsx` | 批量结果刷新列表；删除/重新解析通知 usage |
| `frontend/src/styles/base.css` | 批次结果、结果横幅、重试按钮样式 |

无后端文件修改。

## 4. 实现细节

### 4.1 U1 数据刷新

- Uploader 在批次成功数 > 0 时调用 `notifyUsageChanged()`。
- Library 删除论文、重新解析后调用 `notifyUsageChanged()`。
- Shell 监听事件，120ms 防抖后重新请求 `/settings/usage`。
- 每次加载使用递增序列号；新请求会 abort 旧请求；旧响应无法覆盖新状态。
- 组件卸载时 abort 未完成请求。
- 不刷新整个 Shell，不重载页面。

### 4.2 U2 批次结果

新增 `UploadBatchResult`：

```ts
{ success: number; failed: number; skipped: number; items: UploadResultItem[]; at: number }
```

状态映射：

- `done` → success
- `error` → failed
- `duplicate` / `skipped`（非 PDF、超限）→ skipped
- 等待/上传/解析中 → 不计入最终统计

批次完成后：

- toast 显示“本批次上传完成：成功 N，失败 M，跳过 K”
- 面板显示同样统计
- 只有 `failed === 0 && skipped === 0` 才调用 `onUploaded` 关闭面板
- 任何失败/跳过时面板保留，并显示文件级原因

### 4.3 失败信息保留

- 最终结果写入 `localStorage`：`paperlens.upload.lastResult`
- 广播 `UPLOAD_RESULT_EVENT`
- Shell 全局 `UploadResultNotice` 显示“上次上传：成功/失败/跳过”
- 点击“查看结果”打开文件级表格
- 面板关闭、页面切换后仍可查看

错误文本会清理本地绝对路径、压缩空白、截断 220 字符，不暴露堆栈或服务器路径。

### 4.4 重新处理

- 解析失败的 item 有 `paper.id`：调用 `/papers/{id}/reprocess`，等待 ready/failed。
- 上传阶段失败、没有 paper 记录的 item：显示“重新选择”，使用文件选择器重新选文件。
- 批次结果中的失败行也提供“重新解析”（仅当有 paperId）。
- 已经成功的 paper 不会重新上传或重新解析。
- 后端去重规则未修改。

## 5. 测试结果

### 5.1 命令

```text
cd backend
python -m pytest tests -q -p no:cacheprovider

cd ../frontend
npm run build

cd ../qa
QA_EMAIL=... QA_PASSWORD=... node run.mjs

# 独立 API 全流程
python %TEMP%\paperlens_flow_test.py

# U1 / U2 专项（临时 Playwright 脚本）
node %TEMP%\paperlens_u1_test.cjs
node %TEMP%\paperlens_u2_test.cjs
```

### 5.2 结果

| 测试 | 结果 |
| --- | --- |
| 后端 pytest | **80 passed** |
| 浏览器 E2E | **38 / 38 passed，0 console/page error** |
| 独立 API | **88 / 88 passed** |
| 前端构建 | 通过 |
| U1 上传两篇 | usage **2** |
| U1 删除一篇 | usage **1** |
| U1 连续两批 | usage **1 → 2** |
| U2 全部成功 | 成功 2 / 失败 0 / 跳过 0 |
| U2 部分失败 | 成功 1 / 失败 1 / 跳过 0；失败原因正确 |
| U2 全部失败 | 成功 0 / 失败 2 / 跳过 0 |
| U2 重复混合 | 成功 1 / 失败 0 / 跳过 1 |
| U2 单文件成功 | 成功 1 / 失败 0 / 跳过 0 |
| U2 单文件损坏 | 成功 0 / 失败 1 / 跳过 0 |
| U2 结果持久化 | 面板关闭后 banner 仍显示；2 行结果；失败行可重试 |
| U2 失败重试 | 只发出 **1** 次 `/reprocess`；资料库论文数保持 2，不重复上传成功文件 |

截图：

- `qa/screenshots/20-u1-usage-fixed.png`
- `qa/screenshots/20-u2-all-success.png`
- `qa/screenshots/20-u2-all-failed.png`
- `qa/screenshots/20-u2-duplicate.png`
- `qa/screenshots/20-u2-partial-result.png`

说明：重复文件测试中浏览器控制台有 1 条预期的 409 资源错误，这是后端去重语义；不是未捕获异常。

## 6. 缺陷状态

| 缺陷 | 状态 | 证据 |
| --- | --- | --- |
| U1 | **已修复** | 上传 2 → usage 2；删除 1 → usage 1；连续批次 1→2 |
| U2 | **已修复** | A/B/C/D/E/F 场景全部通过；结果持久化与失败重试通过 |

## 7. 风险与遗留

1. **非 PDF/超大文件跳过**：代码已支持 skipped，但本轮没有做专门浏览器场景；后台仍按 PDF-only 校验。
2. **上传阶段失败（没有 paper 记录）**：只能重新选择文件，不能从 batch result 中直接恢复原始 File（浏览器不允许持久化 File 字节）。
3. **结果 banner 重试**：只负责重新排队，不在 banner 内实时轮询解析状态；面板内重试会轮询。
4. **重复文件**：批量中按现有规则跳过；单文件仍弹“仍然上传”确认。没有改变业务规则。
5. **并发上传**：上传并发为 2；后端解析仍串行。没有做 10+ 文件压力测试。
6. **usage 事件**：进行了防抖/abort；没有做人为慢网络下的自动化竞态注入。
7. **通知区域**：结果 banner 是轻量级，不是完整通知中心；未做移动端专项截图。
8. 未覆盖 Docker/Railway/PostgreSQL；本轮为前端修复。

## 8. Git 状态

修改前 HEAD：

```text
d8e415e
```

修改后 HEAD 仍为：

```text
d8e415e
```

**未 commit、未 push。**

`git status --short`：

```text
 M frontend/src/components/Shell.tsx
 M frontend/src/components/Uploader.tsx
 M frontend/src/pages/Home.tsx
 M frontend/src/pages/Library.tsx
 M frontend/src/styles/base.css
?? frontend/src/lib/events.ts
?? docs/UPLOAD_UX_FIX_REPORT_2026-11-06.md
```

`git diff --stat`：

```text
 frontend/src/components/Shell.tsx    |  44 ++++++-
 frontend/src/components/Uploader.tsx | 312 ++++++++++++++++++++++++++++++++++-------
 frontend/src/pages/Home.tsx          |   6 +-
 frontend/src/pages/Library.tsx       |   6 +-
 frontend/src/styles/base.css         |  17 ++
 5 files changed, 313 insertions(+), 72 deletions(-)
```

完整 diff 可用：

```text
git diff -- frontend/src/components/Shell.tsx frontend/src/components/Uploader.tsx   frontend/src/pages/Home.tsx frontend/src/pages/Library.tsx frontend/src/styles/base.css
git diff --no-index /dev/null frontend/src/lib/events.ts
```

## 9. 结论

U1、U2 均通过真实浏览器场景验证：

- 上传后 Sidebar 统计刷新；
- 删除后统计刷新；
- 连续批次统计正确；
- 全部成功、部分失败、全部失败、重复混合、单文件成功/失败均显示正确统计；
- 失败原因可见；
- 面板关闭后结果仍可查看；
- 失败文件可重新处理，成功文件不重复上传。

原有后端 80 测试、38 步浏览器 E2E、88 项 API 全流程均通过。未提交、未推送。
