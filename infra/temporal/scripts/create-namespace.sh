#!/bin/sh
set -eu

address="${TEMPORAL_ADDRESS:-temporal:7233}"
namespace="${TEMPORAL_NAMESPACE:-agentfactory}"
retention="${TEMPORAL_NAMESPACE_RETENTION:-7d}"

until temporal operator cluster health --address "$address" >/dev/null 2>&1; do
  sleep 2
done

if temporal operator namespace describe --namespace "$namespace" --address "$address" >/dev/null 2>&1; then
  echo "Namespace '$namespace' already exists"
else
  temporal operator namespace create --namespace "$namespace" --description "AgentFactory local durable workflows" --retention "$retention" --address "$address"
fi
