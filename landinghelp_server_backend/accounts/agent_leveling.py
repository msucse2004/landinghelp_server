from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Optional

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from settlement.models import AgentAppointmentRequest


@dataclass(frozen=True)
class LevelThreshold:
    level: str
    min_score: float


DEFAULT_LEVEL_THRESHOLDS: Iterable[LevelThreshold] = (
    LevelThreshold(User.AgentLevel.PLATINUM, 90.0),
    LevelThreshold(User.AgentLevel.DIAMOND, 75.0),
    LevelThreshold(User.AgentLevel.GOLD, 60.0),
    LevelThreshold(User.AgentLevel.SILVER, 40.0),
    LevelThreshold(User.AgentLevel.BRONZE, 0.0),
)


def normalize_accept_rate(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    v = float(value)
    if v < 0:
        return 0.0
    if v > 1:
        v = v / 100.0
    return max(0.0, min(v, 1.0))


def derive_accept_rate(agent: User) -> float:
    if agent.accept_rate is not None:
        return normalize_accept_rate(float(agent.accept_rate))

    stats = AgentAppointmentRequest.objects.filter(agent=agent).aggregate(
        total=Count('id'),
        confirmed=Count('id', filter=Q(status='CONFIRMED')),
        cancelled=Count('id', filter=Q(status='CANCELLED')),
    )
    total = int(stats.get('total') or 0)
    cancelled = int(stats.get('cancelled') or 0)
    confirmed = int(stats.get('confirmed') or 0)
    effective_total = max(total - cancelled, 0)
    if not effective_total:
        return 0.0
    return normalize_accept_rate(confirmed / effective_total)


def derive_completed_service_count(agent: User) -> int:
    return int(
        AgentAppointmentRequest.objects.filter(agent=agent, status='CONFIRMED').count()
    )


def derive_rating_avg(agent: User) -> float:
    summary = agent.get_agent_rating_summary() or {}
    return float(summary.get('avg') or 0.0)


def calculate_agent_level_score(completed_count: int, rating_avg: float, accept_rate: float) -> float:
    completed_norm = min(max(float(completed_count), 0.0), 100.0) / 100.0
    rating_norm = min(max(float(rating_avg), 0.0), 5.0) / 5.0
    accept_norm = normalize_accept_rate(accept_rate)

    score = (
        completed_norm * 40.0
        + rating_norm * 35.0
        + accept_norm * 25.0
    )
    return round(score, 2)


def resolve_agent_level(score: float, thresholds: Optional[Iterable[LevelThreshold]] = None) -> str:
    active_thresholds = tuple(thresholds or DEFAULT_LEVEL_THRESHOLDS)
    for threshold in active_thresholds:
        if score >= threshold.min_score:
            return threshold.level
    return User.AgentLevel.BRONZE


def build_level_constraints(level: str) -> Dict[str, object]:
    constraints = {
        User.AgentLevel.BRONZE: {
            'max_active_assignments': 5,
            'lsa_auto_priority_weight': 0.8,
        },
        User.AgentLevel.SILVER: {
            'max_active_assignments': 8,
            'lsa_auto_priority_weight': 1.0,
        },
        User.AgentLevel.GOLD: {
            'max_active_assignments': 12,
            'lsa_auto_priority_weight': 1.15,
        },
        User.AgentLevel.DIAMOND: {
            'max_active_assignments': 16,
            'lsa_auto_priority_weight': 1.3,
        },
        User.AgentLevel.PLATINUM: {
            'max_active_assignments': 20,
            'lsa_auto_priority_weight': 1.5,
        },
    }
    return constraints.get(level, constraints[User.AgentLevel.BRONZE]).copy()


def evaluate_agent_level(agent: User, persist: bool = True) -> Dict[str, object]:
    if agent.role != User.Role.AGENT:
        return {'ok': False, 'reason': 'not_agent'}

    completed_count = derive_completed_service_count(agent)
    rating_avg = derive_rating_avg(agent)
    accept_rate = derive_accept_rate(agent)
    score = calculate_agent_level_score(
        completed_count=completed_count,
        rating_avg=rating_avg,
        accept_rate=accept_rate,
    )
    level = resolve_agent_level(score)
    constraints = build_level_constraints(level)

    snapshot = {
        'ok': True,
        'agent_id': agent.id,
        'level': level,
        'score': score,
        'completed_service_count': completed_count,
        'rating_avg': round(rating_avg, 2),
        'accept_rate': round(accept_rate, 4),
        'constraints': constraints,
    }

    if persist:
        agent.agent_level = level
        agent.agent_level_score = Decimal(str(score))
        agent.agent_completed_service_count = completed_count
        agent.agent_rating_avg_snapshot = Decimal(str(round(rating_avg, 2)))
        agent.agent_accept_rate_snapshot = Decimal(str(round(accept_rate, 4)))
        agent.agent_level_constraints = constraints
        agent.agent_level_last_evaluated_at = timezone.now()
        agent.save(update_fields=[
            'agent_level',
            'agent_level_score',
            'agent_completed_service_count',
            'agent_rating_avg_snapshot',
            'agent_accept_rate_snapshot',
            'agent_level_constraints',
            'agent_level_last_evaluated_at',
        ])

    return snapshot


def evaluate_all_agents() -> Dict[str, int]:
    total = 0
    for agent in User.objects.filter(role=User.Role.AGENT).only('id', 'role', 'accept_rate'):
        evaluate_agent_level(agent, persist=True)
        total += 1
    return {'processed': total}
