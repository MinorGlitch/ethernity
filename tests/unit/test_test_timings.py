"""CI timing summaries keep expensive work and incomplete runs visible."""

from scripts.summarize_test_timings import summarize


def test_timings_combine_workers_and_report_failures_and_skips(tmp_path):
    first = tmp_path / "one.xml"
    first.write_text("""<testsuites><testsuite>
      <testcase classname="tests.ui.workflows.test_navigation" name="focus" time="4.5"/>
      <testcase classname="tests.unit.test_frames" name="invalid" time="0.5"><failure/></testcase>
    </testsuite></testsuites>""")
    second = tmp_path / "two.xml"
    second.write_text("""<testsuite>
      <testcase classname="tests.ui.workflows.test_navigation" name="keys[a|b]" time="1.0"/>
      <testcase classname="tests.rendering.test_pdf" name="scan" time="0"><skipped/></testcase>
    </testsuite>""")
    result = summarize([first, second])
    assert "4 cases, 1 failures/errors, 1 skipped" in result
    assert "| UI workflows | 2 | 5.5 | 91.7% |" in result
    assert "| PDF rendering | 1 | 0.0 | 0.0% |" in result
    assert "keys[a&#124;b]" in result
    assert result.index("focus`") < result.index("keys[a&#124;b]`")


def test_empty_timings_do_not_claim_a_successful_run(tmp_path):
    empty = tmp_path / "empty.xml"
    empty.write_text("<testsuite/>")
    assert summarize([]) == summarize([empty]) == "No test timings were produced.\n"
