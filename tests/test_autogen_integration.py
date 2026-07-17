"""
REAL-LLM integration test — AutoGen (VapAutoGen) via OpenRouter.

GATED: AutoGen (the `ag2` package) is not installed by default; this skips at
collection until `pip install ag2`. When installed, it runs a 2-agent AutoGen
conversation through OpenRouter and asserts the traced graph.

    pip install ag2 && pytest tests/test_autogen_integration.py -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("autogen")

from _real_llm import KEY, MODEL, BASE_URL  # noqa: E402

import vapviz  # noqa: E402
from vapviz.backends.sqlite import SqliteStore  # noqa: E402
from vapviz.integrations.autogen import VapAutoGen  # noqa: E402

pytestmark = pytest.mark.skipif(
    not KEY, reason="OPENROUTER_API_KEY not set — real-LLM integration tests skipped"
)


def test_autogen_conversation_is_traced(tmp_path):
    from autogen import ConversableAgent

    llm_config = {"config_list": [{
        "model": MODEL, "api_key": KEY, "base_url": BASE_URL,
    }], "temperature": 0}

    store = SqliteStore(str(tmp_path / "autogen.db"))
    tracer = vapviz.Tracer(store=store)

    assistant = ConversableAgent(
        name="assistant", llm_config=llm_config,
        system_message="Answer in one short sentence.",
    )
    user = ConversableAgent(
        name="user", llm_config=False, human_input_mode="NEVER", max_consecutive_auto_reply=0,
    )

    with tracer.trace("AutoGen conversation") as run:
        listener = VapAutoGen(run)
        try:
            user.initiate_chat(assistant, message="What is agent tracing?", max_turns=1)
        finally:
            listener.detach()

    g = store.get_graph(run.run_id)
    assert not [n for n in g.nodes if n.status.value == "running"]
    assert any(n.kind.value == "llm" for n in g.nodes), "no llm node traced"
