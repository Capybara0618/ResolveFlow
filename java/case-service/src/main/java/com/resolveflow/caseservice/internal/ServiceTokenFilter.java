package com.resolveflow.caseservice.internal;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
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
 * <p>Same boundary as Commerce's, and deliberately a separate class rather than a shared one: the two
 * services are separate Spring applications and neither should be able to loosen the other's rule by
 * accident. What is shared is the thing that must be identical — {@link JwtCodec}, which is what decides
 * whether a token is a service token.
 *
 * <p>A perfectly valid <em>user</em> token is refused with 403 rather than treated as "somebody is logged in,
 * so allow it" (docs/core-contracts.md:15). This matters as soon as the Agent calls Case: the Agent holds a
 * service token with scopes, and a user token must never be able to read a policy manifest or append
 * evidence on a case.
 *
 * <p>Failures are written in the shared error body directly: this filter runs before the MVC layer, so there
 * is no exception handler to reach, and the content type is set explicitly for the same reason the handler
 * sets it — an error is not negotiated.
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
            codec.verifyAsService(header.substring("Bearer ".length()).trim(), Instant.now());
        } catch (JwtCodec.TokenException error) {
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
