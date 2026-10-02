package com.resolveflow.caseservice.casefile;

import java.time.Instant;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface CustomerCaseRepository {
    String COLUMNS = "case_id AS caseId,merchant_id AS merchantId,customer_id AS customerId,"
            + "order_id AS orderId,line_id AS lineId,description,status,input_revision AS inputRevision,"
            + "version,expires_at AS expiresAt,created_at AS createdAt,updated_at AS updatedAt";

    @Select("<script>SELECT " + COLUMNS
            + " FROM aftersale_case WHERE merchant_id=#{merchant} AND customer_id=#{customer} "
            + "<if test='line != null'>AND line_id=#{line} </if>"
            + "<if test='view == \"WAITING\"'>AND status='WAITING_CUSTOMER' </if>"
            + "<if test='view == \"REVIEW\"'>AND status='PENDING_REVIEW' </if>"
            + "<if test='view == \"PROCESSING\"'>AND status IN ('QUEUED','ANALYZING','AUTHORIZED','EXECUTING','RECONCILING') </if>"
            + "<if test='view == \"CLOSED\"'>AND status IN ('CLOSED_SUCCESS','CLOSED_REJECTED','CANCELLED') </if>"
            + "<if test='before != null'>AND (updated_at &lt; #{before} OR (updated_at=#{before} AND case_id &lt; #{id})) </if>"
            + "ORDER BY updated_at DESC,case_id DESC LIMIT #{limit}</script>")
    List<CaseRow> list(
            @Param("merchant") String merchant,
            @Param("customer") String customer,
            @Param("view") String view,
            @Param("line") String line,
            @Param("before") Instant before,
            @Param("id") String id,
            @Param("limit") int limit);

    @Select("SELECT " + COLUMNS
            + " FROM aftersale_case WHERE merchant_id=#{merchant} AND customer_id=#{customer} AND line_id=#{line} "
            + "ORDER BY CASE WHEN status NOT IN ('CLOSED_SUCCESS','CLOSED_REJECTED','CANCELLED') THEN 0 "
            + "WHEN status='CLOSED_SUCCESS' THEN 1 ELSE 2 END,updated_at DESC,case_id DESC LIMIT 1")
    CaseRow related(@Param("merchant") String merchant, @Param("customer") String customer, @Param("line") String line);
}
