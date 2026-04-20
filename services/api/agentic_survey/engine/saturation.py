from dataclasses import dataclass


@dataclass(slots=True)
class SaturationSnapshot:
    session_count: int
    theme_count: int
    info_gain: float


def estimate_saturation(session_count: int, theme_count: int) -> SaturationSnapshot:
    info_gain = 0.0 if session_count == 0 else theme_count / session_count
    return SaturationSnapshot(
        session_count=session_count,
        theme_count=theme_count,
        info_gain=info_gain,
    )
