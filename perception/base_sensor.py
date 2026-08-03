from abc import ABC, abstractmethod
from playwright.sync_api import Page

class BaseSensor(ABC):
    @abstractmethod
    def capture(self, page: Page) -> str:
        """采集页面状态，返回大模型可理解的文本描述"""
        pass