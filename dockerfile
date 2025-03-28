FROM python:3.11-slim AS python-base
WORKDIR /app

ENV PROJECT_ROOT=/app \
    VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH" \
    PYTHONPATH=$PROJECT_ROOT
WORKDIR $PROJECT_ROOT

FROM python-base AS builder
# Install uv
RUN pip install uv==0.6.10 --disable-pip-version-check --only-binary :all:

# Create a virtual environment
# This keeps installed packages isolated and makes them easy to copy
RUN uv venv $VIRTUAL_ENV

# Activate the virtual environment for subsequent RUN instructions
# (Note: ENV PATH is often preferred over source in Dockerfiles)
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy dependency definition
COPY pyproject.toml LICENSE README.md ormodel/ ./
# COPY uv.lock* ./ # Uncomment if using uv lock files

# Install dependencies into the virtual environment using uv
# We don't need --system here as we are targeting the venv PATH
RUN uv pip install -r pyproject.toml --no-cache --extra dev
# Or, using sync:
# RUN uv pip sync pyproject.toml --no-cache # Or uv sync uv.lock --no-cache

# --- Final Stage ---
FROM python-base AS final
# Copy the virtual environment with installed dependencies from the builder stage
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}

# --- Runtime ---
# Expose the port the app runs on (if applicable)
# EXPOSE 8000

# Define the command to run your application
# Python from the venv will be used due to PATH modification
CMD ["python", "your_main_script.py"]