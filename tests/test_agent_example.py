"""The copyable example uses disk memory and never needs a provider by default."""
import httpx

from examples import agent_memory as example


def test_two_sessions_and_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("offline demo must not use a provider")))
    path = tmp_path / "brain"
    nid = example.capture_session(path)
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    context, messages = example.next_session(path)
    assert context["nodes"] == [nid]
    assert example.PREFERENCE in context["context"]
    assert context["context"] in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": example.QUESTION}
    assert "[memory:" + nid + "]" in example.offline_answer(context)
    assert before == {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_optional_model_receives_same_prompt(tmp_path, monkeypatch):
    example.capture_session(tmp_path / "brain")
    _, messages = example.next_session(tmp_path / "brain")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.invalid/v1")
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": "model answer"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert example.model_answer(messages, "chosen-model") == "model answer"
    assert seen["url"] == "https://provider.invalid/v1/chat/completions"
    assert seen["json"] == {"model": "chosen-model", "messages": messages}
