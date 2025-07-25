import typing

from starlette.requests import HTTPConnection
from typing_extensions import ParamSpec, TypeAlias

P = ParamSpec("P")
Q = ParamSpec("Q")
R = typing.TypeVar("R")
S = typing.TypeVar("S")
T = typing.TypeVar("T")


UNLIMITED = object()
"""
A sentinel value to identify that a connection should not be throttled.

This value should be returned by the connection identifier function
when the connection should not be subject to throttling.
"""

Function: TypeAlias = typing.Callable[P, R]
CoroutineFunction: TypeAlias = typing.Callable[P, typing.Awaitable[R]]
Decorated: TypeAlias = typing.Union[Function[P, R], CoroutineFunction[P, R]]
Dependency: TypeAlias = typing.Union[Function[Q, S], CoroutineFunction[Q, S]]

HTTPConnectionT = typing.TypeVar("HTTPConnectionT", bound=HTTPConnection)
HTTPConnectionTcon = typing.TypeVar(
    "HTTPConnectionTcon", bound=HTTPConnection, contravariant=True
)
WaitPeriod: TypeAlias = int

class Stringable(typing.Protocol):
    """Protocol for objects that can be converted to a string."""

    def __str__(self) -> str:
        """Return a string representation of the object."""
        ...


class ConnectionIdentifier(typing.Protocol, typing.Generic[HTTPConnectionTcon]):
    """Protocol for connection identifier functions."""

    async def __call__(
        self, connection: HTTPConnectionTcon, *args: typing.Any, **kwargs: typing.Any
    ) -> typing.Union[Stringable, typing.Any]:
        """Identify a connection for throttling purposes."""
        ...


class ConnectionThrottledHandler(typing.Protocol, typing.Generic[HTTPConnectionTcon]):
    """Protocol for connection throttled handlers."""

    async def __call__(
        self,
        connection: HTTPConnectionTcon,
        wait_period: WaitPeriod,
        *args: typing.Any,
        **kwargs: typing.Any,
    ) -> typing.Any:
        """Handle a throttled connection."""
        ...
