from __future__ import annotations

import asyncio
from typing import Any

from agentic_survey.agents.validator import Validator
from agentic_survey.domain.outline import OutlineArtifact
from agentic_survey.llm.client import ChatCompletion
from agentic_survey.repository import InMemoryRepository


class _RepairingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def chat(self, *args: Any, **kwargs: Any) -> ChatCompletion:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return ChatCompletion(
                content=(
                    '{"coverage_score":0.0,"quality_score":0.8,'
                    '"follow_up_needed":true,"follow_up_reason":"needs repair",'
                    '"is_spam":false,"extracted_concepts":[{"label":"tape archive","0.0"}]'
                )
            )
        return ChatCompletion(
            content=(
                '{"coverage_score":0.4,"quality_score":0.8,'
                '"follow_up_needed":true,"follow_up_reason":"needs follow-up",'
                '"is_spam":false,'
                '"extracted_concepts":[{"label":"tape archive","type":"infrastructure"}],'
                '"extracted_relations":[]}'
            )
        )


def test_validator_repairs_malformed_json_with_reasoning_disabled() -> None:
    repo = InMemoryRepository()
    campaign = repo.create_campaign(title="Validator repair", min_n=1, max_n=3)
    llm = _RepairingLLM()
    validator = Validator(llm=llm)  # type: ignore[arg-type]

    result = asyncio.run(
        validator.validate(
            campaign=campaign,
            content="The tape archive handoff drops metadata.",
            outline=OutlineArtifact(
                research_question="What breaks in data workflows?",
                objectives=["Find concrete workflow pain."],
            ),
            previous_agent_question="Where does the handoff break?",
        )
    )

    assert result.coverage_score == 0.4
    assert result.extracted_concepts == [
        {"label": "tape archive", "type": "infrastructure"}
    ]
    assert len(llm.calls) == 2
    assert llm.calls[0]["disable_reasoning"] is True
    assert llm.calls[0]["max_tokens"] == 1024
    assert llm.calls[1]["disable_reasoning"] is True
    assert llm.calls[1]["max_tokens"] == 1024
