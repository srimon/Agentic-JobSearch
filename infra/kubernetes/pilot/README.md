# Isolated AI Hub pilot configuration

Status: prepared and statically tested; no Kubernetes cluster installed or started. Files are JSON-compatible YAML/JSON to allow dependency-free inspection. This is a synthetic, stateless security pilot, not a production migration. Production remains on Compose.

## Selected starting design

- k3d with one K3s server, zero agent nodes, and 4 GiB server-container memory limit. Candidate image is the version shown in the upstream configuration example; verify supported patches and resolve its immutable digest before installation. This tag is not a vulnerability assessment or immutable image pin.
- Loopback API at 127.0.0.1:6447, no load balancer, Traefik or ServiceLB. Proposed gateway ports 3180 and 31443 remain unpublished. No default kubeconfig/context changes. Save eventual credentials under private .secrets, never Git.
- Default Flannel networking with K3s's built-in kube-router NetworkPolicy controller retained. Prove deny and explicit allow behavior with synthetic pods before any application credentials are introduced. Default-deny includes DNS until a scoped DNS rule is added during the connectivity test.
- Two pilot-only namespaces: ai-hub-pilot and jobsearch-pilot. Restricted pod admission, no automatically mounted service-account token, no RBAC grants, default-deny ingress/egress, container limits, and quotas. Each namespace is capped at 1 CPU and 1 GiB in aggregate pod limits. These are workload quotas, not a cap on Kubernetes control-plane CPU.
- No library namespace, application images, private secrets, host bind mounts, existing Docker networks or volumes. k3d will create its own network/node storage if later started. k3d uses privileged node containers: namespaces are not a boundary against a hostile host administrator or node escape.
- PVC quota zero during this stage. K3s local-path storage is a candidate for disposable later staging only, not an accepted production recovery mechanism. Production PostgreSQL/Qdrant/Redis remain separate. No mail sender or employer submission workload is included.

## Capacity observation — 2026-09-12 UTC

Windows reported 66,812,612 KiB total visible memory and 12,849,652 KiB free (~12.3 GiB). WSL reported 23,474 MiB available within its 31,952 MiB memory limit. C: and G: reported approximately 239 and 227 GiB free respectively; the WSL virtual filesystem reported 848 GiB. Physical disk placement for the VHD and future image growth still require verification; do not interpret the virtual filesystem number as physical capacity. This is a point-in-time snapshot, not a full three-hour workload cycle.

No listeners on proposed ports 6447, 3180 or 31443 were found in Windows or WSL. They are planned, not OS-reserved; recheck immediately before creation. Existing 3105/3106 and library ports are unchanged.

## Installation and acceptance gates

1. Recheck host memory and disk. Initial conservative pilot gate: at least 10 GiB Windows free memory, 8 GiB WSL available, and 20 GiB on the physical volume holding Docker/WSL data. These are operational choices, not upstream requirements. Monitor real usage and stop the pilot if Windows free memory remains below 6 GiB; do not stop existing apps to make room.
2. Download verified k3d/kubectl binaries into a Jobsearch-owned tool directory. Pin checksums and the K3s image digest. Validate cluster.yaml against the selected k3d schema. Inventory live app identifiers/networks/mounts before creation.
3. Create only ai-hub-pilot with this config. Verify actual container memory limit, loopback API binding and network separation. Store a dedicated owner-only kubeconfig; always specify it and the pilot context. No global context changes.
4. Run Kubernetes server-side dry-run on baseline.json, then apply. Reject any target context/name mismatch. Never apply these resources to production or another cluster.
5. Use non-root synthetic workloads to test restricted admission, quotas, no mounted token, denied cross-namespace access, denied outbound access and a narrowly allowed path. Do not probe library endpoints to test denial. Verify policies with independent test endpoints.
6. Compare production service identities and health, then stop only the pilot if validation fails. Do not delete volumes or use global cleanup. No autoscaler, shared data, persistent workload or production cutover until later gates pass.

## References

- https://k3d.io/stable/usage/configfile/
- https://raw.githubusercontent.com/k3d-io/k3d/v5.9.0/pkg/config/v1alpha5/schema.json
- https://docs.k3s.io/networking/networking-services
- https://docs.k3s.io/add-ons/storage


## NVIDIA GPU plan and current blocker

Windows and WSL both detect a GeForce GTX 1650 Ti, 4096 MiB VRAM, driver 581.95. Three nearby observations reported 100% utilization and approximately 96–149 MiB free. Process-level memory was unavailable; no application is blamed for this load and none was stopped. The inspected Docker runtime list showed runc variants, not an NVIDIA runtime; no NVIDIA container CLI or cached CUDA image was found on the inspected PATH/image list. This is not proof that every possible GPU integration is absent. Container CUDA access remains unverified.

Run `JBS/bin/python scripts/gpu_readiness.py` for a fresh metadata-only check. It loads no model, collects no process list and does not enable GPU scheduling. Missing metrics remain unknown. A benchmark candidate requires at least 2048 MiB free and utilization at or below 10%; this conservative gate is neither a VRAM reservation nor a guarantee a model fits.

Use GPU capacity first for a measured small embedding/reranking workload, with one inference request at a time and no model replicas. Keep crawling, API, database and scheduler on CPU. Do not assume a large local LLM fits in 4 GiB. Select the model after a benchmark establishes memory use, latency and output quality on synthetic job text. Changing an embedding model also requires a versioned vector collection and reindex plan; never mix incompatible embeddings or silently replace the current model.

GPU enablement remains blocked by current device load and unverified container support. Do not change the shared Docker daemon or restart it to enable a runtime while existing apps are operating. Verify a no-restart setup path before installation. WSL uses the Windows NVIDIA driver; do not install a Linux display driver inside WSL. k3d additionally requires a compatible GPU-enabled node runtime and NVIDIA device plugin; adding gpuRequest alone is insufficient. Do not enable GPU Operator driver installation or GPU time-slicing/MIG for this card. The CPU pilot configuration intentionally makes no GPU request.

When headroom is available: verify a pinned CUDA test container without production mounts, benchmark a small model with synthetic input, establish a bounded inference queue with an explicit CPU-compatible fallback or deferred state, and then validate Kubernetes GPU allocation with one consumer. Existing application GPU use must take priority until an explicit shared scheduling plan is accepted. CPU fallback must not silently change model semantics or ranking.

Sources: https://docs.nvidia.com/cuda/wsl-user-guide/ and https://k3d.io/v5.4.3/usage/advanced/cuda/ (the latter explains additional runtime/plugin requirements; its old version-specific build commands are not installation instructions for this pilot).
