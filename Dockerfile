# ---------- stage 1: Android APK (plain SDK tools, no Gradle). Never blocks the server deploy.
FROM ghcr.io/cirruslabs/android-sdk:35 AS apk
ARG PUBLIC_URL
ARG APK_KEYSTORE_B64
ARG APK_KS_PASS
ARG APP_VERSION_CODE
WORKDIR /apk
COPY android/ .
RUN mkdir -p dist && (bash build_apk.sh || echo "!!! APK build failed — server will deploy without /download")

# ---------- stage 2: server
FROM python:3.12-slim-bookworm

# pg_dump/pg_restore 18 for backups
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get purge -y gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=apk /apk/dist/ /srv/dist/
RUN useradd -m appuser && mkdir -p /srv/backups && chown -R appuser /srv
USER appuser
ENV BACKUP_DIR=/srv/backups
EXPOSE 8080
CMD ["python", "-m", "app"]
