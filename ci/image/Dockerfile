# Disposable-CI runner image for Lambda MicroVMs.
# Fixed/common image: the job payload (artifact URL + SHA-256 + steps) is what
# carries the code-under-test; the image itself does not change per commit.
FROM python:3.13-slim

COPY ci_agent.py /opt/ci/ci_agent.py

ENV CI_JOB_ROOT=/workspace/ci-jobs
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace
EXPOSE 8080
CMD ["python", "-u", "/opt/ci/ci_agent.py"]
