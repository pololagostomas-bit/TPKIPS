# Preserve each approved variant's app, database and operational workflows.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY --chown=10001:10001 backend/services/cloud_auth.py backend/services/cloud_excel.py backend/services/cloud_sync.py backend/services/cloud_import_policy.py backend/services/purchase_alerts.py /app/backend/services/
COPY --chown=10001:10001 backend/password_policy.py /app/backend/password_policy.py
COPY --chown=10001:10001 frontend/templates/cloud-connection.html frontend/templates/change-password.html /app/frontend/templates/
COPY --chown=10001:10001 frontend/templates/purchase-alerts.html /app/frontend/templates/
COPY --chown=10001:10001 frontend/static/cloud-connection.js frontend/static/cloud-connection.css frontend/static/auth-client.js /app/frontend/static/
COPY --chown=10001:10001 frontend/static/purchase-alerts.js frontend/static/purchase-alerts.css /app/frontend/static/
COPY infrastructure/cloud-overlay/prepare.py /opt/wms-cloud/prepare.py
RUN python /opt/wms-cloud/prepare.py /app
RUN python -c "from zoneinfo import ZoneInfo; ZoneInfo('America/Lima')"

CMD ["python", "-m", "backend.password_policy", "serve"]
