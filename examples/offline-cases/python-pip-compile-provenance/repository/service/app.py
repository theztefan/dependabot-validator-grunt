import transport_parent


def create_client() -> object:
    return transport_parent.Client()
