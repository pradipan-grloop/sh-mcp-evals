"""The live progress line: drawn only on a terminal, and cleared before results are printed."""
import io

from evalkit.progress import Progress


def test_line_shows_steps_calls_and_what_is_happening():
    p = Progress(stream=io.StringIO(), enabled=True)
    p.start("R21 run 1/3", 20)
    p.step(5)
    p.tool("get_learner")
    p.tool("get_learner")
    line = p.line()
    assert "R21 run 1/3" in line and "step 5/20" in line and "2 tool calls" in line
    assert "calling get_learner" in line
    assert line.count("█") == 5 and line.count("░") == 15  # 5 of 20 steps


def test_judging_and_stop_clear_the_line():
    out = io.StringIO()
    p = Progress(stream=out, enabled=True)
    p.start("S01 run 1/1", 20)
    p.judging()
    assert "judge grading" in p.line()
    p.stop()
    assert out.getvalue().endswith("\r")  # the PASS line then prints over a blank line


def test_not_a_terminal_draws_nothing():
    out = io.StringIO()  # StringIO is not a tty: as when output goes to a file or CI
    p = Progress(stream=out)
    p.start("R01 run 1/1", 20)
    p.step(1)
    p.tool("get_health")
    p.stop()
    assert out.getvalue() == ""
