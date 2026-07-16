from llm4hls.report import parse_csynth_xml


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
