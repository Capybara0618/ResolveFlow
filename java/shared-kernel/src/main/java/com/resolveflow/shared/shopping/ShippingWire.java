package com.resolveflow.shared.shopping;

public final class ShippingWire {
    private ShippingWire() {}

    public record Selection(String address_id, Long expected_version) {}

    public record Snapshot(
            String address_id,
            long version,
            String recipient,
            String phone,
            String province,
            String city,
            String district,
            String detail) {}

    public record View(Snapshot shipping) {}
}
