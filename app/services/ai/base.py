from abc import ABC, abstractmethod

class AIClient(ABC):
    """
    Contrato que cualquier proveedor de IA debe cumplir.
    """

    @abstractmethod
    def generate_response(
        self,
        system_prompt: str,
        user_prompt: str
    ) -> str:
        pass
