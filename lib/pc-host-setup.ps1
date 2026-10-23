# pc-host-setup.ps1 -- make a Windows PC a muxtopus pc host: a WSL2 distro of
# its own, reachable by ssh from ONE test machine, that takes whole e2e runs
# (pc slots) and lanes.
#
#   powershell -ExecutionPolicy Bypass -File pc-host-setup.ps1 -Root C:\muxtopus-wsl -Allow 198.51.100.7 `
#       -User alice -PublicKey (Get-Content alice-pc.pub) [-Distro muxtopus] [-Port 22022] `
#       [-LoopbackNames app.example] [-Node 24.19.0] [-Playwright 1.62.1,1.63.0]
#   powershell -ExecutionPolicy Bypass -File pc-host-setup.ps1 -Root C:\muxtopus-wsl -Uninstall [-RemoveDistro]
#
# Run it as an administrator (the firewall rule, the port proxy and the task
# need one), with pc-host-setup.sh beside it. It is idempotent.
#
# WHAT IT MAKES. A NEW distro, -Distro, imported from an Ubuntu 24.04 WSL root
# filesystem into -Root\<Distro> (its ext4.vhdx lives there -- put -Root on the
# disk with room; a lane's tree and node_modules are a few GB). Your other
# distros are not touched: not stopped, not exported, not changed. Inside it,
# pc-host-setup.sh makes -User (the TEST machine's user name: the same HOME on
# both is what lets a run keep its paths), sshd on -Port taking -PublicKey only,
# node and Playwright's Chromium. Outside it, exactly three things:
#   - a scheduled task "<Distro>-keepalive" (at startup, logged on or not,
#     S4U, no stored password) holding one `wsl.exe -d <Distro>` open, because
#     WSL stops a distro nothing is attached to, and sshd with it
#   - a port proxy: <this PC's address>:-Port -> 127.0.0.1:-Port. WSL2's
#     default NAT networking forwards a port the distro listens on to the PC's
#     localhost only; the proxy makes it reachable from the LAN without
#     switching WSL to mirrored networking, which would change every other
#     distro's networking too
#   - a firewall rule: -Port, TCP, from -Allow only
# -Uninstall removes those three; -RemoveDistro also unregisters the distro,
# which DELETES its disk with everything in it.
#
# WHAT IT DOES NOT DO: .wslconfig. Memory, processors and swap are one setting
# for the whole WSL VM -- every distro on the PC -- and applying one needs
# `wsl --shutdown`, which stops all of them. That is the PC owner's decision;
# docs/pc-host.md shows the file.
param(
	[Parameter(Mandatory = $true)][string]$Root,
	[string]$Distro = 'muxtopus',
	[string]$User = '',
	[string]$PublicKey = '',
	[string]$Allow = '',
	[int]$Port = 22022,
	[string]$ListenAddress = '',
	[string[]]$LoopbackNames = @(),
	[string]$Node = '24.19.0',
	[string[]]$Playwright = @(),
	[string]$Rootfs = 'https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz',
	[string]$Sha256 = '',
	[switch]$Uninstall,
	[switch]$RemoveDistro
)
$ErrorActionPreference = 'Stop'
$task = "$Distro-keepalive"
$rule = "$Distro ssh ($Port)"

function Get-Distros { (wsl.exe -l -q) -replace "`0", '' | Where-Object { $_ } }

if ($Uninstall) {
	Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
	Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
	Get-NetFirewallRule -DisplayName "$Distro ssh (*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
	netsh interface portproxy show v4tov4 | Select-String " $Port " | ForEach-Object {
		$f = ($_ -split '\s+') | Where-Object { $_ }
		netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$($f[0]) | Out-Null
	}
	if ($RemoveDistro -and ((Get-Distros) -contains $Distro)) { wsl.exe --unregister $Distro | Out-Null; "unregistered $Distro (its disk is gone)" }
	else { wsl.exe --terminate $Distro 2>$null | Out-Null }
	"removed: task $task, firewall rule, port proxy :$Port" + $(if ($RemoveDistro) { '' } else { " (the distro $Distro and $Root are kept: -RemoveDistro deletes it)" })
	return
}

if (-not $Allow) { throw '-Allow <the test machine''s address> is required: only it may reach the port' }
if (-not $User) { throw '-User <the test machine''s user name> is required: a pc run keeps its paths, so HOME must match' }
if (-not $PublicKey) { throw '-PublicKey "<ssh public key>" is required: the distro takes keys only' }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sh = Join-Path $here 'pc-host-setup.sh'
if (-not (Test-Path $sh)) { throw "pc-host-setup.sh is not beside this script ($here)" }

# 1. The distro, imported once.
New-Item -ItemType Directory -Force -Path "$Root\images", "$Root\$Distro" | Out-Null
if ((Get-Distros) -notcontains $Distro) {
	$img = Join-Path "$Root\images" (Split-Path $Rootfs -Leaf)
	if (-not (Test-Path $img)) { & curl.exe -fsSL -o $img $Rootfs; if ($LASTEXITCODE) { throw "download failed: $Rootfs" } }
	if ($Sha256 -and ((Get-FileHash $img -Algorithm SHA256).Hash -ne $Sha256.ToUpper())) { throw "checksum mismatch: $img" }
	wsl.exe --import $Distro "$Root\$Distro" $img --version 2
	if ($LASTEXITCODE) { throw "wsl --import failed ($LASTEXITCODE)" }
	"imported $Distro into $Root\$Distro"
}

# 2. Inside it. The script goes in through \\wsl.localhost, not a /mnt/c path:
#    pc-host-setup.sh turns the distro's Windows drives off.
wsl.exe -d $Distro -u root -- true | Out-Null
$unc = "\\wsl.localhost\$Distro\tmp\pc-host-setup.sh"
Copy-Item $sh $unc -Force
wsl.exe -d $Distro -u root --exec bash /tmp/pc-host-setup.sh root $User $Port $PublicKey @LoopbackNames
if ($LASTEXITCODE) { throw "pc-host-setup.sh root failed ($LASTEXITCODE)" }
wsl.exe -d $Distro -u $User --exec bash /tmp/pc-host-setup.sh user $Node @Playwright
if ($LASTEXITCODE) { throw "pc-host-setup.sh user failed ($LASTEXITCODE)" }
# /etc/wsl.conf is read when the distro starts.
wsl.exe --terminate $Distro | Out-Null

# 3. The keep-alive task.
Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
$act = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wsl.exe" -Argument "-d $Distro -u root -- /bin/sh -c `"exec sleep infinity`""
$pri = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
$set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
	-RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $act -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $pri -Settings $set `
	-Description "muxtopus pc host: keeps the WSL distro $Distro (and its sshd) running." | Out-Null
Start-ScheduledTask -TaskName $task
Start-Sleep 8

# 4. The port proxy and the firewall rule.
if (-not $ListenAddress) {
	$ListenAddress = (Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
		Select-Object -First 1).IPv4Address.IPAddress
	if (-not $ListenAddress) { throw 'no default-route address found; give -ListenAddress' }
}
netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=$ListenAddress 2>$null | Out-Null
netsh interface portproxy add v4tov4 listenport=$Port listenaddress=$ListenAddress connectport=$Port connectaddress=127.0.0.1 | Out-Null
if ((Get-Service iphlpsvc).Status -ne 'Running') { 'WARNING: the IP Helper service (iphlpsvc) is not running; the port proxy needs it' }
Get-NetFirewallRule -DisplayName "$Distro ssh (*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress $Allow -Action Allow -Profile Any | Out-Null

"task $task : " + (Get-ScheduledTask -TaskName $task).State
"distro: " + ((wsl.exe -l -v) -replace "`0", '' | Select-String $Distro)
"ssh: ${ListenAddress}:$Port -> the distro's sshd, from $Allow only " + $(if (Test-NetConnection 127.0.0.1 -Port $Port -InformationLevel Quiet) { '(listening)' } else { '(NOT listening yet)' })
