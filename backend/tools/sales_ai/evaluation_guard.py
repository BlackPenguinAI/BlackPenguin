"""Process-local evaluation firewall and model-call budget."""
from contextlib import ExitStack, contextmanager
import socket
import math
from unittest.mock import patch
import httpx


class EvaluationBlocked(RuntimeError):
    pass


class Budget:
    def __init__(self, maximum):
        self.maximum = maximum
        self.calls = 0
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'cost_usd': 0.0,
                      'responses_with_cost':0}
        self.blocked = 0

    def authorize(self, request):
        url = request.url
        if not (url.scheme == 'https' and url.host == 'openrouter.ai'
                and url.port in (None, 443) and url.path == '/api/v1/chat/completions'
                and request.method == 'POST' and not url.query):
            self.blocked += 1
            raise EvaluationBlocked('Only OpenRouter inference is allowed.')
        if self.calls >= self.maximum:
            raise EvaluationBlocked('Model-call budget exhausted.')
        self.calls += 1


@contextmanager
def guard(budget):
    """Only for the dedicated worker process, never an application request."""
    original_send = httpx.AsyncClient.send
    original_dns = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    allowed = set()

    def dns(host, port, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name != 'openrouter.ai' or port not in (443, '443'):
            budget.blocked += 1
            raise EvaluationBlocked('Outbound DNS destination blocked.')
        result = original_dns(host, port, *args, **kwargs)
        allowed.update(row[4][0] for row in result)
        return result

    def connect(sock, address):
        # Local event-loop socketpairs do not use connect; no local services allowed.
        if not isinstance(address, tuple) or address[0] not in allowed or address[1] != 443:
            budget.blocked += 1
            raise EvaluationBlocked('Outbound socket destination blocked.')
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if not isinstance(address, tuple) or address[0] not in allowed or address[1] != 443:
            budget.blocked += 1
            raise EvaluationBlocked('Outbound socket destination blocked.')
        return original_connect_ex(sock, address)

    async def send(client, request, *args, **kwargs):
        budget.authorize(request)
        response = await original_send(client, request, *args, **kwargs)
        await response.aread()
        try:
            usage = response.json().get('usage') or {}
            for key in ('prompt_tokens','completion_tokens'):
                budget.usage[key] += max(0, int(usage.get(key) or 0))
            if usage.get('cost') is not None:
                cost = float(usage['cost'])
                if math.isfinite(cost) and cost >= 0:
                    budget.usage['cost_usd'] += cost
                    budget.usage['responses_with_cost'] += 1
        except (ValueError, TypeError, AttributeError):
            pass
        return response

    def deny_sync(*args, **kwargs):
        budget.blocked += 1
        raise EvaluationBlocked('Synchronous HTTP is disabled in evaluation.')

    def deny_datagram(*args, **kwargs):
        budget.blocked += 1
        raise EvaluationBlocked('Datagram delivery is disabled in evaluation.')

    with ExitStack() as stack:
        stack.enter_context(patch.object(httpx.AsyncClient, 'send', send))
        stack.enter_context(patch.object(httpx.Client, 'send', deny_sync))
        stack.enter_context(patch.object(socket, 'getaddrinfo', dns))
        stack.enter_context(patch.object(socket.socket, 'connect', connect))
        stack.enter_context(patch.object(socket.socket, 'connect_ex', connect_ex))
        stack.enter_context(patch.object(socket.socket, 'sendto', deny_datagram))
        yield budget
