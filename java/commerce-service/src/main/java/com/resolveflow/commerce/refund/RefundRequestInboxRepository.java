package com.resolveflow.commerce.refund;

import java.time.Instant;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * The delivery inbox (docs/domain-model.md:45).
 *
 * <p>Its primary key is the delivery's own id, and it is written **in the same transaction as the effect**:
 * a redelivery that arrives after the first one committed finds the row and is answered from the operation
 * instead of moving money again. That is why this is an inbox and not a cache — a cache can be lost, and a
 * lost claim is a second refund.
 */
@Mapper
public interface RefundRequestInboxRepository {

    @Insert("""
            INSERT INTO refund_request_inbox (request_id, operation_id, payload_hash, received_at)
            VALUES (#{requestId}, #{operationId}, #{payloadHash}, #{receivedAt})
            """)
    void insert(
            @Param("requestId") String requestId,
            @Param("operationId") String operationId,
            @Param("payloadHash") String payloadHash,
            @Param("receivedAt") Instant receivedAt);

    /**
     * The command this delivery id already carried, if any.
     *
     * <p>Read so a reuse of one request id for different money can be refused rather than silently answered
     * with somebody else's refund.
     */
    @Select("""
            SELECT request_id   AS requestId,
                   operation_id AS operationId,
                   payload_hash AS payloadHash
              FROM refund_request_inbox
             WHERE request_id = #{requestId}
            """)
    StoredRequest find(@Param("requestId") String requestId);

    /** One inbox row, exactly as stored. */
    record StoredRequest(String requestId, String operationId, String payloadHash) {}
}
