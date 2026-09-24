import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("demo_server", Path(__file__).parent.parent / "demo" / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_demo_processes_ticket_without_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    status, body = server.process({"tickets": [{"id": "D1", "message": "Which asset will go up today?"}]})
    assert status == 200 and body["results"][0]["intent"] == "trading_advice_request"
    assert list(tmp_path.iterdir()) == []


def test_demo_rejects_bad_payloads():
    assert server.process("nope")[0] == 400
    assert server.process({"tickets": "x"})[0] == 400
    assert server.process({"tickets": [{"id": f"T{i}", "message": "hi"} for i in range(51)]})[0] == 400
    dup = [{"article_id": "A", "title": "t", "body": "b"}] * 2
    assert server.process({"tickets": [], "kb": dup})[0] == 422
