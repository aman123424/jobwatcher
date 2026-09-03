<#
.SYNOPSIS
  One-command deploy for jobwatcher - backend (Lambda) and frontend
  (S3 + CloudFront) - replacing the old manual "upload a zip in the
  Lambda console, drag files into the S3 console, click Invalidate"
  workflow with a single script.

.DESCRIPTION
  1. Backend: installs Lambda-target dependencies into backend/.deploy/package/
     (only when requirements-lambda.txt has changed since the last run -
     otherwise reuses the existing install, which is the slow part),
     copies the current backend source files on top, zips it, and
     uploads via `aws lambda update-function-code`.
  2. Frontend: runs `npm run build`, syncs frontend/dist/ to the S3
     bucket (deleting anything no longer in dist/), then creates a
     CloudFront invalidation so visitors don't keep getting a stale
     cached index.html.

  Requires: AWS CLI configured (`aws configure`) as the `jobwatcher`
  IAM user, Python 3.12 on PATH, Node/npm on PATH.

.PARAMETER SkipBackend
  Deploy only the frontend.

.PARAMETER SkipFrontend
  Deploy only the backend.

.EXAMPLE
  .\deploy.ps1                  # deploy both
  .\deploy.ps1 -SkipFrontend    # backend only
  .\deploy.ps1 -SkipBackend     # frontend only
#>

param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

# --- Fixed resource identifiers (see project memory for how these were found) ---
$LambdaFunction = "jobwatcher-backend"
$AwsRegion = "ap-south-1"
$S3Bucket = "s3://jobwatcher-frontend-amankulwal"
$CloudFrontDistId = "E6VN3AWR1IL8V"

$BackendFiles = @(
    "api.py", "auth.py", "auth_routes.py", "companies.py", "db.py",
    "fetchers.py", "ingest.py", "job_dates.py", "lambda_handler.py",
    "main.py", "models.py", "scoring.py", "state.py"
)

# --- Paths ---
$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$DeployDir = Join-Path $Backend ".deploy"
$PackageDir = Join-Path $DeployDir "package"
$ZipPath = Join-Path $DeployDir "jobwatcher-lambda.zip"
$ReqFile = Join-Path $Backend "requirements-lambda.txt"
$HashMarker = Join-Path $PackageDir ".requirements-hash"

# `aws` might not be on THIS process's PATH yet even if it's genuinely
# installed (a freshly-installed PATH entry only takes effect in a NEW
# terminal) - fall back to the default install location rather than
# failing with a confusing "not recognized" error.
$Aws = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $Aws) {
    $Aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
}
if (-not (Test-Path $Aws)) {
    throw "AWS CLI not found on PATH or at the default install location. Install it first (see README/chat history)."
}

function Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

if (-not $SkipBackend) {
    Step "Backend: preparing Lambda package"

    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
    $ReqHash = (Get-FileHash $ReqFile -Algorithm SHA256).Hash
    $NeedsInstall = $true
    if (Test-Path $HashMarker) {
        $PrevHash = (Get-Content $HashMarker -Raw).Trim()
        if ($PrevHash -eq $ReqHash) { $NeedsInstall = $false }
    }

    if ($NeedsInstall) {
        # Only re-runs when requirements-lambda.txt actually changed -
        # this is the slow step (real dependency download+extract), so
        # skipping it on every ordinary code-only deploy is the whole
        # point of caching package/ here instead of rebuilding from
        # scratch (like the old scratchpad-based manual flow did).
        Write-Host "requirements-lambda.txt changed (or first run) - installing dependencies..."
        Get-ChildItem $PackageDir -Exclude ".requirements-hash" | Remove-Item -Recurse -Force
        python -m pip install -r $ReqFile `
            --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 `
            --implementation cp --target $PackageDir
        if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
        Set-Content -Path $HashMarker -Value $ReqHash -NoNewline
    } else {
        Write-Host "Dependencies unchanged - reusing existing install."
    }

    Write-Host "Copying current backend source files into package/..."
    foreach ($f in $BackendFiles) {
        Copy-Item (Join-Path $Backend $f) (Join-Path $PackageDir $f) -Force
    }

    Write-Host "Zipping..."
    python (Join-Path $DeployDir "build_zip.py") $PackageDir $ZipPath
    if ($LASTEXITCODE -ne 0) { throw "build_zip.py failed" }

    Step "Backend: uploading to Lambda ($LambdaFunction)"
    & $Aws lambda update-function-code `
        --function-name $LambdaFunction `
        --zip-file "fileb://$ZipPath" `
        --region $AwsRegion `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "lambda update-function-code failed" }

    Write-Host "Waiting for the update to finish deploying..."
    & $Aws lambda wait function-updated --function-name $LambdaFunction --region $AwsRegion
    Write-Host "Backend deployed." -ForegroundColor Green
}

if (-not $SkipFrontend) {
    Step "Frontend: building"
    Push-Location $Frontend
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
        Pop-Location
    }

    Step "Frontend: syncing dist/ to S3"
    & $Aws s3 sync (Join-Path $Frontend "dist") $S3Bucket --delete --region $AwsRegion
    if ($LASTEXITCODE -ne 0) { throw "s3 sync failed" }

    Step "Frontend: invalidating CloudFront cache"
    & $Aws cloudfront create-invalidation `
        --distribution-id $CloudFrontDistId `
        --paths "/*" `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "cloudfront create-invalidation failed" }
    Write-Host "Frontend deployed. CloudFront invalidation may take a minute or two to finish propagating." -ForegroundColor Green
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Frontend: https://jobwatcher.mykave.in"
