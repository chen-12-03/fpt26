function MacroPanelTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title, [string]$fill, [string]$line,
    [string]$id = ''
) {
    $panel = RectTL $x $y $w $h '' $fill $line 16 $false 1.1 1 18 $id
    RectTL ($x + 1) ($y + 1) ($w - 2) 80 '' $line $line 16 $false 0 1 16 | Out-Null
    TextTL ($x + 20) ($y + 6) ($w - 40) 70 $title 20 $C.White $true $false 0 | Out-Null
    return $panel
}

function SectionLabelTL(
    [double]$x, [double]$y, [double]$w,
    [string]$number, [string]$title, [string]$color
) {
    TextTL $x $y 70 66 $number 16 $color $true $false 0 | Out-Null
    TextTL ($x + 72) $y ($w - 72) 66 $title 16 $color $true $false 0 | Out-Null
    LineTL $x ($y + 68) ($x + $w) ($y + 68) $color 0.55 $false | Out-Null
}

function DecisionWithLabelTL(
    [double]$x, [double]$y, [double]$side,
    [string]$shortText, [string]$label,
    [string]$fill, [string]$line, [string]$id = ''
) {
    $body = RectTL $x $y $side $side '' $fill $line 16 $false 0.95 1 0 $id
    Set-Cell $body 'Angle' '45 deg'
    TextTL ($x - 20) ($y + 0.16 * $side) ($side + 40) (0.68 * $side) $shortText 13 $C.Black $true | Out-Null
    if ($label -ne '') {
        TextTL ($x - 90) ($y + $side + 8) ($side + 180) 105 $label 14 $line $true | Out-Null
    }
    return $body
}

function MiniHeaderCardTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$header, [string]$body,
    [string]$fill, [string]$line, [string]$id = ''
) {
    $shape = RectTL $x $y $w $h '' $fill $line 16 $false 0.8 1 10 $id
    TextTL ($x + 12) ($y + 8) ($w - 24) 58 $header 16 $line $true $false 0 | Out-Null
    TextTL ($x + 12) ($y + 68) ($w - 24) ($h - 78) $body 14 $C.Black $false $false 0 | Out-Null
    return $shape
}

function ClearCylinderTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title, [string]$detail,
    [string]$fill, [string]$line, [string]$id = ''
) {
    $capH = 30
    $body = RectTL $x ($y + 15) $w ($h - 30) '' $fill $line 16 $false 1.0 1 0 $id
    OvalTL $x $y $w $capH '' $fill $line 16 $false 1.0 | Out-Null
    OvalTL $x ($y + $h - $capH) $w $capH '' $fill $line 16 $false 1.0 | Out-Null
    RectTL ($x + 1) ($y + 16) ($w - 2) ($h - 32) '' $fill 'none' 16 $false 0 1 0 | Out-Null
    TextTL ($x + 12) ($y + 12) ($w - 24) 100 $title 14 $C.Black $true | Out-Null
    TextTL ($x + 12) ($y + 120) ($w - 24) 45 $detail 13 $C.DarkGray | Out-Null
    return $body
}

function ClearDocumentTL(
    [double]$x, [double]$y, [double]$w, [double]$h,
    [string]$title, [string]$detail,
    [string]$fill, [string]$line, [string]$id = ''
) {
    $s = RectTL $x $y $w $h '' $fill $line 16 $false 0.9 1 7 $id
    $fold = 30
    LineTL ($x + $w - $fold) $y ($x + $w - $fold) ($y + $fold) $line 0.6 $false | Out-Null
    LineTL ($x + $w - $fold) ($y + $fold) ($x + $w) ($y + $fold) $line 0.6 $false | Out-Null
    TextTL ($x + 12) ($y + 8) ($w - 24) 110 $title 14 $C.Black $true | Out-Null
    TextTL ($x + 12) ($y + 120) ($w - 24) ($h - 125) $detail 13 $C.DarkGray | Out-Null
    return $s
}
function Draw-WorkflowV3 {
    # V3 uses one dominant core workflow and two explicit lower support loops.
    # Dedicated lanes between the macro-panels carry rejection and across-run evidence.
    RectTL 0 0 $RefW $RefH '' $C.White 'none' 16 $false 0 1 0 | Out-Null

    # Title and compact legend.
    RectTL 28 24 2944 126 '' $C.GraySoft $C.GrayMid 16 $false 0.6 1 14 | Out-Null
    TextTL 58 38 1640 82 'Evidence-Governed Verified-Candidate Loop' 22 $C.Black $true $false 0 | Out-Null
    TextTL 58 98 1540 52 'LLM proposes; measured evidence decides.' 13 $C.DarkGray $false $false 0 | Out-Null
    LineTL 1830 64 1915 64 $C.Black 0.9 $true 1 | Out-Null
    TextTL 1932 35 180 58 'flow' 15 $C.DarkGray $false $false 0 | Out-Null
    LineTL 1830 112 1915 112 $C.RedDark 1.1 $true 2 | Out-Null
    TextTL 1932 83 250 58 'within-run' 15 $C.RedDark $false $false 0 | Out-Null
    LineTL 2255 64 2340 64 $C.Blue 1.0 $true 2 | Out-Null
    TextTL 2357 35 270 58 'across-run' 15 $C.BlueDark $false $false 0 | Out-Null
    LineTL 2255 112 2340 112 $C.Green 1.5 $true 1 | Out-Null
    TextTL 2357 83 430 58 'fallback update' 15 $C.GreenDark $false $false 0 | Out-Null

    # A — core workflow.
    MacroPanelTL 40 175 2920 745 'A: VERIFIED-CANDIDATE LOOP CORE' $C.GraySoft $C.DarkGray 'A_CORE' | Out-Null

    SectionLabelTL 80 268 510 '01' 'INITIALIZE' $C.DarkGray
    SectionLabelTL 650 268 660 '02' 'PROPOSE' $C.CyanDark
    SectionLabelTL 1390 268 590 '03' 'ADMIT + VALIDATE' $C.BlueDark
    SectionLabelTL 2070 268 540 '04' 'PROMOTE SAFELY' $C.GreenDark
    SectionLabelTL 2620 268 300 '05' 'OUTPUT' $C.DarkGray

    # 01 — shared state and a compact decision. The diamond carries only "Role?".
    StepTL 90 345 340 115 'Task Contract`n+ Starter' $C.White $C.DarkGray $true 'N1' | Out-Null
    LineTL 260 460 260 495 $C.Black 0.85 $true | Out-Null
    ClearCylinderTL 100 495 320 160 'Run State' 'kernel · evidence' $C.GraySoft $C.DarkGray 1.0 'N2' | Out-Null
    LineTL 420 575 485 575 $C.Black 0.85 $true | Out-Null
    DecisionWithLabelTL 475 520 100 'R?' 'State-aware role router' $C.YellowSoft $C.YellowDark 'N3' | Out-Null
    RectTL 95 745 485 100 'Repair · Structural`nOptimization' $C.YellowSoft $C.YellowDark 14 $true 0.6 1 18 | Out-Null

    # 02 — one selected context rather than three parallel arrows in the stage gutter.
    MiniHeaderCardTL 660 350 330 300 'CONTEXT' 'Repair · CSim/Synth`nStructural · flow`nOptimize · QoR-RAG' $C.CyanSoft $C.CyanDark 'N4_CONTEXT' | Out-Null
    LineTL 573 574 630 574 $C.Black 0.8 $false | Out-Null
    LineTL 630 569 630 500 $C.Black 0.8 $false | Out-Null
    LineTL 630 500 660 500 $C.Black 0.8 $true | Out-Null
    TextTL 580 430 70 58 '' 14 $C.DarkGray $false $true | Out-Null

    StepTL 1010 380 270 120 'LLM`nPROPOSER' $C.Cyan $C.CyanDark $true 'N4_LLM' | Out-Null
    LineTL 990 500 1000 500 $C.Black 0.8 $false | Out-Null
    LineTL 1000 500 1000 440 $C.Black 0.8 $false | Out-Null
    LineTL 1000 440 1010 440 $C.Black 0.8 $true | Out-Null
    LineTL 1145 500 1145 545 $C.Black 0.85 $true | Out-Null
    StepTL 1010 545 270 115 'Full-Source`nCandidate' $C.White $C.CyanDark $true 'N4_FULL_SOURCE' | Out-Null
    RectTL 675 720 605 78 'proposal only  ·  no promotion' $C.White $C.CyanDark 14 $true 0.55 2 18 | Out-Null

    # 03 — deterministic admission followed by one ordered validation chain.
    StepTL 1410 350 540 130 'Candidate Admission`nextract · guard · budget' $C.YellowSoft $C.YellowDark $true 'N5' | Out-Null
    ElbowArrow 1280 598 1345 415 1410 415 $C.Black 0.85 1
    LineTL 1680 480 1680 490 $C.Black 0.85 $true | Out-Null
    MiniHeaderCardTL 1410 490 540 285 'VALIDATION CHAIN' 'Interface · CSim · Synth`nFrequency · Capacity`nRequired CoSim*`nMetric completeness' $C.BlueSoft $C.BlueDark 'N6' | Out-Null
    TextTL 1770 700 165 50 '' 13 $C.DarkGray $false $true | Out-Null
    LineTL 1680 775 1680 795 $C.BlueDark 0.9 $true | Out-Null
    RectTL 1410 795 540 100 'Measured QoR Evidence' $C.Blue $C.BlueDark 15 $true 0.9 1 16 'Q2' | Out-Null

    # 04 — the second diamond also carries only the compact metric name.
    TextTL 2090 325 205 60 '' 13 $C.GreenDark $false $true | Out-Null
    DecisionWithLabelTL 2243 343 96 'R?' '' $C.GreenSoft $C.GreenDark 'N7' | Out-Null
    ElbowArrow 1950 837 2030 391 2243 391 $C.Black 0.9 1
    LineTL 2291 432 2170 480 $C.Black 0.8 $true | Out-Null
    LineTL 2291 432 2450 480 $C.Black 0.8 $true | Out-Null
    TextTL 2050 415 240 60 '' 14 $C.GreenDark $true | Out-Null
    TextTL 2340 420 240 60 '' 14 $C.GreenDark $true | Out-Null

    RectTL 2050 480 240 150 'Restore`nValidity`nrepair/struct.' $C.White $C.GreenDark 13 $true 0.65 1 7 'N8_REPAIR' $C.White $C.GreenDark $true 'N8_REPAIR' | Out-Null
    RectTL 2340 480 240 150 'Improve QoR`noptimize' $C.White $C.GreenDark 13 $true 0.65 1 7 'N8_OPT' $C.White $C.GreenDark $true 'N8_OPT' | Out-Null
    LineTL 2170 630 2170 660 $C.Green 1.0 $true | Out-Null
    LineTL 2460 630 2460 660 $C.Green 1.0 $true | Out-Null
    RectTL 2070 660 200 68 'PASS' $C.White $C.GreenDark 14 $true 0.65 1 7 'N8_PASS_REPAIR' $C.White $C.GreenDark $true 'N8_PASS_REPAIR' | Out-Null
    RectTL 2360 660 200 68 'PASS' $C.White $C.GreenDark 14 $true 0.65 1 7 'N8_PASS_OPT' $C.White $C.GreenDark $true 'N8_PASS_OPT' | Out-Null
    LineTL 2460 728 2460 746 $C.Green 1.0 $true | Out-Null
    DecisionWithLabelTL 2410 746 100 'Q_HW' '' $C.GreenSoft $C.GreenDark 'N9' | Out-Null
    LineTL 2170 728 2170 832 $C.Green 1.0 $false | Out-Null
    LineTL 2170 842 2160 842 $C.Green 1.0 $true | Out-Null
    LineTL 2410 796 2380 796 $C.Green 1.0 $false | Out-Null
    LineTL 2380 796 2380 832 $C.Green 1.0 $true | Out-Null
    RectTL 2160 790 260 105 'VERIFIED`nFALLBACK' $C.Green $C.GreenDark 14 $true 1.0 1 12 'N10' | Out-Null

    # 05 — delivery and independent evaluation are deliberately separated.
    ClearDocumentTL 2640 350 270 225 'Final Artifacts' 'kernel · report`nevidence' $C.GreenSoft $C.GreenDark 'N11' | Out-Null
    ElbowArrow 2420 842 2605 455 2640 455 $C.Black 0.9 1
    RectTL 2610 610 320 275 '' $C.White $C.Gray 16 $false 0.8 2 12 'TB' | Out-Null
    TextTL 2630 620 280 105 'TRUST`nBOUNDARY' 13 $C.DarkGray $true | Out-Null
    RectTL 2640 735 260 140 'Independent`nEvaluator`nQoR Score' $C.GraySoft $C.DarkGray 13 $true 0.65 1 7 'N12' $C.GraySoft $C.DarkGray $true 'N12' | Out-Null
    LineTL 2775 575 2775 610 $C.DarkGray 0.8 $true 2 | Out-Null

    # State update uses the top bus; it does not consume the 01–02 gutter.
    LineTL 2160 842 2160 900 $C.Green 1.35 $false | Out-Null
    LineTL 2160 900 65 900 $C.Green 1.35 $false | Out-Null
    LineTL 65 900 65 575 $C.Green 1.35 $false | Out-Null
    LineTL 65 575 100 575 $C.Green 1.35 $true | Out-Null
    RectTL 870 872 300 58 'state update' $C.White 'none' 14 $true 0 1 10 | Out-Null

    # Rejection lane in the whitespace between A and B/C.
    LineTL 1950 415 1980 415 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 1980 415 1980 943 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2502 777 2585 777 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2585 778 2585 943 $C.RedDark 1.0 $false 2 | Out-Null
    LineTL 2585 943 1430 943 $C.RedDark 1.0 $true 2 | Out-Null
    RectTL 2140 915 220 58 'rejection' $C.White 'none' 14 $true 0 1 10 | Out-Null

    # B — reflection is a first-class, highly visible within-run loop.
    MacroPanelTL 40 990 1400 515 'B: FAILURE REFLECTION  ·  WITHIN-RUN' $C.RedSoft $C.RedDark 'B_REFLECTION' | Out-Null
    RectTL 90 1085 1300 60 'INPUTS  ·  diagnostics  ·  candidate diff  ·  measured rejection' $C.White $C.RedDark 15 $true 0.65 1 18 | Out-Null
    StepTL 100 1195 330 115 '1  Diagnose`nfailing checks' $C.White $C.RedDark $true 'R1' | Out-Null
    LineTL 430 1252 520 1252 $C.RedDark 1.0 $true | Out-Null
    StepTL 520 1195 340 115 '2  Compare`ncandidate diff' $C.White $C.RedDark $true 'R2' | Out-Null
    LineTL 860 1252 950 1252 $C.RedDark 1.0 $true | Out-Null
    StepTL 950 1195 390 115 '3  Derive`nnext constraint' $C.White $C.RedDark $true 'R3' | Out-Null
    RectTL 100 1365 1240 75 'constraint becomes next-attempt context' $C.RedDark $C.RedDark 16 $true 0.8 1 18 | Out-Null
    LineTL 1145 1310 1145 1365 $C.RedDark 1.0 $true | Out-Null
    LineTL 100 1402 24 1402 $C.RedDark 1.1 $false 2 | Out-Null
    LineTL 24 1402 24 790 $C.RedDark 1.1 $false 2 | Out-Null
    LineTL 24 790 95 790 $C.RedDark 1.1 $true 2 | Out-Null
    # feedback lane ends at the role-options band; it never crosses the router label.
    #
    TextTL 330 875 230 58 '' 14 $C.RedDark $true | Out-Null

    # C — public evidence memory is a separate slow loop.
    MacroPanelTL 1500 990 1460 515 'C: PUBLIC EVIDENCE MEMORY  ·  ACROSS-RUN' $C.BlueSoft $C.BlueDark 'C_MEMORY' | Out-Null
    ClearDocumentTL 1545 1085 325 180 'Verified Run`nReport' 'provenance' $C.White $C.BlueDark 'P1' | Out-Null
    LineTL 1870 1167 1935 1167 $C.Blue 1.0 $true 2 | Out-Null
    RectTL 1935 1090 325 160 'Evidence`nCuration`ncomplete gates' $C.White $C.BlueDark 13 $true 0.65 1 7 'P2' $C.White $C.BlueDark $true 'P2' | Out-Null
    LineTL 2260 1167 2325 1167 $C.Blue 1.0 $true 2 | Out-Null
    ClearCylinderTL 2325 1085 365 175 'Public Evidence`nStore' 'verified cases' $C.BlueSoft $C.BlueDark 1.0 'P3' | Out-Null
    RectTL 1935 1315 325 115 'QoR-RAG`npublic only' $C.White $C.CyanDark 14 $true 0.65 1 7 'P4' $C.White $C.CyanDark $true 'P4' | Out-Null
    ElbowArrow 2507 1250 2507 1372 2260 1372 $C.Blue 1.0 2
    LineTL 1935 1372 1505 1372 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 1505 1372 1505 968 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 1505 968 660 968 $C.Blue 1.0 $false 2 | Out-Null
    LineTL 660 968 660 650 $C.Blue 1.0 $true 2 | Out-Null
    RectTL 1190 940 140 58 'reuse' $C.White 'none' 14 $true 0 1 10 | Out-Null
}
