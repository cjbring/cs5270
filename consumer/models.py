import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class WidgetRequest:
    type: str
    request_id: str
    widget_id: str
    owner: str
    label: Optional[str] = None
    description: Optional[str] = None
    other_attributes: Optional[List[Dict[str, str]]] = None

    @classmethod
    def from_json(cls, json_str: str) -> "WidgetRequest":
        data = json.loads(json_str)
        for field in ("type", "requestId", "widgetId", "owner"):
            if field not in data:
                raise ValueError(f"Missing required field: {field}")
        
        return cls(
            type=data["type"],
            request_id=data["requestId"],
            widget_id=data["widgetId"],
            owner=data["owner"],
            label=data.get("label"),
            description=data.get("description"),
            other_attributes=data.get("otherAttributes", [])
        )

    def to_widget_dict(self) -> Dict:
        return {
            "id": self.widget_id,
            "owner": self.owner,
            "label": self.label,
            "description": self.description,
            "otherAttributes": self.other_attributes or []
        }

    def get_s3_key(self) -> str:
        formatted_owner = re.sub(r"\s+", "-", self.owner.strip()).lower()
        return f"widgets/{formatted_owner}/{self.widget_id}"