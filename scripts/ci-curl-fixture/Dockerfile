# Test-only /bin/sh + real curl characterization. No application or credentials.
# Same OS/runtime family as Platform, with separately verified official index.
FROM eclipse-temurin:21-jre-jammy@sha256:affcab5356e1270ac35d2361ee83135af2f03e8d580eca78a6d5d6fdbf048db0
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
ENTRYPOINT ["/bin/sh"]
