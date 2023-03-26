import argparse
import json
import sys
from pathlib import Path
from typing import Collection

from eval.data import Instance


def update_instances(args, instances: Collection[Instance]):
    if args.instances.exists():
        with args.instances.open(mode="rt") as f:
            instance_data = json.load(f)
        instance_list = [Instance.parse(instance) for instance in instance_data]
        instances_by_key = {instance.key: instance for instance in instance_list}
    else:
        instances_by_key = dict()

    any_changed = False
    for instance in instances:
        if instance.key not in instances_by_key:
            instances_by_key[instance.key] = instance
            any_changed = True

    if any_changed:
        with args.instances.open(mode="wt") as f:
            json.dump([instance.to_json() for instance in instances_by_key.values()], f)


def load_random(args):
    random_folder: Path = args.folder
    property_file = random_folder / Path("random.props")
    random_instances = []
    if not property_file.exists():
        sys.exit(f"Property file {property_file} does not exist")
    for file in random_folder.rglob("**/*.prism"):
        random_instances.append(file)

    print(f"Discovered {len(random_instances)} instances")

    instances = []
    for random_path in random_instances:
        model_number = random_path.name[:-6].rsplit("_", maxsplit=1)[1]
        family = random_path.parent.name
        key = f"random_{family}_{model_number}"
        instances.append(Instance(key, random_path, property_file, dict()))

    update_instances(args, instances)


def load_prism(args):
    instances_from_file = []

    with args.benchmarks.open(mode="rt") as f:
        for line in f:
            line: str
            comment = line.find("#")
            if comment >= 0:
                line = line[:comment].strip()
            if not line:
                continue
            data = line.split()
            model = data[0]
            if data[1] == "-const":
                constants_string = data[2]
                constants = dict()
                for pair in constants_string.split(","):
                    key, value = pair.split("=")
                    constants[key] = value
                properties = data[3]
            else:
                constants = {}
                properties = data[1]

            model_path = args.path / Path(model)
            if not model_path.exists():
                print(f"Model file {model_path} does not exist")
                continue
            properties_path = args.path / Path(properties)
            if not properties_path.exists():
                print(f"Property file {properties_path} does not exist")
                continue
            instances_from_file.append((model_path, constants, properties_path))

    print(f"Parsed {len(instances_from_file)} benchmarks from prism file")

    instances = []
    for model, constants, properties in instances_from_file:
        # Derive model key
        model_name = model.name
        if model_name.endswith(".prism"):
            model_name = model_name[:-6]
        key = model_name
        for _, v in sorted(constants.items()):
            key += f"_{v}"
        properties_name = properties.name
        if properties_name.endswith(".props"):
            properties_name = properties_name[:-6]
        key += f"_{properties_name}"

        instances.append(Instance(key, model, properties, constants))

    update_instances(args, instances)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("instances", type=Path, help="Path to instance database")

    subparsers = parser.add_subparsers()

    prism = subparsers.add_parser("prism")
    prism.add_argument(
        "benchmarks", type=Path, help="Path prism benchmarks txt"
    )
    prism.add_argument(
        "--path", type=Path, help="Base path for models", default=Path(".")
    )
    prism.set_defaults(func=load_prism)

    random = subparsers.add_parser("random")
    random.add_argument("--folder", type=Path, help="Base folder of random models", required=True)
    random.set_defaults(func=load_random)

    a = parser.parse_args()
    a.func(a)
