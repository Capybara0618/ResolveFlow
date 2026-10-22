package com.resolveflow.shared.shopping;

import static org.assertj.core.api.Assertions.*;

import com.resolveflow.shared.shopping.ProductReviewWire.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class ProductReviewWireTest {
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void sharedFixturesRoundTripWithoutPrivateProjectionFields() throws Exception {
        var fixture = json.readTree(Files.readString(Path.of("../../contracts/core/fixtures/product-reviews.json")));
        var types = Map.of(
                "ProductReview",
                Review.class,
                "ProductReviewSummary",
                Summary.class,
                "ProductReviewPage",
                Page.class,
                "OwnProductReview",
                Own.class,
                "ProductReviewWrite",
                Write.class,
                "ProductReviewReply",
                Reply.class,
                "ProductReviewCommand",
                Command.class,
                "ProductReviewReplyCommand",
                ReplyCommand.class);
        for (var type : types.entrySet()) {
            var value = json.treeToValue(fixture.get(type.getKey()), type.getValue());
            assertThat(json.readTree(json.writeValueAsString(value))).isEqualTo(fixture.get(type.getKey()));
        }
    }

    @Test
    void bodiesAreTextAndIntegerTokensAreNeverCoerced() {
        for (String rating : new String[] {"\"5\"", "4.5"})
            assertThatThrownBy(() -> json.readValue(
                            "{\"rating\":" + rating + ",\"body\":\"text\",\"expected_version\":0}", Write.class))
                    .isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> json.readValue("{\"rating\":5,\"body\":123,\"expected_version\":0}", Write.class))
                .isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> json.readValue("{\"body\":true,\"expected_version\":1}", Reply.class))
                .isInstanceOf(RuntimeException.class);
    }
}
