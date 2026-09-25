package com.resolveflow.caseservice.internal;

import com.resolveflow.shared.error.ApiError;
import com.resolveflow.shared.security.JwtCodec;
import com.resolveflow.shared.security.ServiceScopes;
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
 * <p>As of AS02.3's security sub-step it also enforces the **scope** a route requires, the same rule Commerce's
 * filter applies. Until then the claim was verified and dropped: C06.4④ mints a run credential carrying
 * {@code commerce:read policy:read}, {@code docs/core-contracts.md:74} makes scope part of that credential's
 * binding, and nothing read it — so "凭据已实现" could be misread as "权限已执行". The ledger refused that reading,
 * which is why the check exists.
 *
 * <p><b>Which routes require which scope</b> is a small table rather than an annotation, so the surface can be
 * read at once. The scoped routes are the two the five whitelisted tools read policy through
 * ({@code policy:read}); the credential mint, the callback and the evidence read are deliberately unscoped,
 * and the reasons are written at {@link #requiredScope}.
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

    /** The prefix of the authoritative policy text route ({@code PolicyController}). */
    private static final String POLICIES_PREFIX = "/internal/v1/policies";

    /**
     * The route suffix serving the manifest a case is pinned to ({@code PolicyManifestController}).
     *
     * <p>Matched by segment rather than by the {@code /internal/v1/cases} prefix, because three controllers share
     * that prefix: the manifest, the evidence read and the Agent callback. A prefix rule would have made
     * "read the pinned policy" and "append evidence" the same permission.
     */
    private static final String POLICY_MANIFEST_SEGMENT = "/policy-manifest";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** The scope Case's policy reads require, spelled once in the shared vocabulary. */
    public static final String POLICY_READ = ServiceScopes.POLICY_READ;

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
     * <p>Two routes are scoped, and they are exactly the ones the five whitelisted tools use to read the policy a
     * case is pinned to: the manifest and the authoritative bundle text. Both are reads
     * ({@code docs/agent-spec.md:26-32}), which is why {@code policy:read} covers both.
     *
     * <p>Three routes are <b>not</b> scoped, each for its own reason:
     * <ul>
     *   <li>{@code POST /internal/v1/runs/{run_id}/tool-credential} — this is how a run <em>obtains</em> its
     *       credential, so requiring a scope of the caller would be requiring the thing it does not have yet.
     *       The route has its own authorization (the binding must match the case and revision) and its own test
     *       pinning that a scopeless service token may still ask.
     *   <li>the Agent callback and the evidence read — these are how a run <em>reports</em> and reads back its own
     *       material, not the policy it has to cite. The evidence route is a read of one case's own material, so
     *       requiring {@code policy:read} of it would make the scope's name a lie and would say that reading
     *       evidence needs the policy permission.</li>
     * </ul>
     * Leaving them unscoped is therefore a decision rather than an omission, and it is why this is a table instead
     * of a default: a new route under {@code /internal/} that fits none of these should have the vocabulary decided
     * for it rather than silently inheriting a check or silently having none.
     */
    private static String requiredScope(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.startsWith(POLICIES_PREFIX) || path.contains(POLICY_MANIFEST_SEGMENT)) {
            return POLICY_READ;
        }
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
        String required = requiredScope(request);
        if (required != null && !identity.hasScope(required)) {
            // 403 FORBIDDEN_SCOPE, matching the audience refusal above and Commerce's filter: the caller is
            // authenticated as a service and may not do *this*, which is not the same as not being a service.
            // The message names the required scope and not the held ones — what a token holds is the holder's
            // business, and echoing a scope list into an error body is how it ends up in a log.
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
