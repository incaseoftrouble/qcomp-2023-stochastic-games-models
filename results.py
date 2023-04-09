import argparse
import itertools
import json
import tabulate
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd
import seaborn as sns
from matplotlib import pyplot as plt

from eval.data import Experiment, Termination, Timeout, Error, ErrorType


def main(args):
    with args.data.open(mode="rt") as f:
        result_data = json.load(f)
    results = [Experiment.parse(d) for d in result_data]

    tools = {"tempest", "pet", "pet-core", "prism-games-explicit", "prism-games-mtbdd", "prism-games-extension-ii", "prism-games-extension-wp", "prism-games-extension-ovi"}

    outcomes = []
    values = defaultdict(dict)

    tools_list = sorted(tools)
    header = ["model"] + tools_list
    table_data = []

    for experiment in sorted(results, key=lambda e: e.instance_key):
        if experiment.instance_key.startswith("random"):
            continue

        row = [experiment.instance_key]
        for tool in tools_list:
            if tool not in experiment.tool_executions:
                row.append("n/a")
                continue
            result = experiment.tool_executions[tool].result
            if isinstance(result, Termination):
                row.append(round(result.time, 1))
            elif isinstance(result, Timeout):
                row.append("T/O")
            elif isinstance(result, Error):
                if result.error_type == ErrorType.OUT_OF_MEMORY:
                    row.append("M/O")
                elif result.error_type == ErrorType.STACK_OVERFLOW:
                    row.append("S/O")
                else:
                    row.append("ERR")
            else:
                row.append("?")
        table_data.append(row)

        for tool, execution in experiment.tool_executions.items():
            if tool not in tools:
                continue

            resident_size = None
            construction_time = None
            construction_faction = None
            if isinstance(execution.result, Termination):
                resident_size = execution.result.resident_size
                if execution.result.outcome is not None:
                    construction_time = execution.result.outcome.construction_time
                    construction_faction = construction_time / execution.result.time

                    result = execution.result.outcome.result
                    try:
                        values[experiment.instance_key][tool] = float(result)
                    except ValueError:
                        values[experiment.instance_key][tool] = result.lower()

            outcomes.append(
                (
                    tool,
                    experiment.instance_key,
                    type(execution.result).__name__,
                    execution.result.time,
                    resident_size,
                    construction_time,
                    construction_faction
                )
            )

    print(tabulate.tabulate(table_data, headers=header, tablefmt="github"))
    print()

    for experiment, tool_values in values.items():
        if all(isinstance(v, float) for v in tool_values.values()):
            median = statistics.median(tool_values.values())
            for tool, value in tool_values.items():
                if abs(value - median) > 2e-6:
                    print(f"Value {value} of {experiment}/{tool} differs from median {median}")
        elif all(isinstance(v, str) for v in tool_values.values()):
            values = set(tool_values.values())
            if len(values) > 1:
                print(f"Multiple distinct values for {experiment}: {', '.join(tool + ': ' + value for tool, value in tool_values.items())} -- {','.join(values)}")
        else:
            print(f"Different types of results for {experiment}: {', '.join(tool + ': ' + value for tool, value in tool_values.items())}")

    df = pd.DataFrame(outcomes, columns=["tool", "instance", "outcome", "time", "resident", "construction", "constr_fraction"])
    fig, ax = plt.subplots()
    plt.xticks(rotation=90)
    fig.set_size_inches(20, 6)
    sns.scatterplot(
        df,
        x="instance",
        y="tool",
        hue="outcome",
        size="time",
        palette={
            "Termination": "tab:green",
            "Timeout": "tab:orange",
            "Error": "tab:red",
        },
    )
    sns.move_legend(ax, "upper left", bbox_to_anchor=(1, 1))
    plt.tight_layout()
    fig.savefig("plot-success.png")

    fig, ax = plt.subplots(2, 2)
    fig.set_size_inches(10, 10)
    sns.stripplot(data=df, x="time", y="tool", ax=ax[0, 0])
    sns.stripplot(data=df, x="resident", y="tool", ax=ax[0, 1])
    sns.stripplot(data=df, x="construction", y="tool", ax=ax[1, 0])
    sns.stripplot(data=df, x="constr_fraction", y="tool", hue="time", palette=sns.color_palette("magma", as_cmap=True), ax=ax[1, 1])
    plt.tight_layout()
    fig.savefig("plot-data.png")

    tool_data = {
        tool: df.query(f"tool == '{tool}'") for tool in tools
    }

    fig, ax = plt.subplots(len(tools), len(tools))
    fig.set_size_inches(len(tools) * 4, (len(tools)) * 4)
    for l in ax:
        for a in l:
            a.set(xlim=(0, 62), ylim=(0, 62))
            a.set_aspect('equal', 'box')
            a.axline((0, 0), (1, 1))

    index_map = {}
    for i, t in enumerate(sorted(tools)):
        index_map[t] = i
    for a, b in itertools.product(tools, tools):
        if a == b:
            continue
        axis = ax[index_map[b], index_map[a]]
        merge = tool_data[a].merge(right=tool_data[b], on="instance", how="inner", suffixes=(f"_{a}", f"_{b}"))
        sns.scatterplot(data=merge, x=f"time_{b}", y=f"time_{a}", ax=axis)
    plt.tight_layout()
    fig.savefig("plot-compare.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data", type=Path, help="Path to data file", default="data.json"
    )

    main(parser.parse_args())
