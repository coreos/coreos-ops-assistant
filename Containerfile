# Use the latest Fedora image
FROM quay.io/fedora/fedora-minimal:42

# Install Python, pip, and any other required dependencies
RUN dnf install -y python3-pip && dnf clean all

# Set the working directory in the container
WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .
COPY *.py .

# Install dependencies
RUN pip3 install --no-cache-dir --root-user-action=ignore -r requirements.txt