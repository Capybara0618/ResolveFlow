package com.resolveflow.shared.security;

import static org.assertj.core.api.Assertions.*;

import org.junit.jupiter.api.Test;

class IdentityAccessWireTest {
    @Test
    void credentialCarryingRequestCannotLeakItsBearerViaRecordToString() {
        assertThat(new IdentityAccessWire.Resolve("Bearer synthetic-secret", null).toString())
                .isEqualTo("Resolve[redacted]");
    }
}
