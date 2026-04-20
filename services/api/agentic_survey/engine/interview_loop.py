from dataclasses import dataclass, field


@dataclass(slots=True)
class ValidationResult:
    coverage_score: float = 0.0
    quality_score: float = 0.0
    follow_up_needed: bool = False
    follow_up_reason: str = ""
    is_spam: bool = False


@dataclass(slots=True)
class InterviewTurn:
    role: str
    content: str
    index: int
    validation: ValidationResult | None = None


@dataclass(slots=True)
class InterviewState:
    persona_name: str
    objective_cursor: int = 0
    turns: list[InterviewTurn] = field(default_factory=list)


class InterviewLoop:
    def __init__(self, state: InterviewState) -> None:
        self.state = state

    def append_turn(self, role: str, content: str) -> InterviewTurn:
        turn = InterviewTurn(role=role, content=content, index=len(self.state.turns))
        self.state.turns.append(turn)
        return turn

    def attach_validation(self, turn_index: int, result: ValidationResult) -> None:
        self.state.turns[turn_index].validation = result
