import argparse
import gzip
import json
import logging
import pathlib
import sys
import tarfile
import tempfile
import time
import progressbar
from typing import Collection, List, Tuple

import docker
from pathlib import Path

import requests
from docker.models.images import Image
import docker.errors

from eval.tools import PET, Tool
from eval.data import (
    Experiment,
    ErrorType,
    Error,
    Termination,
    Timeout,
    Instance,
    Result,
    Execution,
)

progressbar.streams.wrap_stderr()
logging.basicConfig()
logger = logging.getLogger("main")

TOOLS = [PET()]


def recognize_error(stdout: str, stderr: str, exit_code: int, tool: Tool):
    if (
        "java.lang.OutOfMemoryError" in stderr
        or "ArrayIndexOutOfBounds" in stderr
        or "NegativeArraySizeException" in stderr
    ):
        return ErrorType.OUT_OF_MEMORY

    if "java.lang.StackOverflowError" in stderr:
        return ErrorType.STACK_OVERFLOW

    if "Iterative method did not converge" in stderr:
        return ErrorType.CONVERGENCE

    if "IllegalArgumentException" in stderr:
        return ErrorType.INTERNAL

    tool_error = tool.recognize_error(stdout, stderr, exit_code)
    if tool_error is not None:
        return tool_error

    print("Unrecognized error:")
    print(exit_code)
    print(stderr)
    return ErrorType.GENERIC


def run(
    client: docker.DockerClient,
    tool: Tool,
    instance: Instance,
    memory: int,
    timeout: float,
) -> Result:
    assert memory > 1024

    start = time.time()

    invocation = tool.get_invocation(
        pathlib.Path("/tmp/model.prism"),
        instance.constants,
        pathlib.Path("/tmp/model.props"),
        instance.property_index,
    )
    import docker.models.containers

    container: docker.models.containers.Container = client.containers.create(
        image=tool.docker_image_name,
        command=[
            "/usr/bin/time",
            "-f",
            "%C\n%x,%e,%U,%M",
            "/usr/bin/timeout",
            "--preserve-status",
            str(timeout),
        ]
        + invocation,
        cpuset_cpus="1",
        mem_limit=f"{memory}m",
        mem_swappiness=0,
        environment={"JAVA_OPTS": f"-Xmx{memory - 128}m -Xms{memory - 256}m"},
        volumes={
            str(instance.prism_model.absolute()): {
                "bind": "/tmp/model.prism",
                "mode": "ro",
            },
            str(instance.prism_properties.absolute()): {
                "bind": "/tmp/model.props",
                "mode": "ro",
            },
        },
        network_disabled=False,
        detach=True,
    )

    try:
        container.start()
        response = container.wait(timeout=timeout)
        exit_code = response["StatusCode"]
        stdout = container.logs(stdout=True, stderr=False).decode()
        stderr = container.logs(stdout=False, stderr=True).decode()
        duration = time.time() - start

        stderr_lines = stderr.splitlines()
        if len(stderr_lines) < 2:
            logger.warning("Execution produced less lines than expected")
            return Error(stdout, stderr, duration, exit_code, ErrorType.OUTPUT)
        time_data = stderr_lines[-1].split(",")
        try:
            time_exit_code, wall, user, resident = (
                int(time_data[0]),
                float(time_data[1]),
                float(time_data[2]),
                int(time_data[3]),
            )
        except ValueError | IndexError:
            logger.warning("Time produced invalid output %s", stderr_lines[-1])
            return Error(stdout, stderr, duration, exit_code, ErrorType.OUTPUT)
        if time_exit_code != exit_code:
            logger.warning(
                "Time and docker return different exit codes: %d and %d",
                time_exit_code,
                exit_code,
            )

        if exit_code:
            error_type: ErrorType = recognize_error(stdout, stderr, exit_code, tool)
            return Error(stdout, stderr, duration, exit_code, error_type)

        try:
            outcome = tool.parse_outcome(stdout, stderr)
        except BaseException as e:
            logger.warning("Tool %s failed to parse output", tool, e)
            return Error(stdout, stderr, duration, exit_code, ErrorType.OUTPUT)

        return Termination(stdout, stderr, duration, outcome, wall, user, resident)
    except requests.exceptions.ReadTimeout:
        container.kill()
        stdout = container.logs(stdout=True, stderr=False)
        stderr = container.logs(stdout=False, stderr=True)
        return Timeout(stdout, stderr, time.time() - start)
    except docker.errors.APIError as e:
        logger.warning("Docker API error for tool %s", tool, e)
        sys.exit(1)
    finally:
        container.remove()


def check_docker_images(client: docker.DockerClient, tools: Collection[Tool]):
    required_tags = {tool.docker_image_name for tool in tools}

    for image in client.images.list():
        image: Image
        for tag in image.tags:
            if tag in required_tags:
                required_tags.remove(tag)

    if required_tags:
        raise KeyError(f"Images {' '.join(sorted(required_tags))} missing")


def main(args):
    client = docker.from_env()
    check_docker_images(client, TOOLS)

    if args.data.exists():
        with args.data.open("rt") as f:
            if args.data.name.endswith(".gz"):
                f = gzip.open(f)
            data = json.load(f)
        stored_experiments = [Experiment.parse(d) for d in data]
        experiments = {e.instance_key: e for e in stored_experiments}
    else:
        experiments = dict()

    with args.instances.open("rt") as f:
        instance_data = json.load(f)
    instances = [Instance.parse(data) for data in instance_data]
    for instance in instances:
        if not instance.prism_model.exists():
            raise KeyError(instance.prism_model)
        if not instance.prism_properties.exists():
            raise KeyError(instance.prism_properties)

    timeout = args.timeout
    to_execute: List[Tuple[Experiment, Tool]] = []
    for instance in instances:
        if instance.key in experiments:
            experiment: Experiment = experiments[instance.key]
            for tool in TOOLS:
                if tool.unique_key not in experiment.tool_executions:
                    to_execute.append((instance, tool))
                execution = experiment.tool_executions[tool.unique_key]
                if args.repeat_before and execution.timestamp < args.repeat_before:
                    to_execute.append((instance, tool))
                result = execution.result
                if isinstance(result, Timeout) and result.time < timeout:
                    to_execute.append((instance, tool))
                if experiment.input_hash != instance.hash:
                    to_execute.append((instance, tool))
        else:
            for tool in TOOLS:
                to_execute.append((instance, tool))

    logger.info(
        "Executing %d out of %d instances",
        len(instance_data) * len(TOOLS),
        len(to_execute),
    )

    for (instance, tool) in progressbar.progressbar(to_execute):
        result = run(client, tool, instance, args.memory, args.timeout)
        execution = Execution(time.time(), result)
        if instance.key not in experiments:
            experiments[instance.key] = Experiment(instance.key, instance.hash, dict())
        experiments[instance.key].tool_executions[tool.unique_key] = execution

    with args.data.open("wt") as f:
        if args.data.name.endswith(".gz"):
            f = gzip.open(f)
        json.dump([experiment.to_json() for experiment in experiments.values()], f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data", type=Path, help="Path to experiment data", default=Path("data.json")
    )
    parser.add_argument(
        "--instances",
        type=Path,
        help="Path to instance data",
        default=Path("instances.json"),
    )
    parser.add_argument(
        "--timeout", type=float, help="Timeout (in seconds)", default=300
    )
    parser.add_argument(
        "--memory", type=int, help="Memory limit (in MB)", default=8 * 1024
    )
    parser.add_argument(
        "--repeat-before",
        type=float,
        help="Repeat experiments done before given timestamp",
    )

    main(parser.parse_args())
