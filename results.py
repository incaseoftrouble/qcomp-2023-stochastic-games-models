import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import seaborn as sns
from matplotlib import pyplot as plt
from matplotlib.colors import Normalize

from eval.data import Experiment, Termination


def main(args):
    with args.data.open(mode="rt") as f:
        result_data = json.load(f)
    results = [Experiment.parse(d) for d in result_data]

    tools = {"tempest", "pet", "prism-games-explicit", "prism-games-extension-ii", "prism-games-extension-wp"}

    outcomes = []
    for experiment in sorted(results, key=lambda e: e.instance_key):
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data", type=Path, help="Path to data file", default="data.json"
    )

    main(parser.parse_args())
