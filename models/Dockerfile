FROM debian:bullseye

RUN apt-get update && apt-get install -y cmake g++ git automake time \
        libboost-all-dev libcln-dev libgmp-dev libginac-dev libglpk-dev libhwloc-dev libz3-dev libxerces-c-dev libeigen3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/storm
RUN mkdir -p /opt/storm/build
WORKDIR /opt/storm/build

# Specify number of threads to use for parallel compilation
# This number can be set from the commandline with:
# --build-arg no_threads=<value>
ARG no_threads=1

RUN cmake .. -DCMAKE_BUILD_TYPE=Release -DSTORM_DEVELOPER=OFF -DSTORM_LOG_DISABLE_DEBUG=ON -DSTORM_PORTABLE=OFF -DSTORM_USE_SPOT_SHIPPED=ON

RUN make resources storm binaries -j $no_threads

ENV PATH="/opt/storm/build/bin:$PATH"

RUN useradd -ms /bin/bash storm
WORKDIR /home/storm
USER storm
