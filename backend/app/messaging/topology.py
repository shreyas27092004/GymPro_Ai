from typing import Any
import aio_pika
from ..settings import settings

EXCHANGE_NAME = "gympro.events"
DLX_NAME = "gympro.dlx"

QUEUE_EMAIL = "q.email"
QUEUE_NOTIFY = "q.notify"
QUEUE_DIGEST = "q.digest"
QUEUE_AGENT_ASYNC = "q.agent.async"
QUEUE_DLQ = "q.dlq"

QUEUE_EMAIL_RETRY_30S = "q.email.retry.30s"
QUEUE_EMAIL_RETRY_5M = "q.email.retry.5m"
QUEUE_EMAIL_RETRY_30M = "q.email.retry.30m"


async def setup_topology(
    channel: aio_pika.abc.AbstractChannel,
    retry_ttl_30s: int = 30_000,
    retry_ttl_5m: int = 300_000,
    retry_ttl_30m: int = 1_800_000,
) -> dict[str, Any]:
    """
    Sets up all RabbitMQ exchanges, dead-letter exchanges, queues, retry queues, and bindings
    as defined in GymPro AI Spec section 9.1.
    """
    # 1. Main & Dead-Letter Exchanges (topic, durable)
    events_exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )
    dlx_exchange = await channel.declare_exchange(
        DLX_NAME,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )

    # 2. Dead-Letter Queue (q.dlq)
    q_dlq = await channel.declare_queue(
        QUEUE_DLQ,
        durable=True,
    )
    await q_dlq.bind(dlx_exchange, routing_key="q.dlq")
    try:
        await q_dlq.unbind(dlx_exchange, routing_key="#")
    except Exception:
        pass

    # 3. Email Work Queue (with dead-lettering to dlx on rejection)
    q_email = await channel.declare_queue(
        QUEUE_EMAIL,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_NAME,
            "x-dead-letter-routing-key": "email.retry.30s",
        },
    )
    await q_email.bind(events_exchange, routing_key="email.#")

    # 4. Email Retry Queues (message-ttl dead-lettering back to main exchange)
    q_retry_30s = await channel.declare_queue(
        QUEUE_EMAIL_RETRY_30S,
        durable=True,
        arguments={
            "x-message-ttl": retry_ttl_30s,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": "email.retry.deliver",
        },
    )
    await q_retry_30s.bind(dlx_exchange, routing_key="email.retry.30s")

    q_retry_5m = await channel.declare_queue(
        QUEUE_EMAIL_RETRY_5M,
        durable=True,
        arguments={
            "x-message-ttl": retry_ttl_5m,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": "email.retry.deliver",
        },
    )
    await q_retry_5m.bind(dlx_exchange, routing_key="email.retry.5m")

    q_retry_30m = await channel.declare_queue(
        QUEUE_EMAIL_RETRY_30M,
        durable=True,
        arguments={
            "x-message-ttl": retry_ttl_30m,
            "x-dead-letter-exchange": EXCHANGE_NAME,
            "x-dead-letter-routing-key": "email.retry.deliver",
        },
    )
    await q_retry_30m.bind(dlx_exchange, routing_key="email.retry.30m")

    # 5. In-App Notifications Queue (q.notify)
    q_notify = await channel.declare_queue(
        QUEUE_NOTIFY,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_NAME,
            "x-dead-letter-routing-key": "q.dlq",
        },
    )
    await q_notify.bind(events_exchange, routing_key="notify.#")
    await q_notify.bind(events_exchange, routing_key="issue.#")
    await q_notify.bind(events_exchange, routing_key="class.cancelled")

    # 6. Digest & Scheduler Queue (q.digest)
    q_digest = await channel.declare_queue(
        QUEUE_DIGEST,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_NAME,
            "x-dead-letter-routing-key": "q.dlq",
        },
    )
    await q_digest.bind(events_exchange, routing_key="digest.#")

    # 7. Agent Async Queue (q.agent.async)
    q_agent_async = await channel.declare_queue(
        QUEUE_AGENT_ASYNC,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_NAME,
            "x-dead-letter-routing-key": "q.dlq",
        },
    )
    await q_agent_async.bind(events_exchange, routing_key="agent.#")

    return {
        "events_exchange": events_exchange,
        "dlx_exchange": dlx_exchange,
        "q_email": q_email,
        "q_notify": q_notify,
        "q_digest": q_digest,
        "q_agent_async": q_agent_async,
        "q_dlq": q_dlq,
        "retry_queues": [q_retry_30s, q_retry_5m, q_retry_30m],
    }


async def init_broker_topology(url: str | None = None) -> None:
    """Connects to RabbitMQ and ensures topology is declared."""
    broker_url = url or settings.rabbitmq_url
    connection = await aio_pika.connect_robust(broker_url)
    async with connection:
        channel = await connection.channel()
        await setup_topology(channel)
