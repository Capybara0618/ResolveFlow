package com.resolveflow.caseservice.casefile;

/**
 * The human line a trajectory row shows (the contract requires a non-empty summary, at most 500
 * characters).
 *
 * <p>It is derived from the stored row rather than stored twice: the row's {@code detail} keeps the
 * facts, and this is the sentence a person reads. The two must not be able to disagree, so the sentence
 * is computed from those facts on the way out.
 *
 * <p>An event whose detail is unreadable still shows its type and time: a trajectory with a gap is
 * better than a trajectory that fails to load, and the missing sentence is visible rather than silent.
 */
final class TimelineSummary {

    private static final int MAX_LENGTH = 500;

    private TimelineSummary() {}

    static String of(TimelineEventRow event) {
        String sentence =
                switch (event.kind()) {
                    case CASE_CREATED -> created(event);
                    case EVIDENCE_APPENDED -> appended(event);
                    case AGENT_STARTED -> "调查已受理";
                    case QUESTION_REQUIRED -> "需要客户补充说明";
                    case PROPOSAL_READY -> proposed(event);
                    case APPROVAL_REQUIRED -> "等待人工审批";
                    case EXECUTION_UPDATED -> "执行状态已更新";
                    case AGENT_FAILED -> failed(event);
                    case CASE_CLOSED -> closed(event);
                };
        return sentence.length() <= MAX_LENGTH ? sentence : sentence.substring(0, MAX_LENGTH);
    }

    private static String created(TimelineEventRow event) {
        String lineId = JsonField.of(event.detail(), "line_id");
        return lineId == null ? "客户提交退款诉求" : "客户提交退款诉求（line_id=" + lineId + "）";
    }

    /**
     * Saying who supplied the material, not just that something arrived.
     *
     * <p>"A revision moved" is exactly the kind of statement the case view exists to explain, and the two
     * possible suppliers are different facts: a customer answered, or staff checked something themselves
     * (docs/domain-model.md:27).
     */
    private static String appended(TimelineEventRow event) {
        String kind = JsonField.of(event.detail(), "evidence_kind");
        return "REVIEWER_VERIFICATION".equals(kind) ? "商家核验并记录" : "客户补充了材料";
    }

    /**
     * A failure says whether it is worth trying again, because that is what the reader has to do next.
     *
     * <p>"调查失败" alone would leave the one question a person actually has unanswered: is this case
     * waiting for a retry, or for me.
     */
    private static String failed(TimelineEventRow event) {
        boolean retryable = Boolean.TRUE.equals(JsonField.flag(event.detail(), "retryable"));
        return retryable ? "调查失败，将自动重试" : "调查失败，转人工处理";
    }

    /**
     * A proposal says whether this service could check it, because that is what happens next.
     *
     * <p>"方案已就绪" alone would be true and useless: a refusal and a validated proposal both end the run,
     * and the reader's next action is completely different — approve a checked amount, or look at why the
     * proposal could not be checked. The reason is quoted rather than summarised, because it was written for
     * exactly this reader.
     */
    private static String proposed(TimelineEventRow event) {
        String status = JsonField.of(event.detail(), "status");
        if (!"REJECTED".equals(status)) {
            Long amount = JsonField.number(event.detail(), "recomputed_amount_minor");
            return amount == null ? "方案已就绪，等待人工确认" : "方案已按政策核对，重算金额 " + amount + " 分，等待人工确认";
        }
        String reason = JsonField.of(event.detail(), "refusal_reason");
        return reason == null ? "方案未通过核对，转人工处理" : "方案未通过核对，转人工处理：" + reason;
    }

    /**
     * The terminal event says which ending it was.
     *
     * <p>{@code CASE_CLOSED} is the contract's only terminal event type, so the distinction between a
     * cancellation and any later ending lives in the detail. A view that showed "closed" for a case the
     * customer cancelled would be hiding the one fact the reader cares about.
     */
    private static String closed(TimelineEventRow event) {
        return "CANCELLED".equals(JsonField.of(event.detail(), "status")) ? "工单已取消" : "工单已关闭";
    }
}
