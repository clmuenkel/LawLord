from dataclasses import dataclass, field


@dataclass
class CaseFact:
    key: str
    question: str
    priority: int  # 1 = critical, 2 = important, 3 = helpful
    category: str  # "classification", "defense", "severity", "procedural", "context"
    follow_up_condition: dict = field(default_factory=dict)
    options: list[str] = field(default_factory=list)


@dataclass
class OffenseLevel:
    name: str
    classification: str
    jail_range: str
    fine_range: str
    license_impact: str = ""
    conditions: str = ""


@dataclass
class Defense:
    name: str
    description: str
    strength_indicator: str  # "strong", "moderate", "weak"
    required_facts: list[str] = field(default_factory=list)


@dataclass
class CaseTypeKnowledge:
    case_type: str
    display_name: str
    jurisdiction: str
    description: str
    statutes: list[str]
    facts: list[CaseFact]
    offense_levels: list[OffenseLevel]
    common_defenses: list[Defense]
    take_signals: list[str]
    pass_signals: list[str]
    review_signals: list[str]
    keywords: list[str]  # for initial classification from caller's description
