package com.resolveflow.shared.contract;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Business enumerations shared by the Java and Python sides of the protocol.
 *
 * <p>Every member here is wire-visible, and docs/domain-model.md is the authority for the value sets.
 * The frozen copy in {@code contracts/fixtures/expected-enums.json} is asserted by {@code
 * ContractCorpusAgreementTest} here and by {@code agent/tests/unit/test_contract_fixtures.py} on the
 * Python side, so a member renamed on one side fails a test on both instead of producing an
 * unroutable action at runtime.
 *
 * <p>Java names are SCREAMING_SNAKE while wire values are the mixed-case strings the documents use
 * ({@code RefundRequested}, {@code commerce-service}). That difference is deliberate and is exactly
 * why the frozen mapping exists: renaming the Java constant must not change the wire value, and
 * renaming the wire value must not be possible by accident.
 */
public final class ContractEnums {

    /** Implemented by every wire enum so the frozen mapping can be built generically. */
    public interface WireValue {
        String wire();
    }

    public enum EventType implements WireValue {
        REFUND_REQUESTED("RefundRequested"),
        RESHIP_REQUESTED("ReshipRequested"),
        REFUND_SUCCEEDED("RefundSucceeded"),
        REFUND_FAILED("RefundFailed"),
        REFUND_UNKNOWN("RefundUnknown"),
        RESHIP_SUCCEEDED("ReshipSucceeded"),
        RESHIP_FAILED("ReshipFailed"),
        RESHIP_UNKNOWN("ReshipUnknown"),
        ENTITLEMENT_COMMITTED("EntitlementCommitted"),
        ENTITLEMENT_RELEASED("EntitlementReleased");

        private final String wire;

        EventType(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** Who is allowed to publish an envelope; mirrors the schema's enum. */
    public enum Producer implements WireValue {
        CASE("case-service"),
        COMMERCE("commerce-service"),
        FULFILLMENT("fulfillment-service");

        private final String wire;

        Producer(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** The only two remediation actions in scope (docs/domain-model.md:10). */
    public enum Action implements WireValue {
        REFUND("REFUND"),
        RESHIP("RESHIP");

        private final String wire;

        Action(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** What the customer asked for; a superset of what can be executed. */
    public enum RequestedAction implements WireValue {
        REFUND("REFUND"),
        RESHIP("RESHIP"),
        EITHER("EITHER");

        private final String wire;

        RequestedAction(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** The three fixed scenarios plus the explicit out-of-scope bucket. */
    public enum CaseType implements WireValue {
        LOGISTICS("LOGISTICS"),
        DAMAGED("DAMAGED"),
        WRONG_MISSING("WRONG_MISSING"),
        OUT_OF_SCOPE("OUT_OF_SCOPE");

        private final String wire;

        CaseType(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** The Agent proposes, Java authorises (docs/contracts.md:14). */
    public enum RecommendedAction implements WireValue {
        REFUND("REFUND"),
        RESHIP("RESHIP"),
        REQUEST_INFO("REQUEST_INFO"),
        MANUAL_REVIEW("MANUAL_REVIEW"),
        REJECT("REJECT");

        private final String wire;

        RecommendedAction(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/domain-model.md:55 case lifecycle. */
    public enum CaseStatus implements WireValue {
        QUEUED("QUEUED"),
        ANALYZING("ANALYZING"),
        WAITING_CUSTOMER("WAITING_CUSTOMER"),
        PENDING_REVIEW("PENDING_REVIEW"),
        AUTHORIZED("AUTHORIZED"),
        EXECUTING("EXECUTING"),
        RECONCILING("RECONCILING"),
        CLOSED_SUCCESS("CLOSED_SUCCESS"),
        CLOSED_REJECTED("CLOSED_REJECTED"),
        CANCELLED("CANCELLED");

        private final String wire;

        CaseStatus(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/contracts.md:42 progress kinds carried over SSE. */
    public enum TimelineEventType implements WireValue {
        CASE_CREATED("CASE_CREATED"),
        AGENT_STARTED("AGENT_STARTED"),
        QUESTION_REQUIRED("QUESTION_REQUIRED"),
        PROPOSAL_READY("PROPOSAL_READY"),
        APPROVAL_REQUIRED("APPROVAL_REQUIRED"),
        EXECUTION_UPDATED("EXECUTION_UPDATED"),
        CASE_CLOSED("CASE_CLOSED");

        private final String wire;

        TimelineEventType(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/contracts.md:71 Python -> case callback kinds. */
    public enum CallbackKind implements WireValue {
        STARTED("STARTED"),
        QUESTION("QUESTION"),
        PROPOSAL("PROPOSAL"),
        FAILED("FAILED");

        private final String wire;

        CallbackKind(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/contracts.md:77 idempotent callback outcomes. */
    public enum CallbackDisposition implements WireValue {
        ACCEPTED("ACCEPTED"),
        DUPLICATE("DUPLICATE"),
        STALE("STALE");

        private final String wire;

        CallbackDisposition(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/contracts.md:76 response dispositions for idempotency keys. */
    public enum IdempotencyDisposition implements WireValue {
        CREATED("CREATED"),
        REPLAYED("REPLAYED"),
        CONFLICT("CONFLICT");

        private final String wire;

        IdempotencyDisposition(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/domain-model.md:57. */
    public enum ProposalStatus implements WireValue {
        PROPOSED("PROPOSED"),
        VALIDATED("VALIDATED"),
        STALE("STALE"),
        REJECTED("REJECTED");

        private final String wire;

        ProposalStatus(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/domain-model.md:57. */
    public enum AuthorizationStatus implements WireValue {
        PENDING_REVIEW("PENDING_REVIEW"),
        APPROVED("APPROVED"),
        REJECTED("REJECTED"),
        EXPIRED("EXPIRED"),
        REVOKED("REVOKED"),
        CONSUMED("CONSUMED");

        private final String wire;

        AuthorizationStatus(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/contracts.md:34 reviewer decisions on a pending authorisation. */
    public enum Decision implements WireValue {
        APPROVE("APPROVE"),
        REJECT("REJECT"),
        REQUEST_INFO("REQUEST_INFO");

        private final String wire;

        Decision(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/product-spec.md:19 low-risk gate outcome, computed by Java. */
    public enum RiskRoute implements WireValue {
        AUTO("AUTO"),
        REVIEW("REVIEW"),
        NEED_INFO("NEED_INFO"),
        BLOCK("BLOCK");

        private final String wire;

        RiskRoute(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** docs/domain-model.md:47 line_entitlement states. */
    public enum EntitlementState implements WireValue {
        FREE("FREE"),
        RESERVED("RESERVED"),
        IN_USE("IN_USE"),
        CONSUMED("CONSUMED");

        private final String wire;

        EntitlementState(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /**
     * docs/domain-model.md:59: a compat superset kept for deserialisation.
     *
     * <p>The target core vocabulary is five states (docs/domain-model.md:57).
     */
    public enum OperationState implements WireValue {
        CREATED("CREATED"),
        RESERVING("RESERVING"),
        RESERVED("RESERVED"),
        RECEIVED("RECEIVED"),
        STARTING("STARTING"),
        DISPATCHED("DISPATCHED"),
        IN_PROGRESS("IN_PROGRESS"),
        TARGET_SUCCEEDED("TARGET_SUCCEEDED"),
        COMMITTING("COMMITTING"),
        SUCCEEDED("SUCCEEDED"),
        UNKNOWN("UNKNOWN"),
        RELEASING("RELEASING"),
        FAILED("FAILED"),
        CANCELLED("CANCELLED");

        private final String wire;

        OperationState(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** Authority-ranked evidence sources; a tool {@code source_ref} may not be a URL. */
    public enum EvidenceSourceType implements WireValue {
        ORDER_LINE("ORDER_LINE"),
        PAYMENT_LEDGER("PAYMENT_LEDGER"),
        LINE_ENTITLEMENT("LINE_ENTITLEMENT"),
        SHIPMENT("SHIPMENT"),
        SHIPMENT_TRACK("SHIPMENT_TRACK"),
        PACKING_MANIFEST("PACKING_MANIFEST"),
        CUSTOMER_STATEMENT("CUSTOMER_STATEMENT"),
        REVIEWER_VERIFICATION("REVIEWER_VERIFICATION"),
        POLICY_RULE("POLICY_RULE");

        private final String wire;

        EvidenceSourceType(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /**
     * docs/contracts.md:14 error codes fixed before the services exist.
     *
     * <p>Only codes whose meaning the documents already decide appear here; route-specific codes are
     * added by the task that implements the route.
     */
    public enum ErrorCode implements WireValue {
        VALIDATION_FAILED("VALIDATION_FAILED"),
        UNAUTHENTICATED("UNAUTHENTICATED"),
        FORBIDDEN_SCOPE("FORBIDDEN_SCOPE"),
        NOT_FOUND("NOT_FOUND"),
        IDEMPOTENCY_CONFLICT("IDEMPOTENCY_CONFLICT"),
        STATE_CONFLICT("STATE_CONFLICT"),
        VERSION_CONFLICT("VERSION_CONFLICT"),
        SEMANTIC_INVALID("SEMANTIC_INVALID"),
        RATE_LIMITED("RATE_LIMITED"),
        SERVICE_UNAVAILABLE("SERVICE_UNAVAILABLE");

        private final String wire;

        ErrorCode(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** The reviewer's verdict on a piece of submitted evidence (docs/contracts.md:36). */
    public enum VerificationResult implements WireValue {
        CONFIRMED("CONFIRMED"),
        REFUTED("REFUTED"),
        INCONCLUSIVE("INCONCLUSIVE");

        private final String wire;

        VerificationResult(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** What the carrier's own tracking concludes (docs/domain-model.md:57); UNKNOWN is not failure. */
    public enum CarrierConclusion implements WireValue {
        LOST("LOST"),
        DELIVERED("DELIVERED"),
        IN_TRANSIT("IN_TRANSIT"),
        UNKNOWN("UNKNOWN");

        private final String wire;

        CarrierConclusion(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    /** agent_run status, fixed by docs/agent-spec.md:17. */
    public enum RunStatus implements WireValue {
        QUEUED("QUEUED"),
        RUNNING("RUNNING"),
        CALLBACK_PENDING("CALLBACK_PENDING"),
        WAITING_INPUT("WAITING_INPUT"),
        COMPLETED("COMPLETED"),
        FAILED("FAILED"),
        CANCELLED("CANCELLED"),
        STALE("STALE");

        private final String wire;

        RunStatus(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }
    /** Packing-manifest verification (docs/domain-model.md:59); NO_RECORD is not a failure. */
    public enum VerifiedStatus implements WireValue {
        VERIFIED("VERIFIED"),
        NOT_VERIFIED("NOT_VERIFIED"),
        NO_RECORD("NO_RECORD");

        private final String wire;

        VerifiedStatus(String wire) {
            this.wire = wire;
        }

        @Override
        public String wire() {
            return wire;
        }
    }

    private ContractEnums() {}

    /**
     * Every frozen group, in the order {@code expected-enums.json} lists them.
     *
     * <p>The Python package contributes the same map; the group names are the JSON keys, so a group
     * added on one side and not the other fails the comparison instead of being ignored.
     */
    public static Map<String, List<String>> wireValues() {
        Map<String, List<String>> groups = new LinkedHashMap<>();
        groups.put("event_type", valuesOf(EventType.class));
        groups.put("producer", valuesOf(Producer.class));
        groups.put("action", valuesOf(Action.class));
        groups.put("requested_action", valuesOf(RequestedAction.class));
        groups.put("case_type", valuesOf(CaseType.class));
        groups.put("recommended_action", valuesOf(RecommendedAction.class));
        groups.put("case_status", valuesOf(CaseStatus.class));
        groups.put("timeline_event_type", valuesOf(TimelineEventType.class));
        groups.put("callback_kind", valuesOf(CallbackKind.class));
        groups.put("callback_disposition", valuesOf(CallbackDisposition.class));
        groups.put("idempotency_disposition", valuesOf(IdempotencyDisposition.class));
        groups.put("proposal_status", valuesOf(ProposalStatus.class));
        groups.put("authorization_status", valuesOf(AuthorizationStatus.class));
        groups.put("decision", valuesOf(Decision.class));
        groups.put("risk_route", valuesOf(RiskRoute.class));
        groups.put("entitlement_state", valuesOf(EntitlementState.class));
        groups.put("operation_state", valuesOf(OperationState.class));
        groups.put("evidence_source_type", valuesOf(EvidenceSourceType.class));
        groups.put("error_code", valuesOf(ErrorCode.class));
        groups.put("verification_result", valuesOf(VerificationResult.class));
        groups.put("carrier_conclusion", valuesOf(CarrierConclusion.class));
        groups.put("run_status", valuesOf(RunStatus.class));
        groups.put("verified_status", valuesOf(VerifiedStatus.class));
        return Collections.unmodifiableMap(groups);
    }

    private static <E extends Enum<E> & WireValue> List<String> valuesOf(Class<E> type) {
        return Arrays.stream(type.getEnumConstants()).map(WireValue::wire).toList();
    }
}
