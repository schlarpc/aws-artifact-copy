import functools

import aiobotocore.session
import trio_asyncio


def _patch_client_methods_for_trio(class_attributes, **_):
    for key, value in class_attributes.items():
        if callable(value):
            class_attributes[key] = trio_asyncio.aio_as_trio(value)


def create_async_session():
    session = aiobotocore.session.get_session()
    session.get_component("event_emitter").register(
        "creating-client-class.*", _patch_client_methods_for_trio
    )
    return session


def create_async_client(*args, session=None, **kwargs):
    if session is None:
        session = create_async_session()
    return trio_asyncio.aio_as_trio(session.create_client(*args, **kwargs))


def partial_client_methods(client, **kwargs):
    for method, api_method in client.meta.method_to_api_mapping.items():
        input_shape = client.meta.service_model.operation_model(api_method).input_shape
        setattr(
            client,
            method,
            functools.partial(
                getattr(client, method),
                **{k: v for k, v in kwargs.items() if k in input_shape.members},
            ),
        )
    return client
