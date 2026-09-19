package com.resolveflow.caseservice.order;

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

    public RequestPrincipalResolver(JwtCodec jwtCodec, Clock clock) {
        this.codec = jwtCodec;
        this.clock = clock;
    }

    public AuthenticatedPrincipal resolve(String authorizationHeader) {
        try {
            return codec.principalFromAuthorizationHeader(authorizationHeader, Instant.now(clock));
        } catch (JwtCodec.TokenException error) {
            // The reason is logged by the codec's message but not echoed to the caller: telling a
            // client which rule its token failed helps only someone probing tokens.
            throw new UnauthenticatedException("a valid user token is required");
        }
    }
}
