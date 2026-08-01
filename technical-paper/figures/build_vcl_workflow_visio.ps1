param(
    [string]$VsdxPath = (Join-Path $PSScriptRoot 'vcl_workflow.vsdx'),
    [string]$OutputDir = (Join-Path $PSScriptRoot 'vcl_workflow_exports'),
    [switch]$Visible
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

# The page is authored at 2x the final IEEE double-column size.
# When placed at 18.2 cm width, 16/17/18 pt text becomes 8/8.5/9 pt.
$PageW = 14.3307
$PageH = 7.4016
$RefW = 3000.0
$RefH = 1550.0

function RGBF([int]$r, [int]$g, [int]$b) { "RGB($r,$g,$b)" }
function VX([double]$x) { $PageW * $x / $RefW }
function VY([double]$y) { $PageH - ($PageH * $y / $RefH) }

$C = @{
    Black      = RGBF 34 34 34
    DarkGray   = RGBF 86 92 99
    Gray       = RGBF 187 187 187
    GraySoft   = RGBF 247 248 249
    GrayMid    = RGBF 224 227 230
    White      = RGBF 255 255 255
    Blue       = RGBF 68 119 170
    BlueDark   = RGBF 41 80 123
    BlueSoft   = RGBF 235 243 250
    Cyan       = RGBF 102 204 238
    CyanDark   = RGBF 25 125 155
    CyanSoft   = RGBF 234 249 253
    Green      = RGBF 34 136 51
    GreenDark  = RGBF 22 98 40
    GreenSoft  = RGBF 235 247 237
    Yellow     = RGBF 204 187 68
    YellowDark = RGBF 126 107 20
    YellowSoft = RGBF 250 247 226
    Red        = RGBF 238 102 119
    RedDark    = RGBF 169 55 72
    RedSoft    = RGBF 253 237 240
}

function Set-Cell($shape, [string]$cell, [string]$formula) {
    try { $shape.CellsU($cell).FormulaU = $formula } catch {}
}

function Set-NodeId($shape, [string]$id) {
    try { $shape.Data1 = $id } catch {}
    try { $shape.Name = $id } catch {}
}

function Style-Shape(
    $shape,
    [string]$fill,
    [string]$line,
    [double]$linePt = 0.8,
    [int]$dash = 1,
    [double]$roundPx = 0
) {
    if ($fill -eq 'none') {
        Set-Cell $shape 'FillPattern' '0'
    } else {
        Set-Cell $shape 'FillPattern' '1'
        Set-Cell $shape 'FillForegnd' $fill
        Set-Cell $shape 'FillBkgnd' $fill
    }
    if ($line -eq 'none') {
        Set-Cell $shape 'LinePattern' '0'
    } else {
        Set-Cell $shape 'LinePattern' ([string]$dash)
        Set-Cell $shape 'LineColor' $line
        Set-Cell $shape 'LineWeight' "$linePt pt"
    }
    if ($roundPx -gt 0) {
        $roundIn = VX $roundPx
        Set-Cell $shape 'Rounding' ($roundIn.ToString([Globalization.CultureInfo]::InvariantCulture) + ' in')
    }
}

function Set-Text(
    $shape,
    [string]$text,
    [double]$size = 16,
    [string]$color = $C.Black,
    [bool]$bold = $false,
    [bool]$italic = $false,
    [int]$align = 1
) {
    $shape.Text = $text.Replace(([string][char]96 + [char]110), [Environment]::NewLine)
    Set-Cell $shape 'Char.Font' 'FONT("Arial")'
    Set-Cell $shape 'Char.Size' "$size pt"
    Set-Cell $shape 'Char.Color' $color
    $style = 0
    if ($bold) { $style += 1 }
    if ($italic) { $style += 2 }
    Set-Cell $shape 'Char.Style' ([string]$style)
    Set-Cell $shape 'Para.HorzAlign' ([string]$align)
    Set-Cell $shape 'Para.SpBefore' '0 pt'
    Set-Cell $shape 'Para.SpAfter' '0 pt'
    Set-Cell $shape 'Para.Leading' '-1.05'
    Set-Cell $shape 'VerticalAlign' '1'
    foreach ($m in 'TxtMarginLeft','TxtMarginRight','TxtMarginTop','TxtMarginBottom') {
        Set-Cell $shape $m '1 pt'
    }
}

function RectTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text = '',
    [string]$fill = 'none',
    [string]$line = $C.Black,
    [double]$size = 16,
    [bool]$bold = $false,
    [double]$linePt = 0.8,
    [int]$dash = 1,
    [double]$roundPx = 10,
    [string]$id = ''
) {
    $s = $script:Page.DrawRectangle((VX $x), (VY ($y + $h)), (VX ($x + $w)), (VY $y))
    Style-Shape $s $fill $line $linePt $dash $roundPx
    if ($text -ne '') { Set-Text $s $text $size $C.Black $bold }
    if ($id -ne '') { Set-NodeId $s $id }
    return $s
}

function TextTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text,
    [double]$size = 16,
    [string]$color = $C.Black,
    [bool]$bold = $false,
    [bool]$italic = $false,
    [int]$align = 1,
    [string]$id = ''
) {
    $s = RectTL $x $y $w $h '' 'none' 'none' $size $bold 0 1 0 $id
    Set-Text $s $text $size $color $bold $italic $align
    return $s
}

function OvalTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text = '',
    [string]$fill = $C.White,
    [string]$line = $C.Black,
    [double]$size = 16,
    [bool]$bold = $false,
    [double]$linePt = 0.8,
    [string]$id = ''
) {
    $s = $script:Page.DrawOval((VX $x), (VY ($y + $h)), (VX ($x + $w)), (VY $y))
    Style-Shape $s $fill $line $linePt 1 0
    if ($text -ne '') { Set-Text $s $text $size $C.Black $bold }
    if ($id -ne '') { Set-NodeId $s $id }
    return $s
}

function LineTL(
    [double]$x1, [double]$y1, [double]$x2, [double]$y2,
    [string]$color = $C.Black,
    [double]$linePt = 0.8,
    [bool]$arrowEnd = $false,
    [int]$dash = 1
) {
    $s = $script:Page.DrawLine((VX $x1), (VY $y1), (VX $x2), (VY $y2))
    Set-Cell $s 'LineColor' $color
    Set-Cell $s 'LineWeight' "$linePt pt"
    Set-Cell $s 'LinePattern' ([string]$dash)
    if ($arrowEnd) {
        Set-Cell $s 'EndArrow' '4'
        Set-Cell $s 'EndArrowSize' '2'
    }
    return $s
}

function ElbowArrow(
    [double]$x1, [double]$y1,
    [double]$xm, [double]$ym,
    [double]$x2, [double]$y2,
    [string]$color = $C.Black,
    [double]$linePt = 0.8,
    [int]$dash = 1
) {
    LineTL $x1 $y1 $xm $y1 $color $linePt $false $dash | Out-Null
    LineTL $xm $y1 $xm $ym $color $linePt $false $dash | Out-Null
    LineTL $xm $ym $x2 $y2 $color $linePt $true $dash | Out-Null
}

function CylinderTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title,
    [string]$detail,
    [string]$fill,
    [string]$line,
    [double]$linePt = 1.0,
    [string]$id = ''
) {
    $capH = [Math]::Min(38.0, $h * 0.22)
    $body = RectTL $x ($y + $capH / 2) $w ($h - $capH) '' $fill $line 16 $false $linePt 1 0 $id
    OvalTL $x $y $w $capH '' $fill $line 16 $false $linePt | Out-Null
    OvalTL $x ($y + $h - $capH) $w $capH '' $fill $line 16 $false $linePt | Out-Null
    RectTL ($x + 1) ($y + $capH / 2 + 1) ($w - 2) ($h - $capH - 2) '' $fill 'none' 16 $false 0 1 0 | Out-Null
    TextTL ($x + 8) ($y + 0.28 * $h) ($w - 16) (0.30 * $h) $title 17 $C.Black $true | Out-Null
    TextTL ($x + 8) ($y + 0.58 * $h) ($w - 16) (0.25 * $h) $detail 16 $C.DarkGray $false | Out-Null
    return $body
}

function DocumentTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title,
    [string]$detail,
    [string]$fill,
    [string]$line,
    [string]$id = ''
) {
    $s = RectTL $x $y $w $h '' $fill $line 16 $false 0.9 1 5 $id
    $fold = [Math]::Min(34.0, $w * 0.18)
    LineTL ($x + $w - $fold) $y ($x + $w - $fold) ($y + $fold) $line 0.6 $false | Out-Null
    LineTL ($x + $w - $fold) ($y + $fold) ($x + $w) ($y + $fold) $line 0.6 $false | Out-Null
    TextTL ($x + 8) ($y + 0.20 * $h) ($w - 16) (0.30 * $h) $title 17 $C.Black $true | Out-Null
    TextTL ($x + 8) ($y + 0.55 * $h) ($w - 16) (0.25 * $h) $detail 16 $C.DarkGray | Out-Null
    return $s
}

function DiamondTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text,
    [string]$fill,
    [string]$line,
    [double]$size = 16,
    [string]$id = ''
) {
    $side = [Math]::Min($w, $h) * 0.68
    $sx = $x + ($w - $side) / 2
    $sy = $y + ($h - $side) / 2
    $body = RectTL $sx $sy $side $side '' $fill $line $size $false 0.9 1 0 $id
    Set-Cell $body 'Angle' '45 deg'
    TextTL $x ($y + 0.25 * $h) $w (0.50 * $h) $text $size $C.Black $true | Out-Null
    return $body
}

function PanelTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title,
    [string]$subtitle,
    [string]$fill,
    [string]$line,
    [double]$linePt = 0.9,
    [int]$dash = 1,
    [string]$id = ''
) {
    $panel = RectTL $x $y $w $h '' $fill $line 16 $false $linePt $dash 12 $id
    RectTL ($x + 1) ($y + 1) ($w - 2) 54 '' $line $line 16 $false 0 1 10 | Out-Null
    TextTL ($x + 14) ($y + 8) ($w - 28) 27 $title 18 $C.White $true $false 0 | Out-Null
    TextTL ($x + 14) ($y + 33) ($w - 28) 18 $subtitle 16 $C.White $false $false 0 | Out-Null
    return $panel
}

function StepTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text,
    [string]$fill,
    [string]$line,
    [bool]$bold = $false,
    [string]$id = ''
) {
    return RectTL $x $y $w $h $text $fill $line 16 $bold 0.65 1 7 $id
}

function TagTL(
    [double]$x, [double]$y, [double]$w,
    [string]$text,
    [string]$fill,
    [string]$line
) {
    RectTL $x $y $w 32 $text $fill $line 16 $true 0.55 1 16 | Out-Null
}

function Draw-Workflow {
    # Background and title band.
    RectTL 0 0 $RefW $RefH '' $C.White 'none' 16 $false 0 1 0 | Out-Null
    RectTL 28 25 2944 122 '' $C.GraySoft $C.GrayMid 16 $false 0.6 1 14 | Out-Null
    TextTL 55 40 1120 42 'Evidence-Governed Verified-Candidate Loop' 27 $C.Black $true $false 0 | Out-Null
    TextTL 58 88 1060 28 'LLM proposes; measured evidence decides.' 18 $C.DarkGray $false $false 0 | Out-Null

    # Legend.
    LineTL 1975 62 2080 62 $C.Black 0.9 $true 1 | Out-Null
    TextTL 2090 43 270 38 'candidate / evidence flow' 16 $C.DarkGray $false $false 0 | Out-Null
    LineTL 1975 102 2080 102 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 2090 83 260 38 'within-run feedback' 16 $C.RedDark $false $false 0 | Out-Null
    LineTL 2390 62 2495 62 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 2505 43 380 38 'across-run evidence reuse' 16 $C.BlueDark $false $false 0 | Out-Null
    LineTL 2390 102 2495 102 $C.Green 1.5 $true 1 | Out-Null
    TextTL 2505 83 380 38 'establish / update fallback' 16 $C.GreenDark $false $false 0 | Out-Null

    # Stage tags.
    TagTL 42 160 410 '01  INITIALIZE STATE' $C.GraySoft $C.DarkGray
    TagTL 625 160 565 '02  PROPOSE CANDIDATE' $C.CyanSoft $C.CyanDark
    TagTL 1210 160 840 '03  ADMIT + VALIDATE' $C.BlueSoft $C.BlueDark
    TagTL 2070 160 680 '04  PROMOTE SAFELY' $C.GreenSoft $C.GreenDark
    TagTL 2770 160 190 '05  DELIVER' $C.GraySoft $C.DarkGray

    # Main-level nodes and panels.
    DocumentTL 42 300 170 245 'Task Contract`n+ Starter' 'interface · budget`nstarter' $C.GraySoft $C.DarkGray 'N1' | Out-Null
    CylinderTL 232 285 200 275 'Run State' 'kernel · evidence`nbudget · history' $C.GraySoft $C.DarkGray 1.0 'N2' | Out-Null
    DiamondTL 458 335 138 170 'State-Aware`nRole Router' $C.YellowSoft $C.YellowDark 16 'N3' | Out-Null
    TextTL 458 492 138 55 'Repair`nStructural`nOptimization' 16 $C.YellowDark | Out-Null

    PanelTL 625 215 565 505 'Role-Conditioned Proposal' 'role-specific evidence → one full-source candidate' $C.CyanSoft $C.CyanDark 0.9 2 'N4' | Out-Null
    TextTL 642 278 128 30 'Repair Context' 16 $C.CyanDark $true $false 0 | Out-Null
    StepTL 770 270 255 58 'CSim/Synth failure`nnormalize · classify · feedback' $C.White $C.CyanDark | Out-Null
    StepTL 1040 270 130 58 'Repair`nPrompt' $C.White $C.CyanDark $true | Out-Null
    LineTL 1025 299 1040 299 $C.Black 0.65 $true | Out-Null

    TextTL 642 354 128 30 'Structural Context' 16 $C.CyanDark $true $false 0 | Out-Null
    StepTL 770 346 255 58 'Required CoSim failure`ndiagnostics · stream/dataflow' $C.White $C.CyanDark | Out-Null
    StepTL 1040 346 130 58 'Structural`nRepair Prompt' $C.White $C.CyanDark $true | Out-Null
    LineTL 1025 375 1040 375 $C.Black 0.65 $true | Out-Null

    TextTL 642 432 128 30 'Optimization Context' 16 $C.CyanDark $true $false 0 | Out-Null
    StepTL 770 418 255 88 'current best · source · synth`nBaseline QoR Context · headroom`nQoR-RAG · measured rejections' $C.White $C.CyanDark | Out-Null
    StepTL 1040 433 130 58 'Optimization`nPrompt' $C.White $C.CyanDark $true | Out-Null
    LineTL 1025 462 1040 462 $C.Black 0.65 $true | Out-Null

    LineTL 1105 328 1105 535 $C.Black 0.65 $false | Out-Null
    LineTL 1105 404 1105 535 $C.Black 0.65 $false | Out-Null
    LineTL 1105 491 1105 535 $C.Black 0.65 $false | Out-Null
    StepTL 770 535 250 62 'LLM Candidate Proposer' $C.White $C.CyanDark $true 'N4_LLM' | Out-Null
    LineTL 1020 566 1042 566 $C.Black 0.8 $true | Out-Null
    StepTL 1042 535 128 62 'Full-Source`nCandidate' $C.Cyan $C.CyanDark $true 'N4_FULL_SOURCE' | Out-Null
    TextTL 650 618 500 58 'The LLM proposes code; it does not promote candidates.' 16 $C.CyanDark $false $true | Out-Null

    PanelTL 1210 215 305 505 'Candidate Admission' 'deterministic pre-tool checks' $C.YellowSoft $C.YellowDark 0.9 1 'N5' | Out-Null
    StepTL 1245 292 235 64 'Code Extraction' $C.White $C.YellowDark $true 'N5_EXTRACT' | Out-Null
    LineTL 1362 356 1362 384 $C.Black 0.65 $true | Out-Null
    StepTL 1245 384 235 92 'Deterministic Guards`ninterface · no-op · duplicate`naction · report-evidence' $C.White $C.YellowDark $true 'N5_GUARDS' | Out-Null
    LineTL 1362 476 1362 504 $C.Black 0.65 $true | Out-Null
    StepTL 1245 504 235 70 'Budget Admission' $C.White $C.YellowDark $true 'N5_BUDGET' | Out-Null
    TextTL 1232 600 260 78 'Reject partial validation when the remaining budget cannot finish the full chain.' 16 $C.YellowDark $false $true | Out-Null

    PanelTL 1535 215 515 505 'Validation Chain' 'one ordered, tool-grounded evidence path' $C.BlueSoft $C.BlueDark 1.0 1 'N6' | Out-Null
    $gateY = @(278, 330, 382, 434, 486, 538, 600)
    $gateText = @('Interface','CSim','Synth','Frequency','Capacity','Required CoSim','Metric Completeness')
    for ($i = 0; $i -lt $gateY.Count; $i++) {
        $gateId = "N6_GATE_$i"
        StepTL 1570 $gateY[$i] 252 42 $gateText[$i] $C.White $C.BlueDark ($i -eq 6) $gateId | Out-Null
        if ($i -lt $gateY.Count - 1) {
            LineTL 1696 ($gateY[$i] + 42) 1696 $gateY[$i + 1] $C.BlueDark 0.7 $true | Out-Null
        }
    }
    TextTL 1828 526 194 42 'conditional on`ntask manifest' 16 $C.DarkGray $false $true | Out-Null
    LineTL 1822 507 1960 507 $C.DarkGray 0.6 $false 10 | Out-Null
    LineTL 1960 507 1960 621 $C.DarkGray 0.6 $false 10 | Out-Null
    LineTL 1960 621 1822 621 $C.DarkGray 0.6 $true 10 | Out-Null
    TextTL 1828 565 190 44 'CoSim not required' 16 $C.DarkGray $false $true | Out-Null
    RectTL 1835 645 175 54 'Candidate QoR`nEvidence' $C.Blue $C.BlueDark 16 $true 0.8 1 18 'Q2' | Out-Null
    LineTL 1822 403 1922 403 $C.Blue 0.7 $false | Out-Null
    LineTL 1922 403 1922 645 $C.Blue 0.7 $true | Out-Null
    LineTL 1822 559 1900 559 $C.Blue 0.7 $false | Out-Null
    LineTL 1900 559 1900 645 $C.Blue 0.7 $true | Out-Null

    PanelTL 2070 215 470 505 'Promotion Controller' 'validation restores validity; measurement improves QoR' $C.GreenSoft $C.GreenDark 1.25 1 'N7' | Out-Null
    DiamondTL 2218 270 175 112 'Candidate`nRole?' $C.White $C.GreenDark 16 'N7_ROLE' | Out-Null
    TextTL 2085 366 210 30 'Validity Restoration' 17 $C.GreenDark $true | Out-Null
    TextTL 2305 366 220 30 'QoR Improvement' 17 $C.GreenDark $true | Out-Null
    StepTL 2092 405 198 54 'Repair / Structural' $C.White $C.GreenDark $true | Out-Null
    StepTL 2310 405 198 54 'Optimization' $C.White $C.GreenDark $true | Out-Null
    LineTL 2191 459 2191 485 $C.GreenDark 0.8 $true | Out-Null
    LineTL 2409 459 2409 485 $C.GreenDark 0.8 $true | Out-Null
    StepTL 2092 485 198 54 'Complete Validation Pass' $C.White $C.GreenDark | Out-Null
    StepTL 2310 485 198 54 'Complete Validation Pass' $C.White $C.GreenDark | Out-Null
    LineTL 2191 539 2191 565 $C.GreenDark 0.8 $true | Out-Null
    LineTL 2409 539 2409 555 $C.GreenDark 0.8 $true | Out-Null
    StepTL 2092 565 198 72 'Establish Verified`nFallback' $C.Green $C.GreenDark $true 'N7_RESTORE' | Out-Null
    DiamondTL 2310 550 198 105 'Q_HW`nPromotion Gate' $C.White $C.GreenDark 16 'Q3' | Out-Null
    TextTL 2310 656 198 38 'compare measured QoR' 16 $C.GreenDark $false $true | Out-Null

    CylinderTL 2560 333 190 238 'Verified`nFallback' 'latest fully`nverified candidate' $C.GreenSoft $C.GreenDark 1.4 'N8' | Out-Null
    DocumentTL 2770 345 190 214 'Final`nArtifacts' 'kernel · run report`nsubmission evidence' $C.GreenSoft $C.GreenDark 'N12' | Out-Null

    # Main horizontal flow and labels.
    LineTL 212 423 232 423 $C.Black 0.9 $true | Out-Null
    TextTL 198 386 55 28 'initialize' 16 $C.DarkGray | Out-Null
    LineTL 432 423 458 423 $C.Black 0.9 $true | Out-Null
    LineTL 596 423 625 423 $C.Black 0.9 $true | Out-Null
    TextTL 576 385 70 30 'selected role' 16 $C.DarkGray | Out-Null
    LineTL 1190 423 1210 423 $C.Black 0.9 $true | Out-Null
    TextTL 1170 382 70 38 'proposed`ncandidate' 16 $C.DarkGray | Out-Null
    LineTL 1515 423 1535 423 $C.Black 0.9 $true | Out-Null
    TextTL 1488 380 76 42 'admitted`ncandidate' 16 $C.DarkGray | Out-Null
    LineTL 2050 423 2070 423 $C.Black 0.9 $true | Out-Null
    TextTL 2020 380 80 40 'validated`nevidence' 16 $C.DarkGray | Out-Null
    LineTL 2540 435 2560 435 $C.Green 1.5 $true | Out-Null
    TextTL 2500 390 92 34 'establish / update' 16 $C.GreenDark | Out-Null
    LineTL 2750 452 2770 452 $C.Black 0.9 $true | Out-Null
    TextTL 2718 400 85 44 'stop /`nconvergence' 16 $C.DarkGray | Out-Null

    # Bootstrap validation, positive state loop, and budget-safe stop.
    LineTL 332 285 332 205 $C.Black 0.8 $false | Out-Null
    LineTL 332 205 1790 205 $C.Black 0.8 $false | Out-Null
    LineTL 1790 205 1790 215 $C.Black 0.8 $true | Out-Null
    TextTL 785 170 245 30 'bootstrap validation' 16 $C.DarkGray | Out-Null
    LineTL 2655 333 2655 132 $C.GreenDark 0.85 $false 10 | Out-Null
    LineTL 2655 132 332 132 $C.GreenDark 0.85 $false 10 | Out-Null
    LineTL 332 132 332 285 $C.GreenDark 0.85 $true 10 | Out-Null
    TextTL 1300 105 315 30 'positive state loop · update current best' 16 $C.GreenDark $false $true | Out-Null
    LineTL 1480 539 1518 539 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 1518 539 1518 742 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 1518 742 2865 742 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 2865 742 2865 559 $C.DarkGray 0.7 $true 10 | Out-Null
    TextTL 1960 715 315 30 'budget denied · retain fallback' 16 $C.DarkGray $false $true | Out-Null

    # Fast feedback band: QoR-RAG and Failure Reflection.
    PanelTL 595 780 640 210 'QoR-RAG' 'advisory evidence only; validation and promotion still decide' $C.CyanSoft $C.CyanDark 0.9 2 'N10' | Out-Null
    StepTL 620 858 175 60 'Build Structured`nQuery' $C.White $C.CyanDark $true | Out-Null
    StepTL 825 858 175 60 'Retrieve Public`nEvidence' $C.White $C.CyanDark $true | Out-Null
    StepTL 1030 858 180 60 'Bounded Prompt`nContext' $C.White $C.CyanDark $true | Out-Null
    LineTL 795 888 825 888 $C.CyanDark 0.7 $true | Out-Null
    LineTL 1000 888 1030 888 $C.CyanDark 0.7 $true | Out-Null
    TextTL 630 934 570 35 'retrieval influences Optimization Context—not Repair or Structural' 16 $C.CyanDark $false $true | Out-Null

    PanelTL 1290 780 1040 210 'Failure Reflection' 'within-run fast loop' $C.YellowSoft $C.YellowDark 0.9 1 'N9' | Out-Null
    StepTL 1320 858 225 60 'key diagnostic lines' $C.White $C.YellowDark | Out-Null
    StepTL 1565 858 210 60 'candidate diff' $C.White $C.YellowDark | Out-Null
    StepTL 1795 858 245 60 'implicated source elements' $C.White $C.YellowDark | Out-Null
    StepTL 2060 858 235 60 'next constraint' $C.White $C.YellowDark $true | Out-Null
    LineTL 1545 888 1565 888 $C.YellowDark 0.6 $true | Out-Null
    LineTL 1775 888 1795 888 $C.YellowDark 0.6 $true | Out-Null
    LineTL 2040 888 2060 888 $C.YellowDark 0.6 $true | Out-Null

    # Admission / gate / QoR rejection to reflection.
    LineTL 1362 574 1362 760 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1362 760 1450 760 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1450 760 1450 780 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 1280 724 180 30 'admission rejection' 16 $C.RedDark $false $true | Out-Null
    LineTL 1725 699 1725 754 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1725 754 1770 754 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1770 754 1770 780 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 1680 720 150 30 'gate failure' 16 $C.RedDark $false $true | Out-Null
    LineTL 2409 655 2409 750 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2409 750 2220 750 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2220 750 2220 780 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 2220 712 230 34 'Measured QoR Rejection' 16 $C.RedDark $true $true | Out-Null

    # Reflection back to router/proposal and into QoR-RAG.
    LineTL 1350 990 1350 1020 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1350 1020 520 1020 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 520 1020 520 560 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 520 560 527 560 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 540 990 320 30 'failure-stage role selection' 16 $C.RedDark $false $true | Out-Null
    LineTL 1520 990 1520 1045 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1520 1045 720 1045 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 720 1045 720 720 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 910 1018 180 28 'next constraint' 16 $C.RedDark $false $true | Out-Null
    LineTL 1290 900 1235 900 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 1195 930 230 35 'rejection / failure history' 16 $C.RedDark $false $true | Out-Null

    # Verified fallback baseline to QoR-RAG, then retrieved evidence to Optimization Context.
    LineTL 2655 571 2655 1010 $C.BlueDark 0.85 $false 10 | Out-Null
    LineTL 2655 1010 1140 1010 $C.BlueDark 0.85 $false 10 | Out-Null
    LineTL 1140 1010 1140 990 $C.BlueDark 0.85 $true 10 | Out-Null
    TextTL 1980 980 390 30 'Baseline QoR Context + source structure' 16 $C.BlueDark $false $true | Out-Null
    LineTL 595 900 560 900 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 560 900 560 462 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 560 462 770 462 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 568 810 190 32 'retrieved evidence' 16 $C.BlueDark $false $true | Out-Null

    # Slow loop: public evidence.
    PanelTL 50 1110 1805 370 'Public Evidence Loop' 'across-run slow loop · only public submission-side evidence' $C.GraySoft $C.Blue 1.0 2 'N11' | Out-Null
    DocumentTL 115 1230 425 150 'Fully Verified`nPublic Run Report' 'required gates complete' $C.White $C.Blue 'N11_REPORT' | Out-Null
    StepTL 675 1215 480 180 'Evidence Curation`n`nversion compatibility`nrequired gates complete`nverified success / measured failure`nprovenance filter' $C.White $C.BlueDark $true 'N11_CURATE' | Out-Null
    CylinderTL 1310 1220 430 170 'Public Evidence Store' 'verified public cases' $C.BlueSoft $C.BlueDark 1.0 'N11_STORE' | Out-Null
    LineTL 540 1305 675 1305 $C.Blue 1.0 $true 2 | Out-Null
    LineTL 1155 1305 1310 1305 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 565 1266 110 32 'curate' 16 $C.BlueDark $false $true | Out-Null

    # Final artifact report enters the public evidence loop.
    LineTL 2865 559 2865 1070 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 2865 1070 330 1070 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 330 1070 330 1230 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 2150 1040 360 30 'public submission run report' 16 $C.BlueDark $false $true | Out-Null

    # Future-run retrieval from public evidence store to QoR-RAG.
    LineTL 1525 1390 1525 1510 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 1525 1510 760 1510 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 760 1510 760 990 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 950 1475 330 30 'future-run retrieval · verified public cases' 16 $C.BlueDark $false $true | Out-Null

    # Independent evaluator and one-way trust boundary.
    RectTL 2390 1110 570 370 '' 'none' $C.Gray 16 $false 1.0 2 18 'N13_BOUNDARY' | Out-Null
    TextTL 2420 1130 510 35 'Evaluator Trust Boundary' 18 $C.DarkGray $true | Out-Null
    RectTL 2470 1205 410 150 'Independent Evaluator`n`nhidden / reference checks`nFinal QoR Score' $C.GraySoft $C.DarkGray 17 $true 0.9 1 8 'N13' | Out-Null
    TextTL 2445 1390 460 44 'no evaluator evidence enters QoR-RAG' 16 $C.DarkGray $false $true | Out-Null
    LineTL 2865 559 2865 1090 $C.Black 0.9 $false | Out-Null
    LineTL 2865 1090 2920 1090 $C.Black 0.9 $false | Out-Null
    LineTL 2920 1090 2920 1280 $C.Black 0.9 $false | Out-Null
    LineTL 2920 1280 2880 1280 $C.Black 0.9 $true | Out-Null
    TextTL 2570 1045 300 42 'final kernel + submission evidence' 16 $C.DarkGray $false $true | Out-Null
}

function Export-Pptx($page, [string]$svgPath, [string]$pptxPath) {
    $powerPoint = $null
    $presentation = $null
    try {
        $powerPoint = New-Object -ComObject PowerPoint.Application
        $powerPoint.Visible = -1
        $presentation = $powerPoint.Presentations.Add()
        $pageWidthPt = [double]$page.PageSheet.CellsU('PageWidth').ResultIU * 72.0
        $pageHeightPt = [double]$page.PageSheet.CellsU('PageHeight').ResultIU * 72.0
        $presentation.PageSetup.SlideWidth = $pageWidthPt
        $presentation.PageSetup.SlideHeight = $pageHeightPt
        $slide = $presentation.Slides.Add(1, 12)
        $slide.Shapes.AddPicture($svgPath, $false, $true, 0, 0, $pageWidthPt, $pageHeightPt) | Out-Null
        $presentation.SaveAs($pptxPath, 24)
    } finally {
        if ($presentation -ne $null) { try { $presentation.Close() } catch {} }
        if ($powerPoint -ne $null) { try { $powerPoint.Quit() } catch {} }
    }
}

. (Join-Path $PSScriptRoot 'draw_vcl_workflow_v3.ps1')

$VsdxPath = [IO.Path]::GetFullPath($VsdxPath)
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

$backup = $null
if (Test-Path -LiteralPath $VsdxPath) {
    $backup = Join-Path (Split-Path -Parent $VsdxPath) (
        [IO.Path]::GetFileNameWithoutExtension($VsdxPath) +
        '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.vsdx'
    )
    Copy-Item -LiteralPath $VsdxPath -Destination $backup
}

$visio = $null
$doc = $null
try {
    $visio = New-Object -ComObject Visio.Application
    $visio.Visible = [bool]$Visible

    if (Test-Path -LiteralPath $VsdxPath) {
        $doc = $visio.Documents.Open($VsdxPath)
    } else {
        $doc = $visio.Documents.Add('')
        $doc.SaveAs($VsdxPath) | Out-Null
    }

    $script:Page = $doc.Pages.Item(1)
    $script:Page.Name = 'Verified-Candidate Loop'
    $script:Page.PageSheet.CellsU('PageWidth').FormulaU = "$PageW in"
    $script:Page.PageSheet.CellsU('PageHeight').FormulaU = "$PageH in"
    Set-Cell $script:Page.PageSheet 'PageLeftMargin' '0 in'
    Set-Cell $script:Page.PageSheet 'PageRightMargin' '0 in'
    Set-Cell $script:Page.PageSheet 'PageTopMargin' '0 in'
    Set-Cell $script:Page.PageSheet 'PageBottomMargin' '0 in'

    while ($script:Page.Shapes.Count -gt 0) {
        $script:Page.Shapes.Item(1).Delete() | Out-Null
    }

    Draw-WorkflowV3
    $shapeCount = $script:Page.Shapes.Count
    $doc.Save() | Out-Null

    $base = 'vcl_workflow'
    $pngPath = Join-Path $OutputDir "$base.png"
    $svgPath = Join-Path $OutputDir "$base.svg"
    $pdfPath = Join-Path $OutputDir "$base.pdf"
    $pptxPath = Join-Path $OutputDir "$base.pptx"

    $visio.Settings.SetRasterExportResolution(3, 600, 600, 0)
    $script:Page.Export($pngPath)
    $script:Page.Export($svgPath)
    $doc.ExportAsFixedFormat(1, $pdfPath, 1, 0)
    $pptxExported = $false
    try {
        Export-Pptx $script:Page $svgPath $pptxPath
        $pptxExported = $true
    } catch {
        Write-Warning "PPTX export skipped: $($_.Exception.Message)"
    }

    Write-Output "Saved: $VsdxPath"
    if ($backup) { Write-Output "Backup: $backup" }
    Write-Output "Shape count: $shapeCount"
    $exportedPaths = @($pngPath, $svgPath, $pdfPath)
    if ($pptxExported) { $exportedPaths += $pptxPath }
    foreach ($path in $exportedPaths) {
        $item = Get-Item -LiteralPath $path
        Write-Output ("Export: {0} ({1} bytes)" -f $item.FullName, $item.Length)
    }
} finally {
    if ($doc -ne $null) { try { $doc.Close() } catch {} }
    if ($visio -ne $null) { try { $visio.Quit() } catch {} }
}





