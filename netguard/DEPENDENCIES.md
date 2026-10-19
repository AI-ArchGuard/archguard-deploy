# Guard runtime dependencies

The pinned base is `postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2` (Alpine 3.23.3). Its PostgreSQL binaries remain an extra attack surface; its original entrypoint is replaced and no database is started. Reusing this already pinned base avoids inventing an unverified image digest. The guard uses no model SDK, pip packages or runtime package installation.

- nftables `1.1.5-r2`, GPL-2.0-or-later: [Alpine package and source metadata](https://pkgs.alpinelinux.org/package/v3.23/main/x86_64/nftables), [upstream source/releases](https://netfilter.org/projects/nftables/downloads.html), [license](https://git.netfilter.org/nftables/tree/COPYING).
- Python 3.12 from the signed Alpine 3.23 repository, PSF-2.0: [Alpine package and source metadata](https://pkgs.alpinelinux.org/package/v3.23/main/x86_64/python3), [Python sources](https://www.python.org/downloads/source/), [license](https://docs.python.org/3.12/license.html). Only its standard library is used.

Builds must record the actual image ID and `apk info -v` inventory, including transitive packages (for example libmnl/libnftnl and Python runtime libraries). These packages and the Python patch version are not fully locked; the base digest and direct nftables version do not imply bit reproducibility. Repository availability/signatures and kernel nft support must be verified; failures stop the gate. No successful build or package inventory is claimed by this document.

Before distributing an image, include the corresponding package versions, license notices and accessible corresponding source, including GPL obligations for nftables and any transitive components. This task does not publish an image. Alternatives considered: host firewall changes affect other stacks; an HTTP/TLS proxy changes the approved direct client contract; an unverified third-party image lacks the required provenance.
