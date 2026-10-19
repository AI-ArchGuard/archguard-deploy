FROM postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2
RUN apk add --no-cache nftables=1.1.5-r2 'python3~3.12'
WORKDIR /opt/archguard/netguard
COPY config.py guard.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/opt/archguard/netguard/guard.py"]
CMD ["serve"]
HEALTHCHECK --interval=5s --timeout=2s --retries=1 CMD ["python3", "/opt/archguard/netguard/guard.py", "health"]
