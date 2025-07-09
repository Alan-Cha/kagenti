# Use minimal Python base image
FROM python:3.12-slim

ENV KEYCLOAK_URL=""
ENV KEYCLOAK_REALM=""
ENV KEYCLOAK_ADMIN_USERNAME=""
ENV KEYCLOAK_ADMIN_PASSWORD=""
ENV CLIENT_NAME=""

# Set work directory
WORKDIR /app

# Copy your script
COPY client_registration.py .

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Register client
CMD ["python", "client_registration.py"]