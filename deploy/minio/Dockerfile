# Official archived source; local course development only.
# Existing Milvus 2.4.9 configuration expects this historical MinIO version.
FROM golang:1.20.14-bookworm AS builder
ARG MINIO_VERSION=RELEASE.2023-03-20T20-16-18Z
WORKDIR /src
RUN git clone --depth 1 --branch ${MINIO_VERSION} https://github.com/minio/minio.git .
RUN CGO_ENABLED=0 go build -mod=readonly -trimpath -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /src/LICENSE /usr/share/doc/minio/LICENSE
EXPOSE 9000 9001
CMD ["minio", "server", "/minio_data", "--console-address", ":9001"]
