FROM ubuntu:16.04
MAINTAINER Jorge Trujillo <jorge.a.trujillo@target.com>

# Install Python and dependencies
RUN \
  apt-get update && apt-get install -y --no-install-recommends \
    cron \
    iputils-ping dnsutils curl tzdata \
    python \
    vim \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

RUN cd /tmp/ \
  && curl -k "https://bootstrap.pypa.io/get-pip.py" -o "get-pip.py" \
  && python get-pip.py \
  && rm get-pip.py

RUN pip install --upgrade pip
RUN pip install requests arrow dnspython

ENV PYTHONUNBUFFERED=1

# Copy scripts
RUN mkdir -p /apps/scripts
COPY scripts/* /apps/scripts/

#Set timezone to America/Chicago
ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

CMD ["/apps/scripts/startpoint.sh"]
