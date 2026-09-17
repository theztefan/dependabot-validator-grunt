import transport_parent


def run_job(payload: dict[str, object]) -> object:
    return transport_parent.process(payload)
