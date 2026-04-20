from agentic_survey.agents.base import BaseAgent, PromptBundle


class Analyst(BaseAgent):
    name = "analyst"
    prompt = PromptBundle(
        system=(
            "Cluster themes, update saturation signals, and consolidate the campaign graph."
        ),
        purpose="Background analysis across transcripts and knowledge artifacts.",
    )
