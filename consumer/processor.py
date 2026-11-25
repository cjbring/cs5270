import logging
from .models import WidgetRequest
from .storage import WidgetStorageStrategy

logger = logging.getLogger(__name__)


class RequestProcessor:
    def __init__(self, storage_strategy: WidgetStorageStrategy):
        self.storage_strategy = storage_strategy

    def process(self, request: WidgetRequest) -> None:
        if request.type in ("create", "WidgetCreateRequest"):
            self.storage_strategy.store_widget(request)
        elif request.type in ("delete", "WidgetDeleteRequest"):
            self.storage_strategy.delete_widget(request)
        elif request.type in ("update", "WidgetUpdateRequest"):
            self.storage_strategy.update_widget(request)
        else:
            logger.error(f"Unknown request type '{request.type}'")