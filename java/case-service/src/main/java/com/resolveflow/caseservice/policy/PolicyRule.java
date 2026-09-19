package com.resolveflow.caseservice.policy;

/**
 * One rule of a bundle, member for member with the contract's {@code PolicyRule}.
 *
 * <p>{@code position} is not part of it: the contract returns rules in an order, and the order is the
 * source file's, kept in storage so a rule set is served the way it was written rather than in whatever
 * order a database happened to return.
 */
public record PolicyRule(String ruleId, String title, String text) {}
