import argparse
import gzip
import json
import logging
import pathlib
import sys
import time
from pathlib import Path
from typing import Collection, List, Tuple

import docker
import docker.errors
import progressbar
import requests
from docker.models.images import Image

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
from eval.tools import PET, Tool, PRISMGames, PRISMGamesExtensions, Tempest

progressbar.streams.wrap_stderr()
logging.basicConfig()
logger = logging.getLogger("main")

TOOLS = [
    PET(True),
    PET(False),
    PRISMGames("explicit"),
    # PRISMGames("mtbdd"),
    PRISMGamesExtensions(PRISMGamesExtensions.Method.INTERVAL_ITERATION),
    # PRISMGamesExtensions(PRISMGamesExtensions.Method.OPTIMISTIC_VALUE_ITERATION),
    PRISMGamesExtensions(PRISMGamesExtensions.Method.WIDEST_PATH),
    Tempest(),
]


def recognize_error(stdout: str, stderr: str, exit_code: int, tool: Tool):
    memory_errors = {
        "java.lang.OutOfMemoryError",
        "ArrayIndexOutOfBounds",
        "NegativeArraySizeException",
    }
    if any(err in stderr for err in memory_errors):
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

    logger.warning(
        f"Unrecognized error for tool %s, code %s\n"
        f"=== Stdout ===\n"
        f"%s\n"
        f"=== Stderr ===\n"
        f"%s",
        tool.unique_key,
        exit_code,
        stdout.strip(),
        stderr.strip(),
    )

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
    )
    import docker.models.containers

    container: docker.models.containers.Container = client.containers.create(
        image=tool.docker_image_name,
        command=[
            "/usr/bin/timeout",
            str(timeout + 1),
            "/usr/bin/time",
            "-f",
            "%C\n%x,%e,%U,%M",
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
        response = container.wait(timeout=timeout + 5)
        exit_code = response["StatusCode"]
        stdout = container.logs(stdout=True, stderr=False).decode()
        stderr = container.logs(stdout=False, stderr=True).decode()
        duration = time.time() - start

        if exit_code == 124 or exit_code == 137:
            return Timeout(stdout, stderr, duration)

        stderr_lines = stderr.splitlines()
        if len(stderr_lines) < 2:
            logger.warning(
                "Execution of %s on %s produced less lines than expected (code %s):\n%s\n%s",
                tool.unique_key,
                instance.key,
                exit_code,
                stdout,
                stderr,
            )
            return Error(stdout, stderr, duration, exit_code, ErrorType.OUTPUT)
        time_data = stderr_lines[-1].split(",")
        try:
            time_exit_code, wall, user, resident = (
                int(time_data[0]),
                float(time_data[1]),
                float(time_data[2]),
                int(time_data[3]),
            )
        except (ValueError, IndexError):
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
            logger.warning("Tool %s failed to parse output", tool, exc_info=e)
            return Error(stdout, stderr, duration, exit_code, ErrorType.OUTPUT)

        return Termination(stdout, stderr, duration, outcome, wall, user, resident)
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        stdout = container.logs(stdout=True, stderr=False)
        stderr = container.logs(stdout=False, stderr=True)
        return Timeout(stdout, stderr, time.time() - start)
    except docker.errors.APIError as e:
        logger.warning("Docker API error for tool %s", tool, exc_info=e)
        sys.exit(1)
    finally:
        try:
            container.kill()
        except docker.errors.APIError:
            pass
        try:
            container.wait(timeout=10)
        except (
            docker.errors.APIError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ):
            pass
        try:
            container.remove()
        except docker.errors.APIError:
            logger.warning("Failed to remove container %s", container.id)


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
    to_execute: List[Tuple[Instance, Tool]] = []
    for instance in instances:
        if instance.key in experiments:
            experiment: Experiment = experiments[instance.key]
            for tool in TOOLS:
                if tool.unique_key not in experiment.tool_executions:
                    to_execute.append((instance, tool))
                    continue
                execution = experiment.tool_executions[tool.unique_key]
                if args.repeat_before and execution.timestamp < args.repeat_before:
                    to_execute.append((instance, tool))
                    continue
                result = execution.result
                if isinstance(result, Timeout) and result.time < timeout:
                    to_execute.append((instance, tool))
                    continue
                if experiment.input_hash != instance.hash:
                    to_execute.append((instance, tool))
                    continue
        else:
            for tool in TOOLS:
                to_execute.append((instance, tool))

    logger.info(
        "Executing %d out of %d instances",
        len(instance_data) * len(TOOLS),
        len(to_execute),
    )

    try:
        widgets = [
            progressbar.SimpleProgress(),
            " --- ",
            progressbar.Variable("model", format="Model: {formatted_value}", width=30),
            " ",
            progressbar.Variable("tool", format="Tool: {formatted_value}", width=15),
            " ",
            progressbar.Bar(),
            " ",
            progressbar.Timer(),
            ", ",
            progressbar.ETA(),
        ]
        with progressbar.ProgressBar(
            min_value=1,
            max_value=len(to_execute),
            redirect_stdout=True,
            widgets=widgets,
            poll_interval=0.1,
        ) as bar:
            for i, (instance, tool) in enumerate(to_execute):
                bar.update(i + 1, model=instance.key, tool=tool.unique_key)

                result = run(client, tool, instance, args.memory, args.timeout)
                execution = Execution(time.time(), result)
                if instance.key not in experiments:
                    experiments[instance.key] = Experiment(
                        instance.key, instance.hash, dict()
                    )
                experiments[instance.key].tool_executions[tool.unique_key] = execution
    except KeyboardInterrupt:
        logger.info("Caught interrupt, writing current results")

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
        "--timeout", type=float, help="Timeout (in seconds)", default=600
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
