FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional local converter for the STEP publishing demo.
ARG INSTALL_STEP_PDF=0
COPY tools/step_pdf/ /opt/plm-step-pdf/
RUN if [ "$INSTALL_STEP_PDF" = 1 ]; then \
      set -eu; \
      apt-get update; \
      apt-get install -y --no-install-recommends freecad-python3 git g++ zlib1g-dev; \
      git clone https://github.com/XenonofArcticus/libPRC.git /tmp/libprc; \
      git -C /tmp/libprc checkout 474fe401e444804116021e5460365b9c0a2c0a2d; \
      src=/tmp/libprc/src/asymptote; \
      g++ -O2 -std=c++17 -fPIC -shared -I"$src" \
        "$src/oPRCFile.cc" "$src/writePRC.cc" "$src/PRCdouble.cc" "$src/PRCbitStream.cc" \
        -lz -o /opt/plm-step-pdf/libasymptote-prc.so; \
      g++ -O2 -std=c++17 -I"$src" /opt/plm-step-pdf/mesh_to_prc.cpp \
        -L/opt/plm-step-pdf -lasymptote-prc -Wl,-rpath,/opt/plm-step-pdf -lz \
        -o /usr/local/bin/mesh-to-prc; \
      cp "$src/LICENSE" "$src/LICENSE.LESSER" /opt/plm-step-pdf/; \
      cp -r "$src" /opt/plm-step-pdf/prc-source; \
      chmod +x /opt/plm-step-pdf/run; \
      rm -rf /tmp/libprc /var/lib/apt/lists/*; \
    fi

COPY schema.sql .
COPY app/ ./app/
COPY static/ ./static/

RUN mkdir -p /srv/plm/files /srv/plm

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
