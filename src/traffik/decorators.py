import asyncio
import copy
import functools
import inspect
import typing

from fastapi.params import Depends
from starlette.requests import HTTPConnection
from typing_extensions import Annotated

from traffik._utils import add_parameter_to_signature
from traffik.throttles import BaseThrottle
from traffik.types import UNLIMITED, HTTPConnectionT, P, Q, R, S

ThrottleT = typing.TypeVar("ThrottleT", bound=BaseThrottle)


class DecoratorDepends(typing.Generic[P, R, Q, S], Depends):
    """
    `fastapi.params.Depends` subclass that allows instances to be used as decorators.

    Instances use `dependency_decorator` to apply the dependency to the decorated object,
    while still allowing usage as regular FastAPI dependencies.

    `dependency_decorator` is a callable that takes the decorated object and an optional dependency
    and returns the decorated object with/without the dependency applied.

    Think of the `dependency_decorator` as a chef that mixes the sauce (dependency)
    with the dish (decorated object), making a dish with the sauce or without it.
    """

    def __init__(
        self,
        dependency_decorator: typing.Callable[
            [
                typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
                typing.Optional[
                    typing.Callable[Q, typing.Union[S, typing.Awaitable[S]]]
                ],
            ],
            typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
        ],
        dependency: typing.Optional[
            typing.Callable[Q, typing.Union[S, typing.Awaitable[S]]]
        ] = None,
        *,
        use_cache: bool = True,
    ) -> None:
        self.dependency_decorator = dependency_decorator
        super().__init__(dependency, use_cache=use_cache)

    def __call__(
        self, decorated: typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]
    ) -> typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]:
        return self.dependency_decorator(decorated, self.dependency)


# Is this worth it? Just because of the `throttle` decorator?
def _wrap_route(
    route: typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
    throttle: BaseThrottle,
) -> typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]:
    """
    Create an wrapper that applies throttling to an route
    by wrapping the route such that the route depends on the throttle.

    :param route: The route to wrap.
    :param throttle: The throttle to apply to the route.
    :return: The wrapper that enforces the throttle on the route.
    """
    # * This approach is necessary because FastAPI does not support dependencies
    # * that are not in the signature of the route function.

    # Use unique (throttle) dependency parameter name to avoid conflicts
    # with other dependencies that may be applied to the route, or in the case
    # of nested use of this wrapper function.
    throttle_dep_param_name = f"_{id(throttle)}_throttle"

    # We need the throttle dependency to be the first parameter of the route
    # So that the rate limit check is done before any other operations or dependencies
    # are resolved/executed, improving the efficiency of implementation.
    if asyncio.iscoroutinefunction(route):
        wrapper_code = f"""
async def route_wrapper(
    {throttle_dep_param_name}: Annotated[typing.Any, Depends(throttle)],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    return await route(*args, **kwargs)
"""
    else:
        wrapper_code = f"""
def route_wrapper(
    {throttle_dep_param_name}: Annotated[typing.Any, Depends(throttle)],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    return route(*args, **kwargs)
"""

    local_namespace = {
        "throttle": throttle,
        "Annotated": Annotated,
        "Depends": Depends,
    }
    global_namespace = {
        **globals(),
        "route": route,
    }
    exec(  # nosec
        wrapper_code,
        global_namespace,
        local_namespace,
    )
    route_wrapper = local_namespace["route_wrapper"]
    route_wrapper = functools.wraps(route)(route_wrapper)
    # The resulting function from applying `functools.wraps(route)` on `route_wrapper`
    # would not have the throttle dependency in its signature, although it is present in `route_wrapper`'s definition,
    # because the result of `functools.wraps` assumes the signature of the original function (route in this case).

    # Since the original/wrapped function does not have the throttle dependency in its signature,
    # the throttle dependency will not be recognized/regarded by FastAPI, as FastAPI
    # uses the signature of the function to determine the params, hence the dependencies of the function.

    # So, we update the signature of the wrapper to include the throttle dependency
    route_wrapper = add_parameter_to_signature(
        func=route_wrapper,
        parameter=inspect.Parameter(
            name=throttle_dep_param_name,
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[typing.Any, Depends(throttle)],
        ),
        index=0,  # Since the throttle dependency was added as the first parameter
    )
    return route_wrapper


def _throttle_route(
    route: typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
    throttle: BaseThrottle,
) -> typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]:
    """
    Returns wrapper that applies throttling to the given route
    by wrapping the route such that the route depends on the throttle.

    :param route: The route to be throttled.
    :param throttle: The throttle to apply to the route.
    """
    wrapper = _wrap_route(route, throttle)
    return wrapper


@typing.overload
def throttled(
    throttle: BaseThrottle[HTTPConnectionT],
) -> DecoratorDepends[P, typing.Any, typing.Any, typing.Any]: ...


@typing.overload
def throttled(
    throttle: BaseThrottle[HTTPConnectionT],
    route: typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
) -> typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]: ...


def throttled(
    throttle: BaseThrottle[HTTPConnectionT],
    route: typing.Optional[
        typing.Callable[P, typing.Union[R, typing.Awaitable[R]]]
    ] = None,
) -> typing.Union[
    DecoratorDepends[P, R, Q, HTTPConnectionT],
    typing.Callable[P, typing.Union[R, typing.Awaitable[R]]],
]:
    """
    Throttles connections to decorated route using the provided throttle.

    :param throttle: The throttle to apply to the route.
    :param route: The route to be throttled. If not provided, returns a decorator that can be used to apply throttling to routes.
    :return: A decorator that applies throttling to the route, or the wrapped route if `route` is provided.


    Example:
    ```python
    import fastapi
    from fastapi_throttle import throttled, HTTPThrottle

    sustained_throttle = HTTPThrottle(limit=10, seconds=60)
    burst_throttle = HTTPThrottle(limit=5, seconds=10)

    router = fastapi.APIRouter(
        dependencies=[
            sustained_throttle
        ]
    )

    @router.get("/throttled1")
    async def throttled_route1():
        return {"message": "Limited route 1"}

    @router.get("/throttled2")
    @throttled(burst_throttle)
    async def throttled_route2():
        return {"message": "Limited route 2"}

    ```
    """
    decorator_dependency = DecoratorDepends[P, R, Q, HTTPConnectionT](
        dependency_decorator=_throttle_route,  # type: ignore
        dependency=throttle,
    )
    if route is not None:
        decorated = decorator_dependency(route)
        return decorated
    return decorator_dependency


def get_referrer(connection: HTTPConnection) -> str:
    return (
        (connection.headers.get("referer", "") or connection.headers.get("origin", ""))
        .split("?")[0]
        .strip("/")
        .lower()
    )


def throttle_referers(
    throttle: BaseThrottle[HTTPConnectionT],
    referrers: typing.Sequence[str],
):
    """
    Throttles request connections based on the referrer of the request.

    This throttle is useful for limiting request connections referred from specific sources/origins.

    :param referrer: The referrer/origin(s) to limit connections from.
    :param throttle_kwargs: Keyword arguments to be used to instantiate the throttle type.
    """
    referrers = tuple(set(referrers))

    async def _identifier(connection: HTTPConnection) -> typing.Any:
        nonlocal referrers

        referrer = get_referrer(connection)
        if referrer not in referrers:
            return UNLIMITED
        return f"referer:{referrer}:{connection.scope['path']}"

    copied_throttle = copy.copy(throttle)
    copied_throttle.identifier = _identifier
    return throttled(throttle=copied_throttle)


async def user_agent_identifier(connection: HTTPConnection) -> str:
    user_agent = connection.headers.get("user-agent", "UnknownAgent")
    return f"{user_agent}:{connection.scope['path']}"


__all__ = [
    "throttled",
    "throttle_referers",
    "user_agent_identifier",
]
