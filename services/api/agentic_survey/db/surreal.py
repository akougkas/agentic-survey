from collections.abc import Sequence
from typing import Any


class SurrealClient:
    def __init__(
        self,
        url: str,
        namespace: str,
        database: str,
        user: str,
        password: str,
    ) -> None:
        self.url = url
        self.namespace = namespace
        self.database = database
        self.user = user
        self.password = password
        self._db = None

    async def connect(self) -> None:
        if self._db is not None:
            return
        try:
            from surrealdb import AsyncSurreal
        except ImportError as exc:
            raise RuntimeError("surrealdb is not installed") from exc

        self._db = AsyncSurreal(self.url)
        await self._db.signin(
            {
                "username": self.user,
                "password": self.password,
            }
        )
        await self._db.use(self.namespace, self.database)

    async def close(self) -> None:
        if self._db is None:
            return
        close = getattr(self._db, "close", None)
        if callable(close):
            maybe_awaitable = close()
            if maybe_awaitable is not None:
                await maybe_awaitable
        self._db = None

    async def healthcheck(self) -> bool:
        try:
            await self.query("RETURN true;")
        except Exception:
            return False
        return True

    async def query(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> Sequence[dict[str, Any]]:
        await self.connect()
        assert self._db is not None
        return await self._db.query(statement, variables or {})

    async def query_raw(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.connect()
        assert self._db is not None
        return await self._db.query_raw(statement, variables or {})
