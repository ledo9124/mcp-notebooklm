"""Core infrastructure for NotebookLM API client."""

import asyncio
import logging
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from .auth import AuthTokens
from .observability.tracing import current_trace
from .rpc import (
    BATCHEXECUTE_URL,
    AuthError,
    ClientError,
    NetworkError,
    RateLimitError,
    RPCError,
    RPCMethod,
    RPCTimeoutError,
    ServerError,
    build_request_body,
    decode_response,
    encode_rpc_request,
)
from .rpc.encoder import build_url_params

logger = logging.getLogger(__name__)

# Maximum number of conversations to cache (FIFO eviction)
MAX_CONVERSATION_CACHE_SIZE = 100

# Default HTTP timeouts in seconds
DEFAULT_TIMEOUT = 30.0
DEFAULT_CONNECT_TIMEOUT = 10.0  # Connection establishment timeout

# Auth error detection patterns (case-insensitive)
AUTH_ERROR_PATTERNS = (
    "authentication",
    "build label",
    "build mismatch",
    "expired",
    "unauthorized",
    "login",
    "re-authenticate",
)

# Automatic retries for transient rate limiting.
RATE_LIMIT_MAX_RETRIES = 3
RATE_LIMIT_INITIAL_DELAY = 1.0
RATE_LIMIT_MAX_DELAY = 8.0
RATE_LIMIT_JITTER_RATIO = 0.25


def is_auth_error(error: Exception) -> bool:
    """Check if an exception indicates an authentication failure.

    Args:
        error: The exception to check.

    Returns:
        True if the error is likely due to authentication issues.
    """
    # AuthError is always an auth error
    if isinstance(error, AuthError):
        return True

    # Don't treat network/rate limit/server errors as auth errors
    # even if they're subclasses of RPCError
    if isinstance(error, (NetworkError, RPCTimeoutError, RateLimitError, ServerError, ClientError)):
        return False

    # HTTP 401/403 are auth errors
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in (401, 403)

    # RPCError with auth-related message
    if isinstance(error, RPCError):
        message = str(error).lower()
        return any(pattern in message for pattern in AUTH_ERROR_PATTERNS)

    return False


class ClientCore:
    """Core client infrastructure for HTTP and RPC operations.

    Handles:
    - HTTP client lifecycle (open/close)
    - RPC call encoding/decoding
    - Authentication headers
    - Conversation cache

    This class is used internally by the sub-client APIs (NotebooksAPI,
    ArtifactsAPI, etc.) and should not be used directly.
    """

    def __init__(
        self,
        auth: AuthTokens,
        timeout: float = DEFAULT_TIMEOUT,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        refresh_callback: Callable[[], Awaitable[AuthTokens]] | None = None,
        refresh_retry_delay: float = 0.2,
        rate_limit_max_retries: int = RATE_LIMIT_MAX_RETRIES,
    ):
        """Initialize the core client.

        Args:
            auth: Authentication tokens from browser login.
            timeout: HTTP request timeout in seconds. Defaults to 30 seconds.
                This applies to read/write operations after connection is established.
            connect_timeout: Connection establishment timeout in seconds. Defaults to 10 seconds.
                A shorter connect timeout helps detect network issues faster.
            refresh_callback: Optional async callback to refresh auth tokens on failure.
                If provided, rpc_call will automatically retry once after refreshing.
            refresh_retry_delay: Delay in seconds before retrying after refresh.
            rate_limit_max_retries: Maximum number of automatic 429 retry attempts.
        """
        self.auth = auth
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._refresh_callback = refresh_callback
        self._refresh_retry_delay = refresh_retry_delay
        self._rate_limit_max_retries = max(0, rate_limit_max_retries)
        self._rate_limit_initial_delay = RATE_LIMIT_INITIAL_DELAY
        self._rate_limit_max_delay = RATE_LIMIT_MAX_DELAY
        self._rate_limit_jitter_ratio = RATE_LIMIT_JITTER_RATIO
        self._refresh_lock: asyncio.Lock | None = asyncio.Lock() if refresh_callback else None
        self._refresh_task: asyncio.Task[AuthTokens] | None = None
        self._http_client: httpx.AsyncClient | None = None
        # Request ID counter for chat API (must be unique per request)
        self._reqid_counter: int = 100000
        # OrderedDict for FIFO eviction when cache exceeds MAX_CONVERSATION_CACHE_SIZE
        self._conversation_cache: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    async def open(self) -> None:
        """Open the HTTP client connection.

        Called automatically by NotebookLMClient.__aenter__.
        """
        if self._http_client is None:
            # Use granular timeouts: shorter connect timeout helps detect network issues
            # faster, while longer read/write timeouts accommodate slow responses
            timeout = httpx.Timeout(
                connect=self._connect_timeout,
                read=self._timeout,
                write=self._timeout,
                pool=self._timeout,
            )
            self._http_client = httpx.AsyncClient(
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Cookie": self.auth.cookie_header,
                },
                timeout=timeout,
            )

    async def close(self) -> None:
        """Close the HTTP client connection.

        Called automatically by NotebookLMClient.__aexit__.
        """
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    @property
    def is_open(self) -> bool:
        """Check if the HTTP client is open."""
        return self._http_client is not None

    def update_auth_headers(self) -> None:
        """Update HTTP client headers with current auth tokens.

        Call this after modifying auth tokens (e.g., after refresh_auth())
        to ensure the HTTP client uses the updated credentials.

        Raises:
            RuntimeError: If client is not initialized.
        """
        if not self._http_client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        self._http_client.headers["Cookie"] = self.auth.cookie_header

    def _build_rpc_params(self, rpc_method: RPCMethod, source_path: str = "/") -> dict[str, str]:
        """Build the canonical batchexecute query parameters for one RPC call."""
        return build_url_params(
            rpc_method,
            source_path=source_path,
            session_id=self.auth.session_id,
            bl=self.auth.build_label,
        )

    def _build_url(self, rpc_method: RPCMethod, source_path: str = "/") -> str:
        """Build the batchexecute URL for an RPC call.

        Args:
            rpc_method: The RPC method to call.
            source_path: The source path parameter (usually notebook path).

        Returns:
            Full URL with query parameters.
        """
        return f"{BATCHEXECUTE_URL}?{urlencode(self._build_rpc_params(rpc_method, source_path))}"

    def _record_transport_event(self, kind: str, payload: dict[str, Any]) -> None:
        """Append a run_event for the current trace when local state is available."""
        trace = current_trace()
        if trace is None:
            return

        try:
            from .local.db import connect_db
            from .local.events import append_run_event

            connection = connect_db()
            try:
                append_run_event(
                    connection,
                    trace.trace_id,
                    kind,
                    run_id=trace.run_id,
                    payload=payload,
                )
            finally:
                connection.close()
        except Exception as exc:
            logger.debug("Failed to record transport event %s: %s", kind, exc)

    async def rpc_call(
        self,
        method: RPCMethod,
        params: list[Any],
        source_path: str = "/",
        allow_null: bool = False,
        _is_retry: bool = False,
        _rate_limit_retry_count: int = 0,
    ) -> Any:
        """Make an RPC call to the NotebookLM API.

        Automatically refreshes authentication tokens and retries once if an
        auth failure is detected and a refresh_callback was provided.

        Args:
            method: The RPC method to call.
            params: Parameters for the RPC call (nested list structure).
            source_path: The source path parameter (usually /notebook/{id}).
            allow_null: If True, don't raise error when response is null.
            _is_retry: Internal flag to prevent infinite retries.

        Returns:
            Decoded response data.

        Raises:
            RuntimeError: If client is not initialized (not in context manager).
            httpx.HTTPStatusError: If HTTP request fails.
            RPCError: If RPC call fails or returns unexpected data.
        """
        if not self._http_client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        start = time.perf_counter()
        logger.debug("RPC %s starting", method.name)

        url = self._build_url(method, source_path)
        rpc_request = encode_rpc_request(method, params)
        body = build_request_body(rpc_request, self.auth.csrf_token)

        try:
            response = await self._http_client.post(url, content=body)
            response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            elapsed = time.perf_counter() - start

            # Check if this is an auth error and we can retry
            if not _is_retry and self._refresh_callback and is_auth_error(e):
                refreshed = await self._try_refresh_and_retry(
                    method,
                    params,
                    source_path,
                    allow_null,
                    e,
                    rate_limit_retry_count=_rate_limit_retry_count,
                )
                if refreshed is not None:
                    return refreshed

            if isinstance(e, httpx.HTTPStatusError):
                status = e.response.status_code
                logger.error(
                    "RPC %s failed after %.3fs: HTTP %s",
                    method.name,
                    elapsed,
                    status,
                )

                # Map HTTP status codes to appropriate exception types
                if status == 429:
                    # Rate limiting - extract retry-after if available
                    retry_after = self._parse_retry_after_seconds(
                        e.response.headers.get("retry-after")
                    )
                    msg = f"API rate limit exceeded calling {method.name}"
                    if retry_after:
                        msg += f". Retry after {retry_after} seconds"
                    rate_limit_error = RateLimitError(
                        msg,
                        method_id=method.value,
                        retry_after=retry_after,
                    )
                    if _rate_limit_retry_count < self._rate_limit_max_retries:
                        return await self._retry_after_rate_limit(
                            method,
                            params,
                            source_path,
                            allow_null,
                            rate_limit_error,
                            _is_retry=_is_retry,
                            rate_limit_retry_count=_rate_limit_retry_count,
                        )
                    raise rate_limit_error from e

                if 500 <= status < 600:
                    raise ServerError(
                        f"Server error {status} calling {method.name}: {e.response.reason_phrase}",
                        method_id=method.value,
                        status_code=status,
                    ) from e

                if 400 <= status < 500 and status not in (401, 403):
                    raise ClientError(
                        f"Client error {status} calling {method.name}: {e.response.reason_phrase}",
                        method_id=method.value,
                        status_code=status,
                    ) from e

                # 401/403 or other: Generic RPCError (handled by auth retry above)
                raise RPCError(
                    f"HTTP {status} calling {method.name}: {e.response.reason_phrase}",
                    method_id=method.value,
                ) from e

            # Network/connection errors
            else:
                logger.error("RPC %s failed after %.3fs: %s", method.name, elapsed, e)

                # Check ConnectTimeout first (more specific than general TimeoutException)
                if isinstance(e, httpx.ConnectTimeout):
                    raise NetworkError(
                        f"Connection timed out calling {method.name}: {e}",
                        method_id=method.value,
                        original_error=e,
                    ) from e

                # Timeout errors (general timeouts, not connection timeouts)
                if isinstance(e, httpx.TimeoutException):
                    raise RPCTimeoutError(
                        f"Request timed out calling {method.name}",
                        method_id=method.value,
                        timeout_seconds=self._timeout,
                        original_error=e,
                    ) from e

                # Connection errors (DNS, network unavailable, etc., excluding ConnectTimeout)
                if isinstance(e, httpx.ConnectError):
                    raise NetworkError(
                        f"Connection failed calling {method.name}: {e}",
                        method_id=method.value,
                        original_error=e,
                    ) from e

                # Other request errors
                raise NetworkError(
                    f"Request failed calling {method.name}: {e}",
                    method_id=method.value,
                    original_error=e,
                ) from e

        try:
            result = decode_response(response.text, method.value, allow_null=allow_null)
            elapsed = time.perf_counter() - start
            logger.debug("RPC %s completed in %.3fs", method.name, elapsed)
            return result
        except RPCError as e:
            elapsed = time.perf_counter() - start

            if (
                isinstance(e, RateLimitError)
                and _rate_limit_retry_count < self._rate_limit_max_retries
            ):
                return await self._retry_after_rate_limit(
                    method,
                    params,
                    source_path,
                    allow_null,
                    e,
                    _is_retry=_is_retry,
                    rate_limit_retry_count=_rate_limit_retry_count,
                )

            # Check if this is an auth error and we can retry
            if not _is_retry and self._refresh_callback and is_auth_error(e):
                refreshed = await self._try_refresh_and_retry(
                    method,
                    params,
                    source_path,
                    allow_null,
                    e,
                    rate_limit_retry_count=_rate_limit_retry_count,
                )
                if refreshed is not None:
                    return refreshed

            logger.error("RPC %s failed after %.3fs", method.name, elapsed)
            raise
        except Exception as e:
            elapsed = time.perf_counter() - start
            logger.error("RPC %s failed after %.3fs: %s", method.name, elapsed, e)
            raise RPCError(
                f"Failed to decode response for {method.name}: {e}",
                method_id=method.value,
            ) from e

    async def _try_refresh_and_retry(
        self,
        method: RPCMethod,
        params: list[Any],
        source_path: str,
        allow_null: bool,
        original_error: Exception,
        *,
        rate_limit_retry_count: int,
    ) -> Any | None:
        """Attempt to refresh auth tokens and retry the RPC call.

        Uses a shared task pattern to ensure only one refresh operation runs
        at a time. Concurrent callers wait on the same task, preventing
        redundant refresh calls under high concurrency.

        Args:
            method: The RPC method to retry.
            params: Original parameters.
            source_path: Original source path.
            allow_null: Original allow_null setting.
            original_error: The auth error that triggered this retry.

        Returns:
            The RPC result if retry succeeds, None if refresh failed.

        Raises:
            The original error (with refresh error as cause) if refresh fails.
        """
        logger.info(
            "RPC %s auth error detected, attempting token refresh",
            method.name,
        )

        # This function is only called when _refresh_callback is set
        assert self._refresh_callback is not None

        # Use lock to coordinate refresh task creation
        # Note: refresh_callback is expected to update auth headers internally
        # Lock is always created when callback is set (see __init__)
        assert self._refresh_lock is not None

        # Determine which task to await (existing or new)
        started_refresh = False
        async with self._refresh_lock:
            if self._refresh_task is not None and not self._refresh_task.done():
                # Another refresh is in progress, wait on it
                refresh_task = self._refresh_task
                logger.debug("Waiting on existing refresh task for RPC %s", method.name)
            else:
                # Start a new refresh task
                # Cast needed: Awaitable → Coroutine for create_task (async funcs return coroutines)
                coro = cast(Coroutine[Any, Any, AuthTokens], self._refresh_callback())
                self._refresh_task = asyncio.create_task(coro)
                refresh_task = self._refresh_task
                started_refresh = True

        # Await refresh outside the lock so other callers can join
        try:
            await refresh_task
        except Exception as refresh_error:
            logger.warning("Token refresh failed: %s", refresh_error)
            raise original_error from refresh_error

        if started_refresh:
            self._record_transport_event(
                "auth.refreshed",
                {
                    "method": method.value,
                    "rpc_method": method.name,
                    "source_path": source_path,
                    "trigger": type(original_error).__name__,
                    "message": str(original_error),
                },
            )

        # Brief delay before retry to avoid hammering the API
        if self._refresh_retry_delay > 0:
            await asyncio.sleep(self._refresh_retry_delay)

        logger.info("Token refresh successful, retrying RPC %s", method.name)

        # Retry with refreshed tokens
        return await self.rpc_call(
            method,
            params,
            source_path,
            allow_null,
            _is_retry=True,
            _rate_limit_retry_count=rate_limit_retry_count,
        )

    def _parse_retry_after_seconds(self, retry_after_header: str | None) -> int | None:
        """Parse a Retry-After value into seconds when possible."""
        if not retry_after_header:
            return None

        try:
            retry_after = int(retry_after_header)
        except ValueError:
            return None

        return retry_after if retry_after > 0 else None

    def _calculate_rate_limit_delay(
        self,
        attempt: int,
        *,
        retry_after: int | None = None,
    ) -> float:
        """Return the delay before the next 429 retry attempt."""
        if retry_after is not None:
            return float(retry_after)

        delay = min(
            self._rate_limit_initial_delay * (2**attempt),
            self._rate_limit_max_delay,
        )
        jitter = random.uniform(0.0, delay * self._rate_limit_jitter_ratio)
        return min(delay + jitter, self._rate_limit_max_delay)

    async def _retry_after_rate_limit(
        self,
        method: RPCMethod,
        params: list[Any],
        source_path: str,
        allow_null: bool,
        rate_limit_error: RateLimitError,
        *,
        _is_retry: bool,
        rate_limit_retry_count: int,
    ) -> Any:
        """Sleep with jittered backoff, then retry the RPC after a rate limit."""
        delay = self._calculate_rate_limit_delay(
            rate_limit_retry_count,
            retry_after=rate_limit_error.retry_after,
        )
        self._record_transport_event(
            "transport.retry",
            {
                "method": method.value,
                "rpc_method": method.name,
                "source_path": source_path,
                "reason": "rate_limit",
                "attempt": rate_limit_retry_count + 1,
                "max_retries": self._rate_limit_max_retries,
                "delay_s": round(delay, 3),
                "retry_after_s": rate_limit_error.retry_after,
            },
        )
        logger.warning(
            "RPC %s rate limited; retrying in %.3fs (attempt %s/%s)",
            method.name,
            delay,
            rate_limit_retry_count + 1,
            self._rate_limit_max_retries,
        )
        if delay > 0:
            await asyncio.sleep(delay)

        return await self.rpc_call(
            method,
            params,
            source_path,
            allow_null,
            _is_retry=_is_retry,
            _rate_limit_retry_count=rate_limit_retry_count + 1,
        )

    def get_http_client(self) -> httpx.AsyncClient:
        """Get the underlying HTTP client for direct requests.

        Used by download operations that need direct HTTP access.

        Returns:
            The httpx.AsyncClient instance.

        Raises:
            RuntimeError: If client is not initialized.
        """
        if not self._http_client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return self._http_client

    def cache_conversation_turn(
        self, conversation_id: str, query: str, answer: str, turn_number: int
    ) -> None:
        """Cache a conversation turn locally.

        Uses FIFO eviction when cache exceeds MAX_CONVERSATION_CACHE_SIZE.

        Args:
            conversation_id: The conversation ID.
            query: The user's question.
            answer: The AI's response.
            turn_number: The turn number in the conversation.
        """
        is_new_conversation = conversation_id not in self._conversation_cache

        # Only evict when adding a NEW conversation at capacity
        if is_new_conversation:
            while len(self._conversation_cache) >= MAX_CONVERSATION_CACHE_SIZE:
                # popitem(last=False) removes oldest entry (FIFO)
                self._conversation_cache.popitem(last=False)
            self._conversation_cache[conversation_id] = []

        self._conversation_cache[conversation_id].append(
            {
                "query": query,
                "answer": answer,
                "turn_number": turn_number,
            }
        )

    def get_cached_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """Get cached conversation turns.

        Args:
            conversation_id: The conversation ID.

        Returns:
            List of cached turns, or empty list if not found.
        """
        return self._conversation_cache.get(conversation_id, [])

    def clear_conversation_cache(self, conversation_id: str | None = None) -> bool:
        """Clear conversation cache.

        Args:
            conversation_id: Clear specific conversation, or all if None.

        Returns:
            True if cache was cleared.
        """
        if conversation_id:
            if conversation_id in self._conversation_cache:
                del self._conversation_cache[conversation_id]
                return True
            return False
        else:
            self._conversation_cache.clear()
            return True

    async def get_source_ids(self, notebook_id: str) -> list[str]:
        """Extract all source IDs from a notebook.

        Fetches notebook data and extracts source IDs for use with
        chat and artifact generation when targeting specific sources.

        Args:
            notebook_id: The notebook ID.

        Returns:
            List of source IDs. Empty list if no sources or on error.

        Note:
            Source IDs are triple-nested in RPC: source[0][0] contains the ID.
        """
        params = [notebook_id, None, [2], None, 0]
        notebook_data = await self.rpc_call(
            RPCMethod.GET_NOTEBOOK,
            params,
            source_path=f"/notebook/{notebook_id}",
        )

        source_ids: list[str] = []
        if not notebook_data or not isinstance(notebook_data, list):
            return source_ids

        try:
            if len(notebook_data) > 0 and isinstance(notebook_data[0], list):
                notebook_info = notebook_data[0]
                if len(notebook_info) > 1 and isinstance(notebook_info[1], list):
                    sources = notebook_info[1]
                    for source in sources:
                        if isinstance(source, list) and len(source) > 0:
                            first = source[0]
                            if isinstance(first, list) and len(first) > 0:
                                sid = first[0]
                                if isinstance(sid, str):
                                    source_ids.append(sid)
        except (IndexError, TypeError):
            pass

        return source_ids
