package com.resolveflow.shared.shopping;

import java.util.List;
import java.util.Map;

public final class PresentationWire {
    private PresentationWire() {}

    public record Spec(String name, String value) {}

    public record Product(
            String product_id,
            long version,
            List<String> images,
            List<Spec> specifications,
            String shipping_note,
            String aftercare_note,
            Map<String, String> variant_images) {
        public Product(
                String product_id,
                long version,
                List<String> images,
                List<Spec> specifications,
                String shipping_note,
                String aftercare_note) {
            this(product_id, version, images, specifications, shipping_note, aftercare_note, Map.of());
        }
    }

    public record ProductWrite(
            Long expected_version,
            List<String> images,
            List<Spec> specifications,
            String shipping_note,
            String aftercare_note,
            Map<String, String> variant_images) {
        public ProductWrite(
                Long expected_version,
                List<String> images,
                List<Spec> specifications,
                String shipping_note,
                String aftercare_note) {
            this(expected_version, images, specifications, shipping_note, aftercare_note, null);
        }
    }

    public record ProductCommand(String merchant_id, String actor, ProductWrite request) {}

    public record Store(
            String store_id,
            long version,
            String introduction,
            String logo_id,
            String contact_phone,
            String service_hours) {}

    public record StoreWrite(
            Long expected_version, String introduction, String logo_id, String contact_phone, String service_hours) {}

    public record StoreCommand(String merchant_id, String actor, StoreWrite request) {}

    public record Media(String media_id) {}

    public record Published(boolean published) {}
}
