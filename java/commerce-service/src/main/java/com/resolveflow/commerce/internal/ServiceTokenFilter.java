package com.resolveflow.commerce.internal;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
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
 * The {@code /internal/**} surface is for services, never for users.
 *
 * <p>docs/core-contracts.md:15 asks for a service JWT with its own {@code aud}/scope, separate from
 * the user token. This filter is that boundary: a request to an internal route must carry a service
 * token, and a perfectly valid <em>user</em> token is not one — it is refused with 403 rather than
 * being treated as "somebody is logged in, so allow it".
 *
 * <p>The distinction matters for exactly the route added in C01.2: the listing takes a
 * {@code merchant_id} scope, and a user token must never be able to name one. Only Case, holding a
 * service token, calls this, and Case derives the scope from the user token it verified itself
 * (docs/core-contracts.md:26).
 *
 * <p>Failures are written in the shared error body directly rather than delegated to the exception
 * handler: this filter runs before the MVC layer, so there is no handler to reach.
 */
@Component
@Order(1)
public class ServiceTokenFilter extends OncePerRequestFilter {

    private static final String INTERNAL_PREFIX = "/internal/";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final JwtCodec codec;

    public ServiceTokenFilter(JwtCodec serviceTokenCodec) {
        this.codec = serviceTokenCodec;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(INTERNAL_PREFIX);
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
        try {
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
