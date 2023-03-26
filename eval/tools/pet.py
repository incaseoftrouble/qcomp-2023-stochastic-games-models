import json
import pathlib
from typing import Optional, Dict

from eval.data import TerminationOutcome
from ._tool import Tool


class PET(Tool):
    def __init__(self, core):
        self.core = core

    def parse_outcome(self, stdout: str, stderr: str) -> Optional[TerminationOutcome]:
        output = json.loads(stdout)
        construction = output["statistics"]["model"] / 1000.0
        result = next(iter(output["values"].values()))
        return TerminationOutcome(construction, str(result))

    @property
    def unique_key(self) -> str:
        return "pet-core" if self.core else "pet"

    @property
    def docker_image_name(self) -> str:
        return "pet:latest"

    def get_invocation(
        self,
        model_path: pathlib.Path,
        constants: Dict[str, str],
        properties_path: pathlib.Path,
    ):
        invocation = [
            "pet",
            "ssg",
            "-m",
            str(model_path),
            "-p",
            str(properties_path),
            "--property",
            "0",
            "--precision",
            "1e-6",
        ]
        if constants:
            invocation.extend(
                ["--const", ",".join(f"{a}={b}" for a, b in constants.items())]
            )
        if self.core:
            invocation.append("--core")
        return invocation
