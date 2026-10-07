$code = @"
using System;
using System.Runtime.InteropServices;
public class WC {
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
}
"@
Add-Type -TypeDefinition $code
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[void][WC]::SetProcessDpiAwarenessContext([IntPtr]([int]-4))

$dir = $PSScriptRoot
$cmd = Join-Path $dir "pet_cmd.json"

function Snap($name) {
    $bmp = New-Object System.Drawing.Bitmap 2880, 1800
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)
    $bmp.Save((Join-Path $dir $name), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
}

# 后空翻: 0.45s(蓄力) / 0.85s(空中转体) / 1.05s(继续转)
Set-Content -Path $cmd -Value '{"op": "flip"}' -Encoding ASCII
Start-Sleep -Milliseconds 450;  Snap "_na_flip1.png"
Start-Sleep -Milliseconds 400;  Snap "_na_flip2.png"
Start-Sleep -Milliseconds 200;  Snap "_na_flip3.png"
Start-Sleep -Milliseconds 1800

# 挥手: 1.2s(手臂举起挥动中)
Set-Content -Path $cmd -Value '{"op": "wave"}' -Encoding ASCII
Start-Sleep -Milliseconds 1200; Snap "_na_wave.png"
Start-Sleep -Milliseconds 1800

# 打滚: 1.3s(滚程中)
Set-Content -Path $cmd -Value '{"op": "roll"}' -Encoding ASCII
Start-Sleep -Milliseconds 1300; Snap "_na_roll.png"
Start-Sleep -Milliseconds 2000

# 魔法变身: 1.9s(转完落地,星光形态已激活)
Set-Content -Path $cmd -Value '{"op": "transform"}' -Encoding ASCII
Start-Sleep -Milliseconds 1900; Snap "_na_trans.png"
Start-Sleep -Milliseconds 1200; Snap "_na_trans2.png"
Write-Output "captured"
