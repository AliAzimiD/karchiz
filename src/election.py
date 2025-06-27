import asyncio
import os
from kubernetes_asyncio import client, config, watch

LEASE_NAME = os.getenv("LEASE_NAME", "karchiz-leader")
LEASE_NS = os.getenv("LEASE_NAMESPACE", "default")
RENEW_SECONDS = int(os.getenv("LEASE_RENEW_SECONDS", "30"))


class LeaderElection:
    """Simple leader election using the Kubernetes Lease API."""

    def __init__(self) -> None:
        self.identity = os.getenv("POD_NAME", "unknown")
        self._lease: client.V1Lease | None = None

    async def acquire(self) -> bool:
        await config.load_incluster_config()
        api = client.CoordinationV1Api()
        body = client.V1Lease(
            metadata=client.V1ObjectMeta(name=LEASE_NAME),
            spec=client.V1LeaseSpec(
                holder_identity=self.identity,
                lease_duration_seconds=RENEW_SECONDS,
            ),
        )
        try:
            self._lease = await api.create_namespaced_lease(LEASE_NS, body)
            return True
        except client.ApiException as exc:
            if exc.status == 409:
                return await self._renew(api)
            raise

    async def _renew(self, api: client.CoordinationV1Api) -> bool:
        body = {"spec": {"holderIdentity": self.identity}}
        await api.patch_namespaced_lease(LEASE_NAME, LEASE_NS, body)
        return True

    async def hold(self) -> None:
        api = client.CoordinationV1Api()
        while True:
            await asyncio.sleep(RENEW_SECONDS / 2)
            await self._renew(api)

    async def watch(self) -> None:
        api = client.CoordinationV1Api()
        w = watch.Watch()
        async for _ in w.stream(api.list_namespaced_lease, LEASE_NS, timeout_seconds=0):
            pass
