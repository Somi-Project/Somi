from tool import run


def test_run():
    result = run({"name": "Somi"}, None)
    assert "Hello Somi" in result["message"]
    assert "time" in result
