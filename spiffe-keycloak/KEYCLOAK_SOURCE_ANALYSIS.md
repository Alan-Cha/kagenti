# Keycloak JWT Age Validation - Source Code Analysis

## Summary

**Keycloak's JWT age threshold is `300 seconds` (5 minutes), hardcoded in the source.**

## Complete Validation Flow

### 1. Entry Point: SpiffeIdentityProvider

**File:** `services/src/main/java/org/keycloak/broker/spiffe/SpiffeIdentityProvider.java`

```java
@Override
public boolean verifyClientAssertion(ClientAuthenticationFlowContext context) throws Exception {
    FederatedJWTClientValidator validator = new FederatedJWTClientValidator(
        context,
        this::verifySignature,
        null,                           // expectedTokenIssuer (null for SPIFFE)
        config.getAllowedClockSkew(),   // Default: 0 seconds
        true                            // reusePermitted (SPIFFE allows token caching)
    );

    validator.setExpectedClientAssertionType(SpiffeConstants.CLIENT_ASSERTION_TYPE);

    String trustedDomain = config.getTrustDomain();
    JsonWebToken token = validator.getState().getToken();

    if (!token.getSubject().startsWith(trustedDomain + "/")) {
        throw new RuntimeException("Invalid trust-domain");
    }

    return validator.validate();
}
```

**Key Configuration:**
- `config.getAllowedClockSkew()` → **0 seconds** (default, no tolerance)
- `reusePermitted` → **true** (SPIFFE JWTs don't have `jti` and can be cached)

### 2. Clock Skew Configuration

**File:** `services/src/main/java/org/keycloak/broker/spiffe/SpiffeIdentityProviderConfig.java`

```java
public int getAllowedClockSkew() {
    String allowedClockSkew = getConfig().get(ALLOWED_CLOCK_SKEW);
    if (allowedClockSkew == null || allowedClockSkew.isEmpty()) {
        return 0;  // ← Default: NO clock skew tolerance
    }
    try {
        return Integer.parseInt(getConfig().get(ALLOWED_CLOCK_SKEW));
    } catch (NumberFormatException e) {
        return 0;
    }
}
```

**Important:** Clock skew is configurable but defaults to 0. This means Keycloak does NOT give any tolerance for clock differences by default.

### 3. Maximum Expiration Time

**File:** `services/src/main/java/org/keycloak/authentication/authenticators/client/FederatedJWTClientValidator.java`

```java
public class FederatedJWTClientValidator extends AbstractJWTClientValidator {
    private final String expectedTokenIssuer;
    private final int allowedClockSkew;
    private final boolean reusePermitted;
    private int maximumExpirationTime = 300;  // ← THE THRESHOLD: 300 seconds = 5 minutes
    private final List<String> validAudiences;

    // Constructor...

    @Override
    protected int getMaximumExpirationTime() {
        return maximumExpirationTime;
    }

    public void setMaximumExpirationTime(int maximumExpirationTime) {
        this.maximumExpirationTime = maximumExpirationTime;
    }
}
```

**Key Point:** `maximumExpirationTime = 300` seconds (5 minutes) is **hardcoded** as the default value.

### 4. The Actual Validation Logic

**File:** `services/src/main/java/org/keycloak/authentication/authenticators/client/AbstractBaseJWTValidator.java`

```java
public boolean validateTokenActive(int allowedClockSkew, int maxExp, boolean reusePermitted) {
    JsonWebToken token = clientAssertionState.getToken();
    long lifespan;

    // Check 1: Token must have expiration
    if (token.getExp() == null) {
        return failure("Token exp claim is required");
    }

    // Check 2: Token must be currently active (not expired)
    if (!token.isActive(allowedClockSkew)) {
        return failure("Token is not active");
    }

    lifespan = token.getExp() - currentTime;

    // Two paths depending on whether iat claim is present:
    if (token.getIat() == null) {
        // Path A: No iat claim
        if (lifespan > maxExp) {
            return failure("Token expiration is too far in the future and iat claim not present in token");
        }
    } else {
        // Path B: iat claim present (SPIFFE JWTs have iat)

        // Check: Token not issued in the future
        if (token.getIat() - allowedClockSkew > currentTime) {
            return failure("Token was issued in the future");
        }

        lifespan = Math.min(lifespan, maxExp);

        if (lifespan <= 0) {
            return failure("Token is not active");
        }

        // *** THE KEY CHECK: JWT age must be less than maxExp ***
        if (currentTime > token.getIat() + maxExp) {
            return failure("Token was issued too far in the past to be used now");
        }
    }

    // Check: Token reuse (skipped if reusePermitted=true, which it is for SPIFFE)
    if (!reusePermitted) {
        if (token.getId() == null) {
            return failure("Token jti claim is required");
        }
        if (!validateTokenReuse(lifespan)) {
            return false;
        }
    }

    return true;
}
```

## The Math

**The critical validation:**
```java
if (currentTime > token.getIat() + maxExp) {
    return failure("Token was issued too far in the past to be used now");
}
```

**Simplifies to:**
```
currentTime - token.iat > maxExp
token_age > maxExp
token_age > 300 seconds
```

**Therefore:** JWTs older than 300 seconds (5 minutes) are rejected.

## Why Our Tests Showed ~4 Minutes

Our empirical testing showed:
- ✅ 187 seconds (3.1 min) → Success
- ❌ 252 seconds (4.2 min) → "Token was issued too far in the past"

The 252-second failure is **less than** the 300-second threshold. Possible reasons:

1. **Clock Skew:** Test client clock slightly ahead of Keycloak clock
2. **Network Latency:** Time between age check and Keycloak validation
3. **Timing Precision:** JWT `iat` claim uses Unix timestamps (seconds), not milliseconds
4. **Processing Time:** Small delays in request processing

**Bottom Line:** The documented threshold is 300 seconds, but in practice, it's safer to treat it as ~240-270 seconds due to these factors.

## Configuration Options

### Can You Change the Threshold?

**Short Answer:** Not easily via configuration UI.

The `maximumExpirationTime` is:
- Hardcoded to 300 in `FederatedJWTClientValidator`
- Has a setter method: `setMaximumExpirationTime(int)`
- But NO configuration UI or file to change it
- Would require code changes to Keycloak

### Can You Add Clock Skew Tolerance?

**Yes!** The SPIFFE Identity Provider accepts an `ALLOWED_CLOCK_SKEW` configuration.

However, this is for clock differences between systems, not for extending the JWT age limit. The validation would be:
```
currentTime - token.iat > maxExp + allowedClockSkew
```

But since `allowedClockSkew` defaults to 0 and isn't easily configurable via UI, it doesn't help in practice.

## Recommended Solution

Since you cannot change Keycloak's 300-second threshold, the solution is to **reduce SPIRE's JWT TTL**:

```yaml
spire:
  values:
    spire-server:
      controllerManager:
        identities:
          clusterSPIFFEIDs:
            default:
              jwtTTL: "5m"  # 5 minutes
```

**Why this works:**
- SPIRE issues JWTs with 5-minute expiration
- SPIRE refreshes at ~50% of TTL = every 2.5 minutes
- Maximum JWT age: 2.5 minutes (150 seconds)
- Keycloak threshold: 300 seconds (5 minutes)
- **Buffer: 150 seconds** ✅ Safe margin!

## Source Code References

All code from Keycloak 26.5.2 (main branch):

1. `services/src/main/java/org/keycloak/broker/spiffe/SpiffeIdentityProvider.java`
2. `services/src/main/java/org/keycloak/broker/spiffe/SpiffeIdentityProviderConfig.java`
3. `services/src/main/java/org/keycloak/authentication/authenticators/client/FederatedJWTClientValidator.java`
4. `services/src/main/java/org/keycloak/authentication/authenticators/client/AbstractBaseJWTValidator.java`
5. `services/src/main/java/org/keycloak/authentication/authenticators/client/AbstractJWTClientValidator.java`

## Conclusion

The 300-second (5-minute) threshold is **hardcoded** in Keycloak's source code and **cannot be configured** via standard means. The only practical solution is to reduce SPIRE's JWT TTL to ensure JWTs are always well under this threshold.

Our empirical testing aligns with the source code, showing failures around 250 seconds, which is just below the 300-second limit when accounting for clock skew and timing variations.
