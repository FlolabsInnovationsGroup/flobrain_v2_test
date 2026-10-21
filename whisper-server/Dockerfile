# FloBrain Whisper service (faster-whisper). CPU by default; for a GPU use an nvidia/cuda runtime base
# with cuDNN and set WHISPER_DEVICE=cuda.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir faster-whisper==1.2.1
WORKDIR /app
COPY app.py .
RUN useradd -m whisper
USER whisper
ENV WHISPER_MODEL=small WHISPER_DEVICE=cpu WHISPER_COMPUTE_TYPE=int8 PORT=8000 HF_HOME=/home/whisper/.cache
EXPOSE 8000
CMD ["python", "-u", "app.py"]
