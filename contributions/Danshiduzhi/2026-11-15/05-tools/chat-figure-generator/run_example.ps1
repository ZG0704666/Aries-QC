# 示例：把三个项目生成到 .\demo_output 下
# 用法：右键“使用 PowerShell 运行”，或在 PowerShell 里执行 .\run_example.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = "python"
$out = Join-Path $root "demo_output"

Write-Host "生成器目录：$root"
Write-Host "输出目录：$out"
Write-Host ""

& $py "$root\src\cli.py" `
  --config "$root\config\项目一.json" "$root\config\项目二.json" "$root\config\项目三.json" `
  --out-root $out `
  --name "鹕安"

Write-Host ""
Write-Host "完成。检查："
Get-ChildItem $out -Recurse -Filter "*.png" | Measure-Object | ForEach-Object { "  PNG：$($_.Count) 张" }
Get-ChildItem $out -Recurse -Filter "*对话图集*.docx" | ForEach-Object { "  DOCX：$($_.Name)" }
