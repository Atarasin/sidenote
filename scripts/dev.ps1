# sidenote 一键开发环境（计划 T0.1.4）：后端 FastAPI + 前端 Vite。
# 用法：scripts\dev.ps1 （Windows PowerShell 5.1+ / PowerShell 7+）
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 功能与 scripts/dev.sh 相同：Ctrl+C 同时结束前后端。

$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# 定位 Python 解释器：优先仓库 .venv（含 worktree 场景向上查找），回退系统 python
$py = $null
if (Test-Path (Join-Path $Root '.venv\Scripts\python.exe')) {
  $py = Join-Path $Root '.venv\Scripts\python.exe'
}
elseif (Test-Path (Join-Path $Root '.venv\bin\python')) {
  $py = Join-Path $Root '.venv\bin\python'
}
else {
  foreach ($name in @('python', 'python3')) {
    $cmd = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $cmd) { $py = $cmd.Source; break }
  }
}
if ([string]::IsNullOrEmpty($py)) {
  Write-Host "[dev] 未找到 Python 解释器：请先创建 $Root\.venv 或安装 Python。" -ForegroundColor Red
  exit 1
}

# npm 实际指向 npm.cmd（Windows）/ npm（Unix），先解析成完整路径再交给 Start-Process
$npm = (Get-Command npm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if ([string]::IsNullOrEmpty($npm)) {
  Write-Host '[dev] 未找到 npm：请先安装 Node.js。' -ForegroundColor Red
  exit 1
}

Write-Host "[dev] python: $py"

$ServerDir = Join-Path (Join-Path $Root 'apps') 'server'
$WebDir = Join-Path (Join-Path $Root 'apps') 'web'

$script:BackProc = $null
$script:FrontProc = $null

function Stop-DevProcess {
  param([System.Diagnostics.Process]$Proc)
  if ($null -eq $Proc -or $Proc.HasExited) { return }
  if ($PSVersionTable.Platform -eq 'Unix') {
    Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue
  }
  else {
    # taskkill /T 连同子进程（uvicorn --reload 的重载子进程、npm 的 node 子进程）一并结束
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      & taskkill.exe /PID $Proc.Id /T /F 2>$null | Out-Null
    }
    finally {
      $ErrorActionPreference = $prevEap
    }
  }
}

function Invoke-Cleanup {
  Write-Host '[dev] shutting down...'
  Stop-DevProcess $script:BackProc
  Stop-DevProcess $script:FrontProc
}

try {
  # 后端：uvicorn（端口 8787）
  $script:BackProc = Start-Process -FilePath $py `
    -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8787') `
    -WorkingDirectory $ServerDir -NoNewWindow -PassThru

  # 前端：vite dev server（端口 5173，/api 代理到 8787）
  if (-not (Test-Path (Join-Path $WebDir 'node_modules'))) {
    Write-Host '[dev] 前端依赖未安装，执行 npm install...'
    Push-Location $WebDir
    try {
      & $npm install
      if ($LASTEXITCODE -ne 0) { throw "[dev] npm install 失败（退出码 $LASTEXITCODE）" }
    }
    finally {
      Pop-Location
    }
  }
  $script:FrontProc = Start-Process -FilePath $npm -ArgumentList @('run', 'dev') `
    -WorkingDirectory $WebDir -NoNewWindow -PassThru

  Write-Host '[dev] 前端: http://localhost:5173  后端: http://127.0.0.1:8787/api/health'

  # 等两个后台进程全部退出（等价 bash 的 wait）；Ctrl+C 走 finally 清理
  Wait-Process -Id @($script:BackProc.Id, $script:FrontProc.Id) -ErrorAction SilentlyContinue
}
finally {
  Invoke-Cleanup
}
