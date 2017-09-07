#!/bin/bash

START_PARAMS=''
if [ -z "$HOST" ]; then
  echo "You must provide a HOST parameter"
fi

if [ -z "$OUTPUT" ]; then
  echo "You must provide a OUTPUT parameter"
fi

if [ ! -z "$INDEX" ]; then
  echo "Using index $INDEX"
  START_PARAMS="$START_PARAMS --index $INDEX"
fi

if [ -z "$CRON_SCHEDULE" ]; then
  $CRON_SCHEDULE="0 1 * * *"
  echo "Defaulting cron schedule to: $CRON_SCHEDULE"
fi

# Configure cron
STDOUT_LOC=${STDOUT_LOC:-/proc/1/fd/1}
STDERR_LOC=${STDERR_LOC:-/proc/1/fd/2}

echo ">> Configuring cron"
echo "${CRON_SCHEDULE} ps -ef | grep -v grep | grep -q backup || /apps/scripts/backup.py --host ${HOST} --output ${OUTPUT} ${START_PARAMS} > ${STDOUT_LOC} 2> ${STDERR_LOC}" | crontab -

echo ">> Starting cron"
exec cron -f
