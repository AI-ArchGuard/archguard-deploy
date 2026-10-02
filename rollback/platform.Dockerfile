# Build only from the separately downloaded and SHA-256-verified v0.4.0 JAR.
# Context must contain platform.jar only, never the workspace or .local credentials.
FROM eclipse-temurin:21-jre-jammy@sha256:e9aaf73145bbd1f9f6ec7f6867dd75a44f34b1a6c32a813504bf4129be2d09d7
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 archguard \
    && useradd --system --uid 10001 --gid archguard --home-dir /nonexistent archguard
COPY platform.jar /opt/archguard/platform.jar
RUN echo '1ab6f01551c1aa79edb42c5365d041f621e9ea3a690f727c1ad4efb7f67c26ba  /opt/archguard/platform.jar' | sha256sum --check --strict
USER 10001:10001
ENTRYPOINT ["java", "-jar", "/opt/archguard/platform.jar"]
