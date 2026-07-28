from llm4hls.report import parse_csynth_xml, parse_inferred_directives


def test_parse_csynth_xml_exposes_pipeline_and_loop_metrics(tmp_path) -> None:
    report_path = tmp_path / "csynth.xml"
    report_path.write_text(
        """<profile>
<PerformanceEstimates>
  <PipelineType>loop auto-rewind stp (delay=1 cycles)</PipelineType>
  <SummaryOfTimingAnalysis><EstimatedClockPeriod>3.170</EstimatedClockPeriod></SummaryOfTimingAnalysis>
  <SummaryOfOverallLatency>
    <Best-caseLatency>1027</Best-caseLatency>
    <Average-caseLatency>1027</Average-caseLatency>
    <Worst-caseLatency>1027</Worst-caseLatency>
    <Interval-min>1025</Interval-min><Interval-max>1025</Interval-max>
  </SummaryOfOverallLatency>
  <SummaryOfLoopLatency>
    <VITIS_LOOP_7_1>
      <TripCount>1024</TripCount><Latency>1025</Latency>
      <PipelineII>1</PipelineII><PipelineDepth>3</PipelineDepth>
    </VITIS_LOOP_7_1>
  </SummaryOfLoopLatency>
</PerformanceEstimates>
<AreaEstimates>
  <Resources><LUT>156</LUT><FF>93</FF><DSP>2</DSP><BRAM_18K>0</BRAM_18K><URAM>0</URAM></Resources>
  <AvailableResources><LUT>1000</LUT><FF>1000</FF><DSP>100</DSP><BRAM_18K>100</BRAM_18K><URAM>10</URAM></AvailableResources>
</AreaEstimates>
</profile>"""
    )

    report = parse_csynth_xml(report_path)

    assert report.available == {
        "LUT": 1000,
        "FF": 1000,
        "DSP": 100,
        "BRAM_18K": 100,
        "URAM": 10,
    }
    assert report.pipeline_type == "loop auto-rewind stp (delay=1 cycles)"
    assert report.loop_metrics == [
        {
            "name": "VITIS_LOOP_7_1",
            "trip_count": 1024,
            "latency": 1025,
            "pipeline_ii": 1,
            "pipeline_depth": 3,
        }
    ]


def test_parse_csynth_xml_finds_and_deduplicates_nested_module_loops(tmp_path) -> None:
    report_path = tmp_path / "csynth.xml"
    report_path.write_text(
        """<profile>
<PerformanceEstimates>
  <SummaryOfTimingAnalysis><EstimatedClockPeriod>3.170</EstimatedClockPeriod></SummaryOfTimingAnalysis>
  <SummaryOfOverallLatency>
    <Best-caseLatency>39069</Best-caseLatency><Average-caseLatency>39069</Average-caseLatency>
    <Worst-caseLatency>39069</Worst-caseLatency>
    <Interval-min>39070</Interval-min><Interval-max>39070</Interval-max>
  </SummaryOfOverallLatency>
</PerformanceEstimates>
<AreaEstimates>
  <Resources><LUT>909</LUT><FF>649</FF><DSP>6</DSP><BRAM_18K>0</BRAM_18K><URAM>0</URAM></Resources>
  <AvailableResources><LUT>1000</LUT><FF>1000</FF><DSP>100</DSP><BRAM_18K>100</BRAM_18K><URAM>10</URAM></AvailableResources>
</AreaEstimates>
<ModuleInformation>
  <Module>
    <Name>stencil_Pipeline_stencil_label1_stencil_label2</Name>
    <PerformanceEstimates><SummaryOfLoopLatency>
      <stencil_label1_stencil_label2>
        <Name>stencil_label1_stencil_label2</Name>
        <TripCount>7812</TripCount><Latency>39061</Latency>
        <PipelineII>5</PipelineII><PipelineDepth>7</PipelineDepth>
      </stencil_label1_stencil_label2>
    </SummaryOfLoopLatency></PerformanceEstimates>
  </Module>
  <Module>
    <Name>replicated_stencil_module</Name>
    <PerformanceEstimates><SummaryOfLoopLatency>
      <VITIS_LOOP_10_1>
        <Name>stencil_label1_stencil_label2</Name>
        <TripCount>7812</TripCount><Latency>39061</Latency>
        <PipelineII>5</PipelineII><PipelineDepth>7</PipelineDepth>
      </VITIS_LOOP_10_1>
    </SummaryOfLoopLatency></PerformanceEstimates>
  </Module>
</ModuleInformation>
</profile>"""
    )

    report = parse_csynth_xml(report_path)

    assert report.loop_metrics == [
        {
            "name": "stencil_label1_stencil_label2",
            "trip_count": 7812,
            "latency": 39061,
            "pipeline_ii": 5,
            "pipeline_depth": 7,
        }
    ]


def test_parse_csynth_xml_attaches_vitis_inferred_directives(tmp_path) -> None:
    report_path = tmp_path / "csynth.xml"
    report_path.write_text(
        """<profile>
<PerformanceEstimates>
  <SummaryOfTimingAnalysis><EstimatedClockPeriod>4.0</EstimatedClockPeriod></SummaryOfTimingAnalysis>
  <SummaryOfOverallLatency>
    <Best-caseLatency>16</Best-caseLatency><Average-caseLatency>16</Average-caseLatency>
    <Worst-caseLatency>16</Worst-caseLatency><Interval-min>1</Interval-min><Interval-max>1</Interval-max>
  </SummaryOfOverallLatency>
</PerformanceEstimates>
<AreaEstimates>
  <Resources><LUT>1</LUT><FF>1</FF><DSP>0</DSP><BRAM_18K>0</BRAM_18K><URAM>0</URAM></Resources>
  <AvailableResources><LUT>10</LUT><FF>10</FF><DSP>10</DSP><BRAM_18K>10</BRAM_18K><URAM>10</URAM></AvailableResources>
</AreaEstimates>
</profile>"""
    )
    inferred_path = tmp_path / "inferred_directives.ini"
    inferred_path.write_text(
        """[hls]
# Inferred by Vitis
syn.directive.pipeline=top/middle
syn.directive.loop_flatten=top/outer
syn.directive.pipeline=top/middle
syn.directive.unroll=top/inner
"""
    )

    expected = [
        {
            "kind": "pipeline",
            "target": "top/middle",
            "function": "top",
            "scope": "middle",
            "origin": "vitis_inferred",
        },
        {
            "kind": "loop_flatten",
            "target": "top/outer",
            "function": "top",
            "scope": "outer",
            "origin": "vitis_inferred",
        },
        {
            "kind": "unroll",
            "target": "top/inner",
            "function": "top",
            "scope": "inner",
            "origin": "vitis_inferred",
        },
    ]

    assert parse_inferred_directives(inferred_path) == expected
    assert parse_csynth_xml(
        report_path, inferred_directives_fp=inferred_path
    ).inferred_directives == expected
