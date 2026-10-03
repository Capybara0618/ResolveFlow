package com.resolveflow.caseservice.order;

import com.resolveflow.caseservice.auth.PersistentAccounts;
import com.resolveflow.shared.security.AuthenticatedPrincipal;
import com.resolveflow.shared.security.JwtCodec;
import java.time.Clock;
import java.time.Instant;
import org.springframework.stereotype.Component;

/**
 * Turns the {@code Authorization} header into a principal, or refuses the request.
 *
 * <p>The public order surface has no other source of identity: the merchant and customer it queries
 * Commerce with come from a token this service verified (docs/core-contracts.md:15), never from a
 * header a proxy could set and never from the query string.
 */
@Component
public class RequestPrincipalResolver {

    /** Raised when a protected route is reached without a usable user token. */
    public static class UnauthenticatedException extends RuntimeException {

        private static final long serialVersionUID = 1L;

        public UnauthenticatedException(String message) {
            super(message);
        }
    }

    private final JwtCodec codec;
    private final Clock clock;
    private final PersistentAccounts accounts;
    private final com.resolveflow.caseservice.auth.BuyerScopes buyers;

    public RequestPrincipalResolver(
            JwtCodec jwtCodec,
            Clock clock,
            PersistentAccounts accounts,
            com.resolveflow.caseservice.auth.BuyerScopes buyers) {
        this.codec = jwtCodec;
        this.clock = clock;
        this.accounts = accounts;
        this.buyers = buyers;
    }

    public AuthenticatedPrincipal resolve(String authorizationHeader) {
        var principal = session(authorizationHeader).principal();
        requireBusinessPrincipal(principal);
        return principal;
    }

    private static void requireBusinessPrincipal(AuthenticatedPrincipal principal) {
        if (principal.role() == com.resolveflow.shared.security.Role.PLATFORM_ADMIN)
            throw new com.resolveflow.caseservice.casefile.CaseService.ForbiddenScopeException("平台管理员无交易或售后操作权限");
    }

    public AuthenticatedPrincipal forLine(String authorizationHeader, String lineId) {
        return buyers.forLine(resolve(authorizationHeader), lineId);
    }

    public AuthenticatedPrincipal forCase(String authorizationHeader, String caseId) {
        return buyers.forCase(resolve(authorizationHeader), caseId);
    }

    public Session sessionForCase(String authorizationHeader, String caseId) {
        var session = session(authorizationHeader);
        requireBusinessPrincipal(session.principal());
        return new Session(buyers.forCase(session.principal(), caseId), session.identityVersion());
    }

    /** Carries the signed version into short write transactions so reset/disable races cannot pass. */
    public record Session(AuthenticatedPrincipal principal, long identityVersion) {}

    public Session session(String authorizationHeader) {
        try {
            Instant now = Instant.now(clock);
            var principal = codec.principalFromAuthorizationHeader(authorizationHeader, now);
            long version = codec.identityVersionFromAuthorizationHeader(authorizationHeader, now);
            accounts.requireCurrent(principal, version);
            return new Session(principal, version);
        } catch (JwtCodec.TokenException error) {
            // The reason is logged by the codec's message but not echoed to the caller: telling a
            // client which rule its token failed helps only someone probing tokens.
            throw new UnauthenticatedException("a valid user token is required");
        }
    }

    public PersistentAccounts.Profile profile(String authorizationHeader) {
        try {
            return accounts.requireCurrent(
                    session(authorizationHeader).principal(),
                    codec.identityVersionFromAuthorizationHeader(authorizationHeader, Instant.now(clock)));
        } catch (JwtCodec.TokenException error) {
            throw new UnauthenticatedException("a valid user token is required");
        }
    }
}
