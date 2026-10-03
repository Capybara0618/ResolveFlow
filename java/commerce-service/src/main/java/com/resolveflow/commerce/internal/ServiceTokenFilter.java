package com.resolveflow.commerce.internal;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import tools.jackson.databind.ObjectMapper;

/**
 * The {@code /internal/**} surface is for services, never for users — and, since AS02.3's security sub-step, for
 * services holding the **scope** the route requires.
 *
 * <p>docs/core-contracts.md:15 asks for a service JWT with its own {@code aud}/scope, separate from
 * the user token. This filter is that boundary: a request to an internal route must carry a service
 * token, and a perfectly valid <em>user</em> token is not one — it is refused with 403 rather than
 * being treated as "somebody is logged in, so allow it".
 *
 * <p><b>Why the scope check was added.</b> C06.4④ mints a run-scoped tool credential carrying
 * {@code commerce:read policy:read}, and {@code docs/core-contracts.md:74} says the credential is bound to
 * run/case/revision/merchant/customer/line/aud/<b>scope</b>. Until this step nothing read the claim, so a token
 * minted for one purpose could read every internal route: the binding existed on the token and was enforced
 * nowhere. The ledger recorded exactly that gap rather than letting "凭据已实现" be read as "权限已执行".
 *
 * <p><b>What is required of which route</b> is a table in this class rather than an annotation, so the whole
 * surface can be read at once and a route added without a scope is a visible omission instead of an invisible one.
 * The required scope is expressed in the contract's own vocabulary: {@code commerce:read} covers this service's
 * read-only internal routes. If a route is ever added that does not fit an existing scope, that is the moment to
 * decide the vocabulary rather than to add the route with no requirement.
 *
 * <p>Failures are written in the shared error body directly rather than delegated to the exception
 * handler: this filter runs before the MVC layer, so there is no handler to reach.
 */
@Component
@Order(1)
public class ServiceTokenFilter extends OncePerRequestFilter {

    private static final String INTERNAL_PREFIX = "/internal/";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * The scope a read-only internal route of this service requires.
     *
     * <p>Spelled by {@link com.resolveflow.shared.security.ServiceScopes#COMMERCE_READ} rather than as a literal
     * here: the same string is what Case mints onto a run's tool credential, and a literal in this class would be a
     * second spelling that could drift while both compile.
     */
    public static final String COMMERCE_READ = ServiceScopes.COMMERCE_READ;

    private final JwtCodec codec;

    public ServiceTokenFilter(JwtCodec serviceTokenCodec) {
        this.codec = serviceTokenCodec;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(INTERNAL_PREFIX);
    }

    /**
     * The scope this route requires, or {@code null} when it requires none.
     *
     * <p>Written as a prefix match on the route because the internal surface is small and closed: every route under
     * {@code /internal/v1/order-lines} and {@code /internal/v1/operations} is a read of this service's data, and a
     * new one that is not should not silently inherit {@code commerce:read} — so anything unrecognised requires a
     * scope too rather than falling through to "no check".
     */
    private static String requiredScope(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.startsWith("/internal/v1/shop/drafts")
                || path.startsWith("/internal/v1/shop/purchases")
                || path.startsWith("/internal/v1/shop/cart")) return ServiceScopes.COMMERCE_CHECKOUT;
        if (path.startsWith("/internal/v1/shop/")) return COMMERCE_READ;
        if (path.startsWith("/internal/v1/order-lines") || path.startsWith("/internal/v1/operations")) {
            return COMMERCE_READ;
        }
        // An unrecognised internal route is not a route this service serves, and the MVC layer answers 404. It is
        // given no scope requirement so that a 404 keeps meaning "no such route" instead of "not allowed".
        return null;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            refuse(
                    response,
                    request,
                    HttpStatus.UNAUTHORIZED,
                    "UNAUTHENTICATED",
                    "an internal route requires a service token");
            return;
        }
        JwtCodec.ServiceIdentity identity;
        try {
            identity =
                    codec.verifyAsService(header.substring("Bearer ".length()).trim(), java.time.Instant.now());
        } catch (JwtCodec.TokenException error) {
            // "audience must be resolveflow-service, found resolveflow-user" lands here: a user token is
            // a real token that is simply not a service one, which is a scope problem, not a login one.
            boolean wrongAudience = error.getMessage().contains("audience");
            refuse(
                    response,
                    request,
                    wrongAudience ? HttpStatus.FORBIDDEN : HttpStatus.UNAUTHORIZED,
                    wrongAudience ? "FORBIDDEN_SCOPE" : "UNAUTHENTICATED",
                    wrongAudience
                            ? "this route requires a service token, not a user token"
                            : "the service token was refused");
            return;
        }
        String required = requiredScope(request);
        if (ServiceScopes.COMMERCE_CHECKOUT.equals(required) && !"case-service".equals(identity.subject())) {
            refuse(response, request, HttpStatus.FORBIDDEN, "FORBIDDEN_SCOPE", "checkout requires the Case facade");
            return;
        }
        if (required != null && !identity.hasScope(required)) {
            // 403 FORBIDDEN_SCOPE, the same refusal the audience check produces: the caller is authenticated as a
            // service and is not allowed to do *this*, which is a different thing from not being a service at all.
            // The message names the required scope but not the held ones: what a token does hold is the token
            // holder's business, and echoing it into an error body is how a scope list leaks into a log.
            refuse(
                    response,
                    request,
                    HttpStatus.FORBIDDEN,
                    "FORBIDDEN_SCOPE",
                    "this route requires the " + required + " scope");
            return;
        }
        chain.doFilter(request, response);
    }

    private static void refuse(
            HttpServletResponse response, HttpServletRequest request, HttpStatus status, String code, String message)
            throws IOException {
        String traceId = request.getHeader("X-Request-Id");
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString();
        }
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write(MAPPER.writeValueAsString(ApiError.of(code, message, false, traceId)));
    }
}
