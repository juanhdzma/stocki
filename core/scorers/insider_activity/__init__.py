from core.scorers.base import aggregate
from core.scorers.insider_activity import insider_3m, insider_1y

_WEIGHTS = {
    "insider_3m": 0.60,
    "insider_1y": 0.40,
}


def compute(snapshot: dict, funds: list[dict]) -> dict:
    sub = {
        "insider_3m": insider_3m.score(snapshot, funds),
        "insider_1y": insider_1y.score(snapshot, funds),
    }
    return aggregate(sub, _WEIGHTS)
