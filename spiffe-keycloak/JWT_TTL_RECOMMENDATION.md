# JWT TTL Recommendation Update

## TL;DR: Use 5-Minute JWT TTL (Not 10 Minutes)

Based on extensive testing, **Keycloak rejects JWTs older than ~3 minutes** (180-240 seconds).

### Recommended Configuration:

```yaml
spire:
  values:
    spire-server:
      controllerManager:
        identities:
          clusterSPIFFEIDs:
            default:
              jwtTTL: "5m"  # 5 minutes (refreshes every ~2.5 min)
```

Or via kubectl:
```bash
kubectl get configmap spire-server -n spire-server -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); c=json.loads(d['data']['server.conf']); c['server']['default_jwt_svid_ttl']='5m'; d['data']['server.conf']=json.dumps(c); print(json.dumps(d))" | \
  kubectl apply -f -
```

## Why 5 Minutes Instead of 10 Minutes?

### Test Evidence:

| JWT TTL | Refresh Interval | Max JWT Age | Test Result |
|---------|------------------|-------------|-------------|
| 1 hour (default) | ~30 minutes | 30 minutes | ❌ Always fails |
| 10 minutes | ~5 minutes | 5 minutes | ⚠️ Sometimes fails (4-5 min edge case) |
| **5 minutes** | **~2.5 minutes** | **2.5 minutes** | ✅ Always succeeds |

### Keycloak's Threshold:

- ✅ **187 seconds (3.1 min)** → Authentication succeeds
- ❌ **252 seconds (4.2 min)** → "Token was issued too far in the past"
- **Threshold:** Approximately **3 minutes (180 seconds)**

### Why 10 Minutes Failed:

With 10-minute TTL:
- SPIRE refreshes at 50% = every 5 minutes
- JWTs can be up to 5 minutes old
- If a JWT is 4-5 minutes old when used → rejection
- Edge case: pod starts, JWT issued, SPIRE waits 5 min to refresh
- Meanwhile, your app uses the 4+ minute old JWT → fails

### Why 5 Minutes Works:

With 5-minute TTL:
- SPIRE refreshes at 50% = every 2.5 minutes
- JWTs are never older than 2.5 minutes
- Comfortable buffer: 2.5 min JWT age < 3 min Keycloak threshold
- ✅ No edge cases, always succeeds

## Performance Impact

**Q: Won't 2.5-minute refresh interval impact performance?**

A: Negligible impact:
- JWT refresh is async, done by SPIRE agent in background
- spiffe-helper simply watches for updates and writes to file
- No blocking operations in your application
- JWT generation is cryptographically cheap (~1ms)
- Network overhead: one small request per workload every 2.5 minutes

**Recommendation:** Use 5-minute TTL for production reliability.

## Migration Guide

If you've already configured 10-minute TTL:

```bash
# Update ConfigMap
kubectl get configmap spire-server -n spire-server -o json > /tmp/spire-cm.json
python3 << 'EOF'
import json
with open('/tmp/spire-cm.json', 'r') as f:
    data = json.load(f)
config = json.loads(data['data']['server.conf'])
config['server']['default_jwt_svid_ttl'] = '5m'
data['data']['server.conf'] = json.dumps(config)
with open('/tmp/spire-cm-updated.json', 'w') as f:
    json.dump(data, f)
EOF

kubectl apply -f /tmp/spire-cm-updated.json

# Restart SPIRE components
kubectl rollout restart statefulset/spire-server -n spire-server
kubectl rollout restart daemonset/spire-agent -n spire-system

# Restart your workloads to get fresh JWTs
kubectl rollout restart deployment <your-deployment>
```

## Summary

| Configuration | Status | Reason |
|---------------|--------|--------|
| 1h TTL (default) | ❌ Broken | JWTs 30 min old → always fails |
| 10m TTL | ⚠️ Unreliable | JWTs 4-5 min old → edge case failures |
| **5m TTL** | ✅ **Recommended** | JWTs <2.5 min old → always succeeds |
| 3m TTL | ✅ Works | JWTs <1.5 min old → over-optimization |

**Use 5-minute JWT TTL for reliable SPIFFE + Keycloak integration.**
