import yaml


def parse_config(value: str) -> object:
    return yaml.safe_load(value)
