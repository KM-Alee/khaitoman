# Reuse the independently locked/prebuilt vision environment, never the API image.
FROM aabflow-vision:local
WORKDIR /app
COPY vision/configs ./vision/configs
COPY vision/*.py ./vision/
