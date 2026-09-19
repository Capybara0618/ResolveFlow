package com.resolveflow.caseservice.casefile;

/**
 * Where a piece of evidence came from, member for member with the contract's {@code EvidenceSourceType}.
 *
 * <p>The two halves of this enum are the reason the evidence route needs a permission rule. A
 * {@code CUSTOMER_STATEMENT} is something a person says, and the case's own customer is the only one who
 * can say it. A {@code SHIPMENT} is something the system read from Commerce; if a client could submit it,
 * the case would hold a carrier fact that no carrier ever produced.
 */
public enum EvidenceSourceType {

    /** Read from Commerce's order line. */
    ORDER_LINE(true),
    /** Read from Commerce's payment ledger. */
    PAYMENT_LEDGER(true),
    /** Read from the synthetic carrier source. */
    SHIPMENT(true),
    /** Read from the synthetic tracking history. */
    SHIPMENT_TRACK(true),
    /** Asserted by the case's customer. */
    CUSTOMER_STATEMENT(false),
    /** Recorded by merchant staff who checked something themselves (docs/domain-model.md:27). */
    REVIEWER_VERIFICATION(false),
    /** Read from an immutable policy bundle. */
    POLICY_RULE(true);

    private final boolean machineRead;

    EvidenceSourceType(boolean machineRead) {
        this.machineRead = machineRead;
    }

    /** True when this kind is a fact the platform reads, never something a caller asserts. */
    public boolean isMachineRead() {
        return machineRead;
    }

    public static EvidenceSourceType of(String requested) {
        for (EvidenceSourceType type : values()) {
            if (type.name().equals(requested)) {
                return type;
            }
        }
        throw new IllegalArgumentException("unknown evidence_kind " + requested);
    }
}
