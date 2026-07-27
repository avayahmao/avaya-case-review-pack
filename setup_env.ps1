# ==============================================================================
# Avaya Case Review Suite — Automated Setup Script for Support Managers
# ==============================================================================
# This script sets up Antigravity Plugins, MCP Servers, Python dependencies,
# and performs initial authentication for Avaya Support Managers.
# ==============================================================================

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$UserHome = $env:USERPROFILE
$GeminiConfigDir = Join-Path $UserHome ".gemini\config"
$GeminiPluginsDir = Join-Path $GeminiConfigDir "plugins"
$GeminiToolsDir = Join-Path $UserHome ".gemini\tools\gmail"
$McpConfigFile = Join-Path $GeminiConfigDir "mcp_config.json"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Avaya Case Review Manager Suite — Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------------------------------------------
# 1. Check Python Environment
# ------------------------------------------------------------------------------
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Error "Python was not found in PATH. Please install Python 3.10+ and add it to PATH."
    exit 1
}
$PythonVersion = python --version 2>&1
Write-Host "  Found: $PythonVersion" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 2. Install Required Python Packages & Playwright Browser
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[2/6] Installing required Python libraries (mcp, playwright)..." -ForegroundColor Yellow
$env:PYTHONIOENCODING = "utf-8"
python -m pip install --upgrade pip --quiet
python -m pip install mcp playwright --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Python packages."
    exit 1
}
Write-Host "  Python packages installed successfully." -ForegroundColor Green

Write-Host "  Installing Playwright Chromium browser binary..." -ForegroundColor Yellow
playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Playwright browser installation returned non-zero code. Attempting to proceed."
} else {
    Write-Host "  Playwright Chromium installed successfully." -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# 3. Deploy Plugin Files
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[3/6] Deploying Avaya Case Review plugin files..." -ForegroundColor Yellow
$SourcePluginDir = Join-Path $ScriptDir "plugins\avaya-case-review"
$TargetPluginDir = Join-Path $GeminiPluginsDir "avaya-case-review"

if (-not (Test-Path $GeminiPluginsDir)) {
    New-Item -ItemType Directory -Path $GeminiPluginsDir -Force | Out-Null
}

if (Test-Path $SourcePluginDir) {
    Copy-Item -Path $SourcePluginDir -Destination $GeminiPluginsDir -Recurse -Force
    Write-Host "  Plugin deployed to: $TargetPluginDir" -ForegroundColor Green
} else {
    Write-Error "Source plugin directory not found at $SourcePluginDir"
    exit 1
}

# ------------------------------------------------------------------------------
# 4. Deploy Gmail & CaseToMD MCP Server Scripts
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[4/6] Deploying MCP server scripts (Gmail & CaseToMD)..." -ForegroundColor Yellow
$SourceGmailDir = Join-Path $ScriptDir "tools\gmail"
$SourceCaseToMdDir = Join-Path $ScriptDir "tools\casetomd"
$TargetCaseToMdDir = Join-Path $UserHome ".gemini\tools\casetomd"

if (-not (Test-Path $GeminiToolsDir)) {
    New-Item -ItemType Directory -Path $GeminiToolsDir -Force | Out-Null
}
if (-not (Test-Path $TargetCaseToMdDir)) {
    New-Item -ItemType Directory -Path $TargetCaseToMdDir -Force | Out-Null
}

if (Test-Path $SourceGmailDir) {
    Copy-Item -Path "$SourceGmailDir\*" -Destination $GeminiToolsDir -Recurse -Force
    Write-Host "  Gmail MCP script deployed to: $GeminiToolsDir" -ForegroundColor Green
}
if (Test-Path $SourceCaseToMdDir) {
    Copy-Item -Path "$SourceCaseToMdDir\*" -Destination $TargetCaseToMdDir -Recurse -Force
    Write-Host "  CaseToMD MCP bridge deployed to: $TargetCaseToMdDir" -ForegroundColor Green
}

# ------------------------------------------------------------------------------
# 5. Configure MCP Config (mcp_config.json) safely without overwriting other servers
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[5/6] Updating Antigravity MCP configuration ($McpConfigFile)..." -ForegroundColor Yellow

$GmailScriptPath = (Join-Path $GeminiToolsDir "gmail_mcp_server.py").Replace("\", "/")
$CaseToMdScriptPath = (Join-Path $TargetCaseToMdDir "casetomd_mcp_bridge.py").Replace("\", "/")

$ExistingConfig = @{}
if (Test-Path $McpConfigFile) {
    try {
        $ExistingJson = Get-Content -Path $McpConfigFile -Raw -Encoding UTF8
        $ExistingConfig = $ExistingJson | ConvertFrom-Json -AsHashtable
    } catch {
        $ExistingConfig = @{}
    }
}

if (-not $ExistingConfig.ContainsKey("mcpServers")) {
    $ExistingConfig["mcpServers"] = @{}
}

$ExistingConfig["mcpServers"]["gmail"] = @{
    "command" = "python"
    "args" = @($GmailScriptPath)
}
$ExistingConfig["mcpServers"]["CaseToMD"] = @{
    "command" = "python"
    "args" = @($CaseToMdScriptPath)
}

$McpJson = $ExistingConfig | ConvertTo-Json -Depth 5
Set-Content -Path $McpConfigFile -Value $McpJson -Encoding UTF8
Write-Host "  mcp_config.json updated successfully." -ForegroundColor Green

# ------------------------------------------------------------------------------
# 6. One-Time Google SSO Authentication Prompt
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "[6/6] Initializing Google SSO authentication for Gmail MCP..." -ForegroundColor Yellow
Write-Host "  A Chrome window will now open to verify your Avaya Google account session." -ForegroundColor Cyan
Write-Host "  Please complete Google SSO / MFA login if prompted, then close the browser window." -ForegroundColor Cyan

$ProfileDir = Join-Path $GeminiToolsDir "chrome_profile"
$AuthScript = @"
import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        print("Launching browser for initial SSO login...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir=r"$ProfileDir",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://script.google.com/a/macros/avaya.com/s/AKfycbwfqUGLMBppaPEtdzAC74_TeT34shpYkIVv5FMY1JjhqPDH0MXEp-WdeTOp8zmCDL0F/exec")
        print("\n--> Google login page loaded. Please complete login in the opened browser window.")
        print("--> Once you see the Apps Script response or Gmail page, close the browser window to finish setup.\n")
        
        while len(context.pages) > 0:
            await asyncio.sleep(1)

asyncio.run(run())
"@

$TempAuthPy = Join-Path $env:TEMP "init_gmail_sso.py"
Set-Content -Path $TempAuthPy -Value $AuthScript -Encoding UTF8

try {
    python $TempAuthPy
    Remove-Item $TempAuthPy -ErrorAction SilentlyContinue
} catch {
    Write-Host "  Browser session closed or completed." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  SETUP COMPLETE SUCCESSFUL!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "You are all set! Restart Antigravity to load the new plugin & MCP servers." -ForegroundColor White
Write-Host "Example prompt: 'Provide a case review for SR 1-23659220672'" -ForegroundColor White
Write-Host ""
