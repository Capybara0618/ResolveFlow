package com.resolveflow.commerce.catalog;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Profile("backend-discovery")
final class CatalogLabInstanceHeader extends OncePerRequestFilter {
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        if ("GET".equals(request.getMethod()) && "/api/v1/shop/products".equals(request.getRequestURI()))
            response.setHeader("X-ResolveFlow-Instance", Integer.toString(request.getLocalPort()));
        chain.doFilter(request, response);
    }
}
