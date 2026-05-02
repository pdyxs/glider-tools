# glider-wake.ps1 — Re-enumerate the Glider USB device after sleep/wake.
# Run via Task Scheduler triggered on Event ID 1 (Power-Troubleshooter / wake).
# Requires: run as Administrator (set in the task's General tab).

$instanceId = "USB\VID_1209&PID_AE86\3B001900"
pnputil /restart-device $instanceId
Write-Host "Restarted $instanceId"
