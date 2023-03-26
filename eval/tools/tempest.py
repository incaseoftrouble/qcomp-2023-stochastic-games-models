import pathlib
from typing import Optional, Dict

from eval.data import TerminationOutcome
from eval.tools import Tool


class Tempest(Tool):
    def parse_outcome(self, stdout: str, stderr: str) -> Optional[TerminationOutcome]:
        lines = stdout.splitlines()
        construction = None
        for line in lines:
            if line.startswith("Time for model construction: "):
                construction = float(line[len("Time for model construction: ") :][:-2])

                break
        if construction is None:
            return None
        result = None
        for line in lines[::-1]:
            if line.startswith("Result (for initial states): "):
                result = line[len("Result (for initial states): ") :]
        if result is None:
            return None
        return TerminationOutcome(construction, result)

    @property
    def unique_key(self) -> str:
        return "tempest"

    @property
    def docker_image_name(self) -> str:
        return "tempest:latest"

    def get_invocation(
        self,
        model_path: pathlib.Path,
        constants: Dict[str, str],
        properties_path: pathlib.Path,
    ):
        invocation = [
            "storm",
            "--prism",
            str(model_path),
            "--prop",
            str(properties_path),
            "--precision",
            "1e-6",
        ]
        if constants:
            invocation.extend(
                ["--constants", ",".join(f"{a}={b}" for a, b in constants.items())]
            )
        return invocation
