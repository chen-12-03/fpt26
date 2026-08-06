function SimplePanelTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title,
    [string]$fill,
    [string]$line,
    [double]$linePt = 0.9,
    [int]$dash = 1,
    [string]$id = ''
) {
    $panel = RectTL $x $y $w $h '' $fill $line 16 $false $linePt $dash 14 $id
    RectTL ($x + 1) ($y + 1) ($w - 2) 88 '' $line $line 16 $false 0 1 12 | Out-Null
    TextTL ($x + 16) ($y + 10) ($w - 32) 68 $title 18 $C.White $true $false 0 | Out-Null
    return $panel
}

function ReadableCylinderTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title, [string]$detail,
    [string]$fill, [string]$line,
    [double]$linePt = 1.0, [string]$id = ''
) {
    $capH = [Math]::Min(32.0, $h * 0.22)
    $body = RectTL $x ($y + $capH / 2) $w ($h - $capH) '' $fill $line 16 $false $linePt 1 0 $id
    OvalTL $x $y $w $capH '' $fill $line 16 $false $linePt | Out-Null
    OvalTL $x ($y + $h - $capH) $w $capH '' $fill $line 16 $false $linePt | Out-Null
    RectTL ($x + 1) ($y + $capH / 2 + 1) ($w - 2) ($h - $capH - 2) '' $fill 'none' 16 $false 0 1 0 | Out-Null
    if ($detail -eq '') {
        TextTL ($x + 12) ($y + ($h - 70) / 2) ($w - 24) 70 $title 17 $C.Black $true | Out-Null
    } else {
        TextTL ($x + 12) ($y + 12) ($w - 24) 58 $title 16 $C.Black $true | Out-Null
        TextTL ($x + 12) ($y + 75) ($w - 24) 58 $detail 16 $C.DarkGray $false | Out-Null
    }
    return $body
}

function ReadableDiamondTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$text, [string]$fill, [string]$line,
    [double]$size = 16, [string]$id = ''
) {
    $side = [Math]::Min($w, $h) * 0.68
    $sx = $x + ($w - $side) / 2
    $sy = $y + ($h - $side) / 2
    $body = RectTL $sx $sy $side $side '' $fill $line $size $false 0.9 1 0 $id
    Set-Cell $body 'Angle' '45 deg'
    TextTL $x ($y + 0.15 * $h) $w (0.70 * $h) $text $size $C.Black $true | Out-Null
    return $body
}
function Draw-WorkflowV2 {
    # Five readable stages, one fast feedback band, and one slow evidence band.
    # A 16 pt line receives at least 60 reference units of height.
    RectTL 0 0 $RefW $RefH '' $C.White 'none' 16 $false 0 1 0 | Out-Null

    RectTL 28 24 2944 132 '' $C.GraySoft $C.GrayMid 16 $false 0.6 1 14 | Out-Null
    TextTL 58 46 1650 86 'Evidence-Governed Verified-Candidate Loop' 22 $C.Black $true $false 0 | Out-Null
    LineTL 1810 67 1910 67 $C.Black 0.9 $true 1 | Out-Null
    TextTL 1930 38 240 60 'flow' 16 $C.DarkGray $false $false 0 | Out-Null
    LineTL 1810 117 1910 117 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 1930 88 240 60 'within-run' 16 $C.RedDark $false $false 0 | Out-Null
    LineTL 2330 67 2430 67 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 2450 38 300 60 'across-run' 16 $C.BlueDark $false $false 0 | Out-Null
    LineTL 2330 117 2430 117 $C.Green 1.5 $true 1 | Out-Null
    TextTL 2450 88 350 60 'fallback update' 16 $C.GreenDark $false $false 0 | Out-Null

    SimplePanelTL 40 190 430 720 '01  INITIALIZE' $C.GraySoft $C.DarkGray 0.9 1 'S1' | Out-Null
    SimplePanelTL 490 190 650 720 '02  PROPOSE' $C.CyanSoft $C.CyanDark 0.9 1 'S2' | Out-Null
    SimplePanelTL 1160 190 620 720 '03  ADMIT + VALIDATE' $C.BlueSoft $C.BlueDark 1.0 1 'S3' | Out-Null
    SimplePanelTL 1800 190 690 720 '04  PROMOTE SAFELY' $C.GreenSoft $C.GreenDark 1.2 1 'S4' | Out-Null
    SimplePanelTL 2510 190 450 720 '05  DELIVER' $C.GraySoft $C.DarkGray 0.9 1 'S5' | Out-Null

    # 01 — task, shared state, and role selection.
    StepTL 80 305 350 115 'Task Contract`n+ Starter' $C.White $C.DarkGray $true 'N1' | Out-Null
    LineTL 255 420 255 450 $C.Black 0.85 $true | Out-Null
    ReadableCylinderTL 80 450 350 175 'Run State' 'evidence' $C.GraySoft $C.DarkGray 1.0 'N2' | Out-Null
    LineTL 255 625 255 650 $C.Black 0.85 $true | Out-Null
    ReadableDiamondTL 105 615 300 170 'State-Aware`nRole Router' $C.YellowSoft $C.YellowDark 16 'N3' | Out-Null
    TextTL 55 795 400 110 'Repair · Struct.`nOptimize' 16 $C.YellowDark $true | Out-Null

    # 02 — role-specific context converges to one full-source proposal.
    StepTL 535 295 560 115 'Repair`nCSim / Synth' $C.White $C.CyanDark $true 'N4_REPAIR' | Out-Null
    StepTL 535 425 560 115 'Structural`nCoSim / dataflow' $C.White $C.CyanDark $true 'N4_STRUCT' | Out-Null
    StepTL 535 555 560 115 'Optimization`nQoR-RAG context' $C.White $C.CyanDark $true 'N4_OPT' | Out-Null
    LineTL 815 410 815 425 $C.CyanDark 0.7 $true | Out-Null
    LineTL 815 540 815 555 $C.CyanDark 0.7 $true | Out-Null
    LineTL 815 670 815 690 $C.CyanDark 0.8 $true | Out-Null
    StepTL 535 690 560 90 'LLM Candidate Proposer' $C.Cyan $C.CyanDark $true 'N4_LLM' | Out-Null
    LineTL 815 780 815 800 $C.Black 0.85 $true | Out-Null
    StepTL 535 800 560 90 'Full-Source Candidate' $C.White $C.CyanDark $true 'N4_FULL_SOURCE' | Out-Null

    # 03 — deterministic admission followed by the ordered tool chain.
    StepTL 1210 275 520 160 'Candidate Admission`nExtract → Guards`n→ Budget' $C.YellowSoft $C.YellowDark $true 'N5' | Out-Null
    LineTL 1470 435 1470 440 $C.Black 0.85 $true | Out-Null
    RectTL 1210 440 520 350 '' $C.White $C.BlueDark 16 $false 1.0 1 10 'N6' | Out-Null
    TextTL 1240 455 460 68 'Validation Chain' 18 $C.BlueDark $true | Out-Null
    TextTL 1240 525 460 260 'Interface → CSim`nSynth → Frequency`nCapacity`nRequired CoSim*`nMetric Completeness' 16 $C.Black $false | Out-Null
    LineTL 1470 790 1470 800 $C.BlueDark 0.85 $true | Out-Null
    StepTL 1220 800 500 105 'Candidate QoR Evidence' $C.Blue $C.BlueDark $true 'Q2' | Out-Null
    # 04 — two semantically distinct promotion paths.
    ReadableDiamondTL 1945 275 400 120 'Candidate Role?' $C.White $C.GreenDark 16 'N7_ROLE' | Out-Null
    StepTL 1810 415 340 160 'Restore`nValidity`nRepair/Struct.' $C.White $C.GreenDark $true | Out-Null
    StepTL 2160 415 300 160 'QoR Improvement`nOptimization' $C.White $C.GreenDark $true | Out-Null
    LineTL 1980 575 1980 590 $C.Green 1.0 $true | Out-Null
    LineTL 2310 575 2310 590 $C.GreenDark 1.0 $true | Out-Null
    StepTL 1830 600 300 75 'Full Pass' $C.White $C.GreenDark $true | Out-Null
    StepTL 2160 600 300 75 'Full Pass' $C.White $C.GreenDark $true | Out-Null
    LineTL 1980 700 1980 710 $C.Green 1.0 $true | Out-Null
    StepTL 1830 710 300 110 'Establish`nFallback' $C.Green $C.GreenDark $true 'N7_RESTORE' | Out-Null
    LineTL 2310 700 2310 715 $C.GreenDark 1.0 $true | Out-Null
    ReadableDiamondTL 2160 715 300 120 '' $C.White $C.GreenDark 16 'Q3' | Out-Null
    TextTL 2130 675 360 165 'Q_HW`nPromotion`nGate' 16 $C.GreenDark $true | Out-Null
    LineTL 1980 820 1980 840 $C.Green 1.4 $true | Out-Null
    LineTL 2310 835 2310 845 $C.Green 1.4 $true | Out-Null
    ReadableCylinderTL 1900 840 490 65 'Verified Fallback' '' $C.GreenSoft $C.GreenDark 1.4 'N8' | Out-Null
    # 05 — final deliverables cross one-way into the evaluator boundary.
    StepTL 2555 315 360 175 'Final Artifacts`nkernel · report`nevidence' $C.GreenSoft $C.GreenDark $true 'N12' | Out-Null
    LineTL 2735 490 2735 525 $C.Black 0.9 $true | Out-Null
    RectTL 2545 525 380 375 '' 'none' $C.Gray 16 $false 1.0 2 14 'N13_BOUNDARY' | Out-Null
    TextTL 2560 535 350 120 'Evaluator`nTrust Boundary' 16 $C.DarkGray $true | Out-Null
    RectTL 2560 660 350 225 'Independent`nEvaluator`nFinal QoR Score' $C.White $C.DarkGray 16 $true 0.9 1 8 'N13' | Out-Null
    # Main stage-to-stage flow. Elbows are confined to inter-panel gaps.
    LineTL 405 770 480 770 $C.Black 0.9 $false | Out-Null
    LineTL 480 770 480 350 $C.Black 0.9 $false | Out-Null
    LineTL 480 350 535 350 $C.Black 0.9 $true | Out-Null
    LineTL 1045 838 1150 838 $C.Black 0.9 $false | Out-Null
    LineTL 1150 838 1150 370 $C.Black 0.9 $false | Out-Null
    LineTL 1150 370 1210 370 $C.Black 0.9 $true | Out-Null
    LineTL 1670 836 1790 836 $C.Black 0.9 $false | Out-Null
    LineTL 1790 836 1790 375 $C.Black 0.9 $false | Out-Null
    LineTL 1790 375 1985 375 $C.Black 0.9 $true | Out-Null
    LineTL 2390 852 2500 852 $C.Black 0.9 $false | Out-Null
    LineTL 2500 852 2500 418 $C.Black 0.9 $false | Out-Null
    LineTL 2500 418 2555 418 $C.Black 0.9 $true | Out-Null

    # Positive state loop and bootstrap validation.
    LineTL 2145 840 2145 174 $C.GreenDark 0.8 $false 10 | Out-Null
    LineTL 2145 174 255 174 $C.GreenDark 0.8 $false 10 | Out-Null
    LineTL 255 174 255 463 $C.GreenDark 0.8 $true 10 | Out-Null
    TextTL 955 156 300 60 'update best' 16 $C.GreenDark $false $true | Out-Null
    LineTL 430 550 475 550 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 475 550 475 925 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 475 925 1470 925 $C.DarkGray 0.7 $false 10 | Out-Null
    LineTL 1470 925 1470 755 $C.DarkGray 0.7 $true 10 | Out-Null
    TextTL 720 900 220 60 'bootstrap' 16 $C.DarkGray $false $true | Out-Null

    # Fast within-run feedback band.
    SimplePanelTL 490 960 650 235 'QoR-RAG' $C.CyanSoft $C.CyanDark 0.9 2 'N10' | Out-Null
    StepTL 535 1055 560 120 'Public evidence context`nOptimization only' $C.White $C.CyanDark $true | Out-Null

    SimplePanelTL 1160 960 1330 235 'Failure Reflection' $C.YellowSoft $C.YellowDark 0.9 1 'N9' | Out-Null
    StepTL 1210 1060 350 100 'diagnostics' $C.White $C.YellowDark $true | Out-Null
    StepTL 1650 1060 350 100 'candidate diff' $C.White $C.YellowDark $true | Out-Null
    StepTL 2090 1060 350 100 'next constraint' $C.White $C.YellowDark $true | Out-Null
    LineTL 1560 1110 1650 1110 $C.YellowDark 0.7 $true | Out-Null
    LineTL 2000 1110 2090 1110 $C.YellowDark 0.7 $true | Out-Null

    # Admission/validation failures and measured QoR rejection feed reflection.
    LineTL 1470 882 1470 940 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1470 940 1470 960 $C.RedDark 1.0 $true 2 | Out-Null
    LineTL 2310 835 2310 940 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2310 940 2310 960 $C.RedDark 1.0 $true 2 | Out-Null
    TextTL 2050 850 400 110 'Measured QoR`nRejection' 16 $C.RedDark $true $true | Out-Null

    # Failure reflection influences role, proposal constraints, and retrieval.
    LineTL 1210 1160 1150 1160 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1150 1160 1150 1210 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1150 1210 255 1210 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 255 1210 255 865 $C.RedDark 1.0 $true 2 | Out-Null
    LineTL 1500 1195 1500 1220 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1500 1220 815 1220 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 815 1220 815 884 $C.RedDark 1.0 $true 2 | Out-Null
    LineTL 1160 1110 1140 1110 $C.RedDark 1.0 $true 2 | Out-Null

    # Fallback baseline enters QoR-RAG; retrieval returns only to optimization.
    LineTL 2145 905 2145 930 $C.BlueDark 0.8 $false 10 | Out-Null
    LineTL 2145 930 815 930 $C.BlueDark 0.8 $false 10 | Out-Null
    LineTL 815 930 815 960 $C.BlueDark 0.8 $true 10 | Out-Null
    TextTL 1450 900 300 60 'Baseline QoR' 16 $C.BlueDark $false $true | Out-Null
    LineTL 490 1110 455 1110 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 455 1110 455 581 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 455 581 535 581 $C.Blue 1.0 $true 2 | Out-Null
    # Public evidence slow loop.
    SimplePanelTL 40 1250 2450 270 'Public Evidence Loop' $C.GraySoft $C.Blue 1.0 2 'N11' | Out-Null
    StepTL 110 1370 600 110 'Fully Verified Public Run Report' $C.White $C.BlueDark $true 'N11_REPORT' | Out-Null
    StepTL 930 1370 600 110 'Evidence Curation' $C.White $C.BlueDark $true 'N11_CURATE' | Out-Null
    ReadableCylinderTL 1750 1350 650 145 'Public Evidence Store' 'verified public cases' $C.BlueSoft $C.BlueDark 1.0 'N11_STORE' | Out-Null
    LineTL 710 1425 930 1425 $C.Blue 1.0 $true 2 | Out-Null
    LineTL 1530 1425 1750 1425 $C.Blue 1.0 $true 2 | Out-Null

    # Final public report enters the store; the store supports future-run retrieval.
    LineTL 2735 505 2735 1230 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 2735 1230 410 1230 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 410 1230 410 1370 $C.Blue 1.0 $true 2 | Out-Null
    LineTL 2075 1495 2075 1530 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 2075 1530 815 1530 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 815 1530 815 1195 $C.Blue 1.0 $true 2 | Out-Null
}







