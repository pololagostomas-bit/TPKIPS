ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN pip install --no-cache-dir holidays==0.106
USER 10001:10001
COPY --chown=10001:10001 backend/services/reception_work.py backend/services/reception_sla.py backend/services/reception_closure.py backend/services/reception_projection.py /app/backend/services/
COPY --chown=10001:10001 frontend/static/reception-work.js frontend/static/reception-work.css /app/frontend/static/
COPY infrastructure/reception-work-overlay/prepare.py /opt/wms-reception-work/prepare.py
RUN python /opt/wms-reception-work/prepare.py /app
