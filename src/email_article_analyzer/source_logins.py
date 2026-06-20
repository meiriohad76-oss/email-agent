import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SourceLoginConfirmation:
    status: str
    sources: list[str]


class SourceLoginStore:
    def __init__(self, path: str):
        self.path = Path(path)

    def get(self) -> SourceLoginConfirmation:
        if not self.path.exists():
            return SourceLoginConfirmation(status="action_required", sources=[])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        sources = [str(source) for source in payload.get("sources", [])]
        return SourceLoginConfirmation(status="ready", sources=sources)

    def confirm(self, sources: list[str]) -> SourceLoginConfirmation:
        normalized_sources = sorted({source for source in sources if source})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "sources": normalized_sources,
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                },
                sort_keys=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        return SourceLoginConfirmation(status="ready", sources=normalized_sources)
