from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(slots=True)
class PromptBundle:
    system: str
    purpose: str


class BaseAgent:
    name = "base"
    prompt = PromptBundle(system="", purpose="")

    def build_system_prompt(self) -> str:
        return self.prompt.system


@lru_cache(maxsize=None)
def load_prompt_text(filename: str) -> str:
    prompt_path = Path(__file__).with_name("prompts") / filename
    return prompt_path.read_text(encoding="utf-8").strip()
