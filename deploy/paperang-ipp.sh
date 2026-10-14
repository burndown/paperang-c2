#!/bin/sh
# Called by ippeveprinter once per document: $1 = spool file, $CONTENT_TYPE = its MIME type,
# job attributes arrive as IPP_* environment variables. Settings come from /etc/default/paperang-c2.
#
# Debug switch: while /tmp/paperang-ipp.dry exists nothing is printed; the job attributes are
# appended to /tmp/paperang-ipp.dry.log and the document is copied to /tmp/paperang-ipp.dry.d/.
# Remove the file to print again. Spool files are not kept otherwise (they are what you print).
[ -r /etc/default/paperang-c2 ] && . /etc/default/paperang-c2
if [ -e /tmp/paperang-ipp.dry ]; then
  mkdir -p /tmp/paperang-ipp.dry.d && cp "$1" /tmp/paperang-ipp.dry.d/ 2>/dev/null
  { echo "=== $(date '+%F %T') file=$1 type=${CONTENT_TYPE:-}"; env | grep -E '^(IPP_|CONTENT_TYPE|DEVICE_URI|OUTPUT_|SERVER_)' | sort; } >> /tmp/paperang-ipp.dry.log
  exit 0
fi
cd "$(dirname "$0")/.." || exit 1
exec python3 -m paperang_c2 ipp-job --content-type "${CONTENT_TYPE:-}" "$1"
