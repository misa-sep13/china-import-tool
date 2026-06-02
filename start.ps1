# 中国輸入管理ツール 起動スクリプト
Write-Host "Starting China Import Tool..." -ForegroundColor Cyan

# バックエンド起動
$backend = Start-Process -FilePath "python" `
  -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload" `
  -WorkingDirectory "$PSScriptRoot\backend" `
  -PassThru -WindowStyle Normal

Write-Host "Backend started (PID: $($backend.Id)) -> http://127.0.0.1:8000" -ForegroundColor Green

Start-Sleep -Seconds 2

# フロントエンド起動
$frontend = Start-Process -FilePath "npm" `
  -ArgumentList "run dev" `
  -WorkingDirectory "$PSScriptRoot\frontend" `
  -PassThru -WindowStyle Normal

Write-Host "Frontend started (PID: $($frontend.Id)) -> http://localhost:5173" -ForegroundColor Green
Write-Host ""
Write-Host "ブラウザで http://localhost:5173 を開いてください" -ForegroundColor Yellow
Write-Host "終了するには各ウィンドウを閉じてください"
