ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY --chown=10001:10001 backend/services/reception_work.py /app/backend/services/reception_work.py
COPY --chown=10001:10001 frontend/static/reception-work.js frontend/static/reception-work.css /app/frontend/static/
COPY infrastructure/reception-work-overlay/prepare.py /opt/wms-reception-work/prepare.py
RUN python /opt/wms-reception-work/prepare.py /app
