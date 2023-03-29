import base64
import pathlib
from functools import cached_property
from hashlib import sha256
from typing import Dict, List
import abc
import dataclasses
import enum
from typing import Optional


@dataclasses.dataclass
class Instance(object):
    key: str
    prism_model: pathlib.Path
    prism_properties: pathlib.Path
    constants: Dict[str, str]

    @staticmethod
    def create_hash(instance: "Instance"):
        hasher = sha256()
        with instance.prism_model.open("rb") as f:
            while b := f.read(64 * 1024):
                hasher.update(b)
        with instance.prism_properties.open("rb") as f:
            while b := f.read(64 * 1024):
                hasher.update(b)
        for c, v in sorted(instance.constants.items()):
            hasher.update(c.encode())
            hasher.update(v.encode())
        return base64.b64encode(hasher.digest()).decode()

    @cached_property
    def hash(self):
        return Instance.create_hash(self)

    @staticmethod
    def parse(data):
        return Instance(
            key=data["key"],
            prism_model=pathlib.Path(data["model"]),
            prism_properties=pathlib.Path(data["prop"]),
            constants=data.get("constants", {}),
        )

    def to_json(self):
        data = {
            "key": self.key,
            "model": str(self.prism_model),
            "prop": str(self.prism_properties),
        }
        if self.constants:
            data["constants"] = self.constants
        return data

    def __str__(self):
        return self.key


class ErrorType(enum.Enum):
    PARSING = "parsing"
    OUTPUT = "output"
    OUT_OF_MEMORY = "memory"
    STACK_OVERFLOW = "stackoverflow"
    CONVERGENCE = "convergence"
    INTERNAL = "internal"
    GENERIC = "generic"

    @staticmethod
    def by_value(value):
        for e in ErrorType:
            if value == e.value:
                return e
        raise KeyError(value)


@dataclasses.dataclass
class Result(abc.ABC):
    output: str
    error: str
    time: float

    @abc.abstractmethod
    def to_json(self):
        pass

    @staticmethod
    def parse(data):
        data_type = data["type"]
        output = data["stdout"]
        error = data["stderr"]
        time = data["time"]
        if data_type == "timeout":
            return Timeout(output, error, time)
        if data_type == "error":
            return Error(
                output, error, time, data["code"], ErrorType.by_value(data["error"])
            )
        if data_type == "terminated":
            outcome = (
                TerminationOutcome.parse(data["outcome"]) if "outcome" in data else None
            )
            return Termination(
                output,
                error,
                time,
                outcome,
                data["wall_time"],
                data["user_time"],
                data["resident_size"],
            )
        raise KeyError(data_type)

    @property
    def success(self):
        return isinstance(self, Termination) and self.outcome is not None


@dataclasses.dataclass
class Timeout(Result):
    def to_json(self):
        return {
            "type": "timeout",
            "stdout": self.output,
            "stderr": self.error,
            "time": self.time,
        }

    def __str__(self):
        return f"Timeout"


@dataclasses.dataclass
class Error(Result):
    code: int
    error_type: ErrorType

    def to_json(self):
        return {
            "type": "error",
            "code": self.code,
            "error": self.error_type.value,
            "stdout": self.output,
            "stderr": self.error,
            "time": self.time,
        }

    def __str__(self):
        return f"Error({self.error_type},{self.code})"


@dataclasses.dataclass
class TerminationOutcome(object):
    construction_time: float
    result: str

    def to_json(self):
        return {"construction": self.construction_time, "result": self.result}

    @staticmethod
    def parse(data):
        return TerminationOutcome(data["construction"], data["result"])


@dataclasses.dataclass
class Termination(Result):
    outcome: Optional[TerminationOutcome]

    wall_time: float
    user_time: float
    resident_size: int

    def to_json(self):
        data = {
            "type": "terminated",
            "wall_time": self.wall_time,
            "user_time": self.user_time,
            "stdout": self.output,
            "resident_size": self.resident_size,
            "stderr": self.error,
            "time": self.time,
        }
        if self.outcome is not None:
            data["outcome"] = self.outcome.to_json()
        return data

    def __str__(self):
        return "Success"


@dataclasses.dataclass
class Execution(object):
    timestamp: float
    tool_hash: int
    result: Result

    def to_json(self):
        return {
            "timestamp": self.timestamp,
            "hash": self.tool_hash,
            "result": self.result.to_json(),
        }

    @staticmethod
    def parse(data):
        return Execution(data["timestamp"], data["hash"], Result.parse(data["result"]))


@dataclasses.dataclass
class Experiment(object):
    instance_key: str
    input_hash: str
    tool_executions: Dict[str, Execution]

    def to_json(self):
        return {
            "key": self.instance_key,
            "hash": self.input_hash,
            "tools": {
                tool_key: execution.to_json()
                for tool_key, execution in self.tool_executions.items()
            },
        }

    @staticmethod
    def parse(data):
        return Experiment(
            data["key"],
            data["hash"],
            {
                tool_key: Execution.parse(tool_execution)
                for tool_key, tool_execution in data["tools"].items()
            },
        )
