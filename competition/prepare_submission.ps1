# PaperLens 参赛提交包准备脚本
# 用法：
#   .\prepare_submission.ps1 -TeamName "XX大学-知研队" -Contact "13800000000"
# 说明：只做“收集 + 校验 + 打包”，不会伪造任何材料。PPT/视频/证据需要你手动放入。

param(
    [string]$WorkName = "PaperLens知研",
    [Parameter(Mandatory = $true)][string]$TeamName,
    [Parameter(Mandatory = $true)][string]$Contact,
    [string]$Version = "v1.0.0",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $PSScriptRoot "_submission"
$project = Join-Path $stage "project\paperlens-ai"

if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
$dirs = @("ppt", "project", "video", "codearts_proof", "readme")
foreach ($dir in $dirs) { New-Item -ItemType Directory -Force -Path (Join-Path $stage $dir) | Out-Null }
New-Item -ItemType Directory -Force -Path $project | Out-Null

Write-Host "Collecting backend..." -ForegroundColor Cyan
robocopy "$root\backend" "$project\backend" /E /XD "__pycache__" ".venv" "data" /XF "*.db" "*.db-wal" "*.db-shm" /NFL /NDL /NJH /NJS /NP | Out-Null

Write-Host "Collecting frontend..." -ForegroundColor Cyan
robocopy "$root\frontend" "$project\frontend" /E /XD "node_modules" "dist" ".vite" /NFL /NDL /NJH /NJS /NP | Out-Null

Write-Host "Collecting QA + deploy..." -ForegroundColor Cyan
robocopy "$root\qa" "$project\qa" /E /XD "node_modules" "screenshots" /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy "$root\deploy" "$project\deploy" /E /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy "$root\docs" "$project\docs" /E /NFL /NDL /NJH /NJS /NP | Out-Null

foreach ($file in @("Dockerfile", "docker-compose.yml", ".env.example", ".gitignore", "README.md")) {
    $source = Join-Path $root $file
    if (Test-Path $source) { Copy-Item $source -Destination $project -Force }
}

# 占位说明，避免评委打开空目录
$pptNote = @"
# 作品介绍 PPT / PDF

请放入：
- PaperLens_作品介绍.pdf（或 .pptx）

内容要求：场景背景、功能架构、核心亮点、码道应用说明。
可用 ../competition/03_赛题材料提示词.md 让码道生成文案。
"@
$pptNote | Set-Content -Encoding UTF8 (Join-Path $stage "ppt\README.md")

$videoNote = @"
# 功能演示视频

请放入：
- PaperLens_功能演示.mp4（≤3 分钟）
或
- 视频链接.txt（可公开访问的在线视频地址）

建议展示：上传 → 提问 → 引用回跳 → 高亮恢复 → 多论文 → 导出。
"@
$videoNote | Set-Content -Encoding UTF8 (Join-Path $stage "video\README.md")

$proofNote = @"
# 码道使用证明

请按五类放入真实截图：
01_环境搭建、02_代码生成、03_调试排错、04_测试验收、05_文档与材料

同时提供：
- README.md（证据索引与时间线）
- prompt_log.md（真实 Prompt 摘要）

禁止伪造；详见 ../competition/04_执行手册与证据清单.md。
"@
$proofNote | Set-Content -Encoding UTF8 (Join-Path $stage "codearts_proof\README.md")

$readmeNote = @"
# 作品说明文档（待完善）

请按赛题要求放入 PDF，覆盖：
1. 环境依赖说明与一键安装脚本
2. 部署运行步骤说明
3. 额外使用的开源组件说明
4. 码道在项目开发中的应用总结

可用 ../competition/03_赛题材料提示词.md 的第 1 节生成。
"@
$readmeNote | Set-Content -Encoding UTF8 (Join-Path $stage "readme\作品说明文档_待完善.md")

$submitNote = @"
PaperLens AI · 知研 提交说明

作品名称：$WorkName
队伍名称：$TeamName
版本号：$Version
联系方式：$Contact

在线演示地址：【待填】
测试账号：【待填】
启动命令：见 project/paperlens-ai/README.md
已知限制：扫描版 PDF 需 OCR；未配置模型 Key 时为本地抽取模式。
"@
$submitNote | Set-Content -Encoding UTF8 (Join-Path $stage "提交说明.txt")

# ---------------- 校验 ----------------
$problems = New-Object System.Collections.Generic.List[string]
function Test-Required($path, $label) {
    if (-not (Test-Path $path)) { $problems.Add("缺少 $label") }
}

Test-Required (Join-Path $project "backend\run.py") "后端源码"
Test-Required (Join-Path $project "frontend\package.json") "前端源码"
Test-Required (Join-Path $project "README.md") "项目 README"
Test-Required (Join-Path $project "Dockerfile") "Dockerfile"

$pptFiles = Get-ChildItem (Join-Path $stage "ppt") -File | Where-Object { $_.Extension -in ".pdf", ".pptx", ".ppt" }
if ($pptFiles.Count -eq 0) { $problems.Add("ppt/ 中没有 PDF/PPTX") }

$videoFiles = Get-ChildItem (Join-Path $stage "video") -File | Where-Object { $_.Extension -in ".mp4", ".mov", ".mkv" }
$videoLink = Get-ChildItem (Join-Path $stage "video") -File -Filter "*链接*.txt" -ErrorAction SilentlyContinue
if ($videoFiles.Count -eq 0 -and -not $videoLink) { $problems.Add("video/ 中没有视频文件或 视频链接.txt") }

$proofImages = Get-ChildItem (Join-Path $stage "codearts_proof") -Recurse -File -Include *.png, *.jpg, *.jpeg -ErrorAction SilentlyContinue
if ($proofImages.Count -lt 5) { $problems.Add("codearts_proof/ 截图少于 5 张（当前 $($proofImages.Count)）") }

$readmeDocs = Get-ChildItem (Join-Path $stage "readme") -File | Where-Object { $_.Extension -in ".pdf", ".docx" }
if ($readmeDocs.Count -eq 0) { $problems.Add("readme/ 中没有作品说明文档 PDF/DOCX") }

# 敏感文件检查
$sensitive = Get-ChildItem $stage -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq ".env" -or $_.Extension -in ".db", ".key", ".pem" }
if ($sensitive.Count -gt 0) { $problems.Add("发现敏感文件：" + (($sensitive | ForEach-Object { $_.FullName }) -join "; ")) }

Write-Host ""
if ($problems.Count -gt 0) {
    Write-Host "提交包尚未完整（这是正常的，先补齐材料）：" -ForegroundColor Yellow
    $problems | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
} else {
    Write-Host "提交包结构检查通过。" -ForegroundColor Green
}

if ($SkipZip) {
    Write-Host "已生成暂存目录：$stage" -ForegroundColor Cyan
    exit 0
}

$name = $WorkName + "_" + $TeamName + "_" + $Version + "_" + $Contact
$zipPath = Join-Path $PSScriptRoot ($name + ".zip")
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -Force
Write-Host "已生成：$zipPath" -ForegroundColor Green
Write-Host "请打开压缩包确认第一层是 ppt/ project/ video/ codearts_proof/ readme/。" -ForegroundColor Cyan
