# Test-only shell/curl image

This scoped directory is the complete build context; it contains no application,
private `.local` files, credentials, model SDK or runtime configuration. It uses
the Platform runtime family `eclipse-temurin:21-jre-jammy`, with the official image
index fixed to `sha256:affcab5356e1270ac35d2361ee83135af2f03e8d580eca78a6d5d6fdbf048db0`.
Root verified the active public Docker Hub tag metadata on 2026-10-18 at
[the official public catalog endpoint](https://hub.docker.com/v2/repositories/library/eclipse-temurin/tags/21-jre-jammy).
That lookup is provenance for the base reference, not successful local build evidence.

The image exists only to run the real `/bin/sh` and `/usr/bin/curl` against local
synthetic sockets in `scripts/test-agent-network.py`. Java is not started and no
Platform JAR is copied. Its inspected immutable local image ID is selected only
after CI builds it; that local ID is not a registry digest or release artifact.

curl uses the [curl license](https://curl.se/docs/copyright.html); Ubuntu system
packages retain their respective licenses and package notices. Temurin/OpenJDK
includes GPLv2 with the Classpath Exception; retain the base image's licenses and
refer to [Eclipse Temurin licensing](https://adoptium.net/docs/faq/#_what_licenses_are_used_for_openjdk_and_your_temurin_builds).
CI records `curl --version` and `dpkg-query` package/version inventory. apt curl,
its dependencies, and build tooling are not fully locked, so the pinned base does
not make this image bit reproducible. Build, signature, package, or registry
failures stop CI; there is no mirror, DNS, security, or proxy workaround.

Alternative: build the complete Platform image. This fixture keeps the runtime
shell/curl behavior needed by the wrapper test without building unrelated Java
application sources or bringing a candidate JAR into an offline network test.
It is not a substitute for actual candidate JAR/image/build-flag verification.
