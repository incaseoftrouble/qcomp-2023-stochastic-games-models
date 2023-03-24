import abc
import pathlib
from typing import Optional, Dict

from eval.data import Instance, Result, TerminationOutcome


class Tool(abc.ABC):
    @abc.abstractmethod
    def get_invocation(
        self,
        model_path: pathlib.Path,
        constants: Dict[str, str],
        properties_path: pathlib.Path,
        property_index: int,
    ):
        pass

    @property
    @abc.abstractmethod
    def docker_image_name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def unique_key(self) -> str:
        pass

    def recognize_error(
        self, stdout: str, stderr: str, exit_code: int
    ) -> Optional[Result]:
        return None

    @abc.abstractmethod
    def parse_outcome(self, stdout: str, stderr: str) -> Optional[TerminationOutcome]:
        pass

    def __str__(self):
        return self.unique_key

    def __hash__(self):
        return hash(self.unique_key)

    def __eq__(self, other):
        return isinstance(other, Tool) and other.unique_key == self.unique_key
