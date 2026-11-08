# The deployed server (specification 6.5). Each folder is named on purpose, so that nothing local
# (settings/api_keys.env, the spending ledger, saved games) can end up in the image.
FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml ./
COPY nv_core nv_core
COPY nv_world nv_world
COPY nv_server nv_server
COPY nv_ai nv_ai
COPY nv_sim nv_sim
COPY web web
COPY docs docs
COPY scenarios scenarios
COPY settings/software.yaml settings/software.yaml

# Editable, because the code finds docs/, scenarios/ and web/ next to its own folders.
RUN pip install --no-cache-dir -e ".[cloud]"

CMD ["nv-server", "--host", "0.0.0.0"]
