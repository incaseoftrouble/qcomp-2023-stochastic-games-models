import enum
import pathlib
from abc import ABC
from typing import Optional, Dict

from eval.data import TerminationOutcome
from ._tool import Tool


class PRISMTool(Tool, ABC):
    def parse_outcome(self, stdout: str, stderr: str) -> Optional[TerminationOutcome]:
        lines = stdout.splitlines()
        construction = None
        for line in lines:
            if line.startswith("Time for model construction: "):
                construction = float(
                    line[len("Time for model construction: ") :].split(" ", maxsplit=1)[
                        0
                    ]
                )
                break
        if construction is None:
            return None
        result = None
        for line in lines[::-1]:
            if line.startswith("Result: "):
                result = line[len("Result: ") :].split(" ", maxsplit=1)[0]
        if result is None:
            return None
        return TerminationOutcome(construction, result)


class PRISMGames(PRISMTool):
    def __init__(self, engine: str):
        self.engine = engine

    @property
    def unique_key(self) -> str:
        return f"prism-games-{self.engine}"

    @property
    def docker_image_name(self) -> str:
        return "prism-games:latest"

    def get_invocation(
        self,
        model_path: pathlib.Path,
        constants: Dict[str, str],
        properties_path: pathlib.Path,
        memory_limit: int,
    ):
        invocation = [
            "prism",
            str(model_path),
            str(properties_path),
            "--property",
            "1",
            f"--{self.engine}",
            "-epsilon",
            "1e-6",
            "-maxiters",
            "1000000",
            "-javamaxmem",
            f"{memory_limit - 128}m",
            "-cuddmaxmem",
            f"{memory_limit // 2}m",
            "-javastack",
            "128m",
        ]
        if constants:
            invocation.extend(
                ["--const", ",".join(f"{a}={b}" for a, b in constants.items())]
            )

        return invocation


class PRISMGamesExtensions(PRISMTool):
    class Method(enum.Enum):
        INTERVAL_ITERATION = ["ii", ["-ii"]]
        OPTIMISTIC_VALUE_ITERATION = ["ovi", ["-ovi", "-maxiters", "1"]]
        WIDEST_PATH = ["wp", ["-wp"]]

        @property
        def key(self):
            return self.value[0]

        @property
        def invocation(self):
            return self.value[1]

    def __init__(self, method: Method):
        self.method = method

    @property
    def unique_key(self) -> str:
        return f"prism-games-extension-{self.method.key}"

    @property
    def docker_image_name(self) -> str:
        return "prism-games-extensions:latest"

    def get_invocation(
        self,
        model_path: pathlib.Path,
        constants: Dict[str, str],
        properties_path: pathlib.Path,
        memory_limit: int,
    ):
        invocation = [
            "prism",
            str(model_path),
            str(properties_path),
            "--property",
            "1",
            "-epsilon",
            "1e-6",
            "-maxiters",
            "1000000",
            "-javamaxmem",
            f"{memory_limit - 128}m",
            "-cuddmaxmem",
            f"{memory_limit // 2}m",
            "-javastack",
            "128m",
        ] + self.method.invocation
        if constants:
            invocation.extend(
                ["--const", ",".join(f"{a}={b}" for a, b in constants.items())]
            )

        return invocation
