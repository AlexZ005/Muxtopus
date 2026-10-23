# pw-remote-setup.ps1 -- make a Windows PC lend its browser to e2e-slot's remote slots.
#
#   powershell -ExecutionPolicy Bypass -File pw-remote-setup.ps1 -Root D:\muxtopus-e2e -Allow 192.168.1.15 -Versions 1.62.1,1.63.0
#   powershell -ExecutionPolicy Bypass -File pw-remote-setup.ps1 -Root D:\muxtopus-e2e -Uninstall
#
# Run it as an administrator (the firewall rule and the scheduled task need
# one), with pw-remote-server.cjs beside it, on a machine that has Node (the
# LTS installer from nodejs.org; it puts node.exe on PATH). It is idempotent:
# run it again to add a version or move the allowed address.
#
# WHAT IT PUTS WHERE. Everything in -Root, so removing the folder removes it:
#   pw-remote-server.cjs        copied from beside this script
#   start-servers.ps1           what the task runs; logs to logs\server-<date>.log
#   playwright-<version>\       npm install playwright@<version>, its Chromium in browsers\
#                               (a version the lanes start using later installs itself here)
# and outside it exactly two things: a firewall rule (-Port..-Port+8, TCP, from
# -Allow only) and a scheduled task (at startup, logged on or not, no time
# limit). -Uninstall removes all three.
#
# WHY S4U. The task runs as the user who ran this script, "whether logged on
# or not", without storing a password: the browser needs no network share,
# and a password stored in a task is one more secret on the disk. SYSTEM would
# also work and is deliberately not used -- the port has no password, and the
# browser behind it should hold no more rights than a user.
param(
	[Parameter(Mandatory = $true)][string]$Root,
	[string[]]$Versions = @(),
	[string]$Allow = '',
	[int]$Port = 39001,
	[string]$TaskName = 'muxtopus-e2e',
	[switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$rule = "$TaskName (Playwright $Port-$($Port + 8))"

if ($Uninstall) {
	Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
	Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
	Get-NetFirewallRule -DisplayName "$TaskName (*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
	Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object CommandLine -like "*$Root*" |
		ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
	if (Test-Path $Root) { Remove-Item -Recurse -Force $Root }
	"removed: task $TaskName, firewall rule, $Root"
	return
}

if (-not $Allow) { throw '-Allow <the test machine''s address> is required: the port has no password' }
$node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $node) { throw 'node.exe is not on PATH: install Node LTS first (nodejs.org)' }
$npm = Join-Path (Split-Path $node) 'node_modules\npm\bin\npm-cli.js'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $Root, "$Root\logs" | Out-Null
Copy-Item (Join-Path $here 'pw-remote-server.cjs') (Join-Path $Root 'pw-remote-server.cjs') -Force

foreach ($v in $Versions) {
	$d = Join-Path $Root "playwright-$v"
	New-Item -ItemType Directory -Force -Path "$d\browsers" | Out-Null
	if (-not (Test-Path "$d\package.json")) { '{"private":true}' | Set-Content -Encoding ascii "$d\package.json" }
	$env:PLAYWRIGHT_BROWSERS_PATH = "$d\browsers"
	$env:npm_config_cache = "$Root\npm-cache"
	# npm and Playwright write progress to stderr; with Stop that is an error.
	$ErrorActionPreference = 'Continue'
	& $node $npm install --prefix $d --no-audit --no-fund "playwright@$v" 2>&1 | Out-Null
	& $node "$d\node_modules\playwright\cli.js" install chromium 2>&1 | Out-Null
	$ErrorActionPreference = 'Stop'
	if (-not (Test-Path "$d\node_modules\playwright\cli.js")) { throw "playwright $v did not install" }
	"playwright $v : " + ((Get-ChildItem "$d\browsers" -Name) -join ', ')
}

# The task's script. Written here rather than shipped so it carries this
# install's node, port and address.
@"
# start-servers.ps1 -- written by pw-remote-setup.ps1; run at startup by the task '$TaskName'.
`$root = Split-Path -Parent `$MyInvocation.MyCommand.Path
`$logs = Join-Path `$root 'logs'
New-Item -ItemType Directory -Force -Path `$logs | Out-Null
Get-ChildItem `$logs -Filter 'server-*.log' | Where-Object LastWriteTime -lt (Get-Date).AddDays(-14) | Remove-Item -ErrorAction SilentlyContinue
`$log = Join-Path `$logs ('server-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
`$env:npm_config_cache = Join-Path `$root 'npm-cache'
& '$node' (Join-Path `$root 'pw-remote-server.cjs') --root `$root --port $Port --host 0.0.0.0 --allow $Allow --install *>> `$log
"@ | Set-Content -Path "$Root\start-servers.ps1" -Encoding UTF8

Get-NetFirewallRule -DisplayName "$TaskName (*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort "$Port-$($Port + 8)" `
	-RemoteAddress $Allow -Action Allow -Profile Any | Out-Null
# A block rule beats an allow rule, and Windows makes one for node.exe when a
# "allow this app" prompt is dismissed. Say so rather than remove it.
$blocks = Get-NetFirewallApplicationFilter | Where-Object Program -like '*node.exe' | Get-NetFirewallRule |
	Where-Object { $_.Action -eq 'Block' -and $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' }
if ($blocks) { 'WARNING: inbound block rules for node.exe will stop the router: ' + (($blocks | ForEach-Object DisplayName) -join '; ') }

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$act = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $Root `
	-Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Root\start-servers.ps1`""
$pri = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
	-RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $pri -Settings $set `
	-Description "e2e-slot remote slots: the Playwright router on port $Port ($Root)." | Out-Null
# A router left over from an earlier run holds the port, and the new task's
# would exit at once; its run-server backends would outlive it. Both run from
# -Root, which is how they are told from any other node on the machine.
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object CommandLine -like "*$Root*" |
	ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-ScheduledTask -TaskName $TaskName
Start-Sleep 5
"task $TaskName : " + (Get-ScheduledTask -TaskName $TaskName).State
try { 'GET /json: ' + (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json" -TimeoutSec 5).Content } catch { "GET /json failed: $_" }
