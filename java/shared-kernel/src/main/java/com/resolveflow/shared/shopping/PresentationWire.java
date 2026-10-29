package com.resolveflow.shared.shopping;

import java.util.List;

public final class PresentationWire {
    private PresentationWire() {}

    public record Spec(String name, String value) {}

    public record Product(
            String product_id,
            long version,
            List<String> images,
            List<Spec> specifications,
            String shipping_note,
            String aftercare_note) {}

    public record ProductWrite(
            Long expected_version,
            List<String> images,
            List<Spec> specifications,
            String shipping_note,
            String aftercare_note) {}

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
