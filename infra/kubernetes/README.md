# Platform configuration moved

The authoritative Kubernetes pilot and GPU readiness checks now live in the private [Enterprise-AI-Hub repository](https://github.com/srimon/Enterprise-AI-Hub/tree/main/infra/kubernetes/pilot).

The files were imported from Jobsearch commit a7bafea1c18830ea9936445058b35f117fe434b6 and verified byte-for-byte against the pushed hub commit a2a83c1d6f20cd720a59d17b7acd1a8247a05cd0 before removing the duplicate working copies here. Historical source remains available in this repository's Git history.

Jobsearch's Docker Compose deployment, collection agents, monitoring adapters and app-specific readiness check remain here. Nothing was deployed or migrated by this source separation.
