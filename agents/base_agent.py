from abc import ABC, abstractmethod

class BaseAgent(ABC):
    @abstractmethod
    def ask(self, context: dict) -> dict:
        """输入上下文，返回决策结果，统一接口"""
        pass