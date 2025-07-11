# Use the latest Fedora image
FROM quay.io/fedora/fedora-minimal:42

# Install Python, pip, and any other required dependencies
RUN dnf install -y python3-pip python3-devel make gcc-c++ && dnf clean all

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the local code to the container
COPY requirements.txt .
COPY . .

# Install dependencies
RUN pip3 install --no-cache-dir --root-user-action=ignore -r requirements.txt

# Command to run the application
# The environment variables should be passed in at runtime
# (e.g., using `podman run -e ...` or a .env file)
CMD ["python3", "main.py"]
