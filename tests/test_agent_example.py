"""The copyable example uses disk memory and never needs a provider by default."""
import httpx
import pytest

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
    assert "[memory:" + nid + "]" in example.offline_answer(context, nid)
    assert before == {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_existing_main_memory_does_not_change_preference_citation(tmp_path):
    from graph_engine.brain import Brain, Node
    path = tmp_path / "brain"
    brain = Brain(str(path), mode="local")
    brain.ensure_ready()
    brain.write_node(Node(id="existing-main", text="User prefers astronomy examples.",
                          storage_tier="main", tier_locked=True))
    nid = example.capture_session(path)
    context, _ = example.next_session(path)
    assert context["nodes"] == ["existing-main", nid]
    answer = example.offline_answer(context, nid)
    assert f"[memory:{nid}]" in answer
    assert "[memory:existing-main]" not in answer


@pytest.mark.parametrize("budget", [0, 25])
def test_omitted_or_truncated_preference_is_not_cited(tmp_path, budget):
    from graph_engine.brain import Brain
    from graph_engine.brain_engine import BrainEngine
    from graph_engine.context import build_context
    from graph_engine.embedder import HashEmbedder
    path = tmp_path / "brain"
    nid = example.capture_session(path)
    engine = BrainEngine(Brain(str(path), mode="local"), HashEmbedder())
    context = build_context(engine, example.QUESTION, budget=budget)
    assert example.PREFERENCE not in context["context"]
    assert "[memory:" not in example.offline_answer(context, nid)


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
