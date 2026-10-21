# FloBrain meeting assistant: Chromium (Playwright build) + Xvfb + PulseAudio + ffmpeg.
FROM mcr.microsoft.com/playwright:v1.63.0-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends pulseaudio pulseaudio-utils ffmpeg xvfb dumb-init \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY src ./src
# Silence and a black frame for the browser's fake microphone and camera (we never send our own media).
RUN mkdir -p media && ffmpeg -loglevel error -f lavfi -i anullsrc=r=48000:cl=mono -t 10 media/silence.wav \
 && ffmpeg -loglevel error -f lavfi -i color=c=black:s=640x360:r=5 -t 2 -pix_fmt yuv420p media/black.y4m
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh && useradd -m bot && chown -R bot /app
USER bot

ENV CHROMIUM_PATH="" PULSE_SINK=flobrain DISPLAY=:99
ENTRYPOINT ["dumb-init", "--", "./entrypoint.sh"]
