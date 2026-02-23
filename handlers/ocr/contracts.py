from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

OcrMode = Literal["auto", "structured", "general"]
OcrSource = Literal["telegram", "gui", "api"]


@dataclass
class OcrRequest:
    image_paths: List[str]
    prompt: str = ""
    mode: OcrMode = "auto"
    schema_id: Optional[str] = None
    template_id: Optional[str] = None
    source: OcrSource = "api"
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OcrQualityReport:
    coverage: Optional[float] = None
    unk_ratio: float = 0.0
    parse_failures: Dict[str, int] = field(default_factory=dict)
    image_metrics: Dict[str, Any] = field(default_factory=dict)
    escalated: bool = False
    reasons: List[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class OcrResult:
    raw_text: str
    structured_records: Optional[List[Dict[str, Any]]] = None
    structured_text: Optional[str] = None
    exports: Dict[str, str] = field(default_factory=dict)
    quality: OcrQualityReport = field(default_factory=OcrQualityReport)
    provenance: Dict[str, Any] = field(default_factory=dict)
    debug: Dict[str, Any] = field(default_factory=dict)
