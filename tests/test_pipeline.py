from src.pipeline.base import Pipeline, Step


class Add(Step):
    name = "add"

    def run(self, ctx):
        ctx["n"] = ctx.get("n", 0) + 1
        return ctx


def test_pipeline_runs_steps_in_order():
    assert Pipeline([Add(), Add()]).run()["n"] == 2
