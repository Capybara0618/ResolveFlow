package com.resolveflow.shared.security;

import java.util.List;

/**
 * The scope vocabulary a service token is minted with (AS02.3's security sub-step).
 *
 * <p><b>Why this is shared rather than owned by the service that enforces it.</b> A scope is a name two parties
 * have to agree on — the mint writes it and the route requires it — and the two live in different processes. Case
 * mints the run's tool credential ({@code commerce:read}, {@code policy:read}) and Commerce and Case require
 * those scopes on their own internal routes, so a constant spelled once per service is three spellings that can
 * disagree while each looks right. The precedent is {@link com.resolveflow.shared.core.CoreTopicNames}: vocabulary
 * that crosses a process boundary belongs beside the codec, not inside either end.
 *
 * <p><b>What was actually wrong before.</b> C06.4④ minted the tool credential with these two scopes and
 * {@code docs/core-contracts.md:74} made scope part of the credential's binding, but {@link JwtCodec} dropped the
 * claim and no filter read it. So the vocabulary existed in exactly two places — the mint and a Python test — and
 * neither could enforce anything. The ledger refused to let that be read as "权限已执行", which is why this
 * sub-step exists.
 *
 * <p>The buyer checkout facade has a separate deployment scope. The Agent still has no write tools
 * and ToolCredentialService continues to mint only the two read scopes.
 */
public final class ServiceScopes {

    /** Read Commerce's authoritative order, shipment and refund data. */
    public static final String COMMERCE_READ = "commerce:read";

    /** Buyer checkout facade only; never included in run tool credentials. */
    public static final String COMMERCE_CHECKOUT = "commerce:checkout";

    /** Merchant fulfillment facade only; never part of Agent tool credentials. */
    public static final String COMMERCE_FULFILLMENT = "commerce:fulfillment";

    public static final String COMMERCE_CATALOG = "commerce:catalog";

    /** Read Case's material and the policy version a case is pinned to. */
    public static final String POLICY_READ = "policy:read";

    /**
     * The scopes a run's tool credential carries, in the order the contract's example publishes them.
     *
     * <p>The order matters only because a test compares the response array against it; the values are what a route
     * checks. Both are reads, and that is the whole permission the five whitelisted tools need
     * ({@code docs/agent-spec.md:26-32}).
     */
    public static final List<String> TOOL_CREDENTIAL = List.of(COMMERCE_READ, POLICY_READ);

    private ServiceScopes() {}
}
