package com.resolveflow.shared.pagination;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import org.junit.jupiter.api.Test;

class OrderReadCursorTest {
    @Test
    void preservesMicrosecondsAndReadsExistingCursors() {
        var cursor = new OrderReadCursor(Instant.parse("2026-09-20T08:00:00.123456Z"), "line:two");
        assertThat(OrderReadCursor.decode(cursor.encode())).isEqualTo(cursor);
        String legacy = Base64.getUrlEncoder()
                .withoutPadding()
                .encodeToString("1720000000123:7001".getBytes(StandardCharsets.UTF_8));
        assertThat(OrderReadCursor.decode(legacy))
                .isEqualTo(new OrderReadCursor(Instant.ofEpochMilli(1720000000123L), "7001"));
        for (String bad : new String[] {"", "???", "Zm9v", "djJ8YmFkfGxpbmU"})
            assertThatThrownBy(() -> OrderReadCursor.decode(bad)).isInstanceOf(IllegalArgumentException.class);
    }
}
