FROM python:3.12-slim

# Add repository code
WORKDIR /opt/dagster/app

COPY difan-backend/difan_backend/requirements.txt requirements.txt

# Checkout and install dagster libraries needed to run the gRPC server by exposing
# your code location to dagster-webserver and dagster-daemon, and loading the
# DagsterInstance.
RUN pip install -r requirements.txt

COPY difan-backend/ /opt/dagster/app

# Run dagster gRPC server on port 4000
# exposing your repository to dagster-webserver and dagster-daemon, and to load the DagsterInstance
EXPOSE 4000

# CMD allows this to be overridden from run launchers or executors that want
# to run other commands against your repository
CMD ["dagster", "api", "grpc", "-h", "0.0.0.0", "-p", "4000", "-m", "difan_backend"]
