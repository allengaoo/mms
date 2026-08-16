"""
LLM Provider 抽象基类（Python 3.9 兼容，使用 ABC 而非 Protocol）
"""
import abc
from typing import List, Optional


class ProviderUnavailableError(Exception):
    """Provider 不可用（服务未启动、连接失败等）"""
    pass


class AllProvidersUnavailableError(Exception):
    """所有 Provider 均不可用"""
    pass


class LLMProvider(abc.ABC):
    """LLM Provider 抽象基类。所有适配器必须实现此接口。"""

    model_name: str = ""

    @abc.abstractmethod
    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        """
        发送 prompt，返回生成的文本。

        Args:
            prompt:     完整的用户 prompt
            max_tokens: 最大生成 token 数

        Returns:
            生成的文本字符串

        Raises:
            ProviderUnavailableError: 服务不可达或调用失败
        """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """
        检查 Provider 是否可用（不发起实际生成请求）。
        实现应在 3 秒内返回结果。
        """


class EmbedProvider(abc.ABC):
    """向量嵌入 Provider 抽象基类（用于记忆相似度检测，非检索路径）"""

    model_name: str = ""

    @abc.abstractmethod
    def embed(self, text: str) -> List[float]:
        """返回文本的嵌入向量"""

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算两向量的余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x ** 2 for x in a) ** 0.5
        norm_b = sum(x ** 2 for x in b) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)
